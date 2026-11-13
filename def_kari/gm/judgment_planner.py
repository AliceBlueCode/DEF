"""判定要否の決定(ナレーション生成から独立した判定プランナー)。

これまで`gm_agent.py`の`GMAgent.narrate()`は「ナレーションを生成→生成テキストから
【判定】マーカーを正規表現で事後抽出(→抽出失敗時は別LLM呼び出しでJSON再抽出)」
という一体化した設計だった。この構造では判定の要否決定がナレーション生成と
同一呼び出しに融合してしまい、判定結果を同じターンのナレーションで語れない等の
制約があった(競合レビュー§3、2026-08-18確認・2026-08-20設計)。

本モジュールは判定の要否決定を、ナレーション生成"前"に完結する独立フェーズとして
切り出したもの。モデルがtool-calling対応(models.registry.get_quirksの
`tool_calling_capable`)なら実際のtool-calling経由で、非対応ならJSON-mode
プロンプト経由で決定する。どちらの経路でも、出力は旧・インライン抽出方式と
完全互換の`judgments`リスト(character_id/character_name/stat/stat_value/
damage_on)を返す——`session_gameplay.py`・フロントエンドの判定消費側は無改修。
"""

import json as _json
import re as _re
import sys as _sys

from def_kari.characters import resolve_char_game_sheet
from def_kari.llm.backend import LLM_BACKENDS
from def_kari.models.registry import get_quirks

# def_original の技能の一覧と補正の表は、def_original の実装にある（B-030）。この名前は、
# 以前からの呼び出し（tests/characterization を含む）のために残している。
from def_kari.trpg.systems.def_original import (  # noqa: E402
    ALLOWED_SKILLS as _DEF_ALLOWED_SKILLS,
    SKILL_CORRECTION_MAP as _SKILL_CORRECTION_MAP,
)
from def_kari.trpg import registry as _registry  # noqa: E402

_DAMAGE_ON_MAP = {"失敗": "failure", "ファンブル": "fumble", "常時": "any"}

_PROPOSE_CHECKS_TOOL = {
    "type": "function",
    "function": {
        "name": "propose_checks",
        "description": (
            "Declare which investigator(s), if any, should make a skill check "
            "right now based on the current scene. Call this even when no check "
            "is needed, with an empty checks array."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "character": {
                                "type": "string",
                                "description": "Investigator name, must match one of the listed names exactly",
                            },
                            "skill": {
                                "type": "string",
                                "description": "Skill or stat name, must be one of the allowed names",
                            },
                        },
                        "required": ["character", "skill"],
                    },
                },
            },
            "required": ["checks"],
        },
    },
}


def plan_judgments(
    session: dict,
    backend_id: str,
    model_name: str,
    messages: list[dict],
    name_map: dict,
    char_game_sheets: dict,
    profiles: dict,
    scenario: dict | None,
    user_lang: str = "ja",
    rule_system=None,
    rulebook: dict | None = None,
) -> list[dict]:
    """判定要否を決定し、検証済みの`judgments`リストを返す。

    Args:
        session: セッション状態dict(現在シーンindex参照用)
        backend_id: 使用するLLMバックエンドID
        model_name: 現在ロード中のモデル名(tool_calling_capable判定用、
            不明なら空文字で可——その場合フォールバック経路になる)
        messages: 判定材料となる直近の会話履歴(role/content dictのリスト、
            narrate()が使うものと同じ直近履歴スライスをそのまま渡す想定)
        name_map: character_id -> 表示名
        char_game_sheets: character_id -> game_sheet_id
        profiles: load_profiles()の結果
        scenario: シナリオdict(current_scene_index参照用、無ければNone)
        user_lang: "ja" | "en"
    """
    # 判定の要否を LLM に決めさせるのは def_original の仕組み。それを持たないルールシステムの卓では
    # 何もしない（B-031。判定はそのルールシステムが自分で決める）。指定が無ければ既定のルールシステム。
    system = rule_system if rule_system is not None else _registry.get(_registry.DEFAULT_RULE_SYSTEM)
    if not callable(getattr(system, "judgment_system_prompt", None)):
        return []
    rulebook = rulebook or {}
    corrections = getattr(system, "skill_corrections", {})
    is_ja = user_lang == "ja"
    rev_map = {v: k for k, v in name_map.items()}

    scene_damage_map: dict[str, str] = {}
    scene_all_investigators: set[str] = set()
    if scenario:
        scene_idx = session.get("current_scene_index", 0)
        scenes = scenario.get("scenes", [])
        cur_scene = scenes[scene_idx] if 0 <= scene_idx < len(scenes) else {}
        for sj in cur_scene.get("judgments", []):
            sj_stat = sj.get("stat")
            if not sj_stat:
                continue
            if sj.get("damage_on"):
                scene_damage_map[sj_stat] = sj["damage_on"]
            if sj.get("all_investigators"):
                scene_all_investigators.add(sj_stat)

    def _stat_val_for(cid: str, stat: str) -> int:
        sheet_id = char_game_sheets.get(cid, "")
        if not sheet_id:
            return 0
        sheet = resolve_char_game_sheet(cid, sheet_id, profiles, session)
        skills = sheet.get("skills", {})
        stats = sheet.get("stats", {})
        if stat in skills:
            return skills[stat]
        if stat in stats:
            return stats[stat].get("current", 0)
        return 0

    def _valid_stats_for_char(cid: str) -> frozenset[str]:
        sheet_id = char_game_sheets.get(cid, "")
        allowed = system.allowed_skills(rulebook)
        if not sheet_id:
            return allowed
        sheet = resolve_char_game_sheet(cid, sheet_id, profiles, session)
        char_skills = frozenset(sheet.get("skills", {}).keys())
        char_stats = frozenset(sheet.get("stats", {}).keys())
        return allowed | char_skills | char_stats

    def _normalize_stat(stat: str, cid: str) -> str | None:
        valid = _valid_stats_for_char(cid)
        if stat in valid:
            return stat
        corrected = corrections.get(stat)
        if corrected and corrected in valid:
            return corrected
        return None

    def _make_entry(cid: str, cname: str, stat: str, damage_on: str = "") -> dict:
        entry: dict = {
            "character_id": cid,
            "character_name": cname,
            "stat": stat,
            "stat_value": _stat_val_for(cid, stat),
        }
        resolved = damage_on or scene_damage_map.get(stat, "")
        if resolved:
            entry["damage_on"] = resolved
        return entry

    def _resolve_judgments_from_pairs(pairs: list[tuple[str, str]], damage_on: str = "") -> list[dict]:
        all_inv_stats = {jstat for _, jstat in pairs if jstat in scene_all_investigators}
        result = []
        seen: set[tuple[str, str]] = set()
        if all_inv_stats:
            for jstat in all_inv_stats:
                for cid, cname in name_map.items():
                    key = (cid, jstat)
                    if key not in seen:
                        seen.add(key)
                        result.append(_make_entry(cid, cname, jstat, damage_on))
        else:
            for jcname, jstat in pairs:
                jcid = rev_map.get(jcname)
                if not jcid:
                    continue
                key = (jcid, jstat)
                if key not in seen:
                    seen.add(key)
                    result.append(_make_entry(jcid, jcname, jstat, damage_on))
        return result

    def _expand_all_investigators(judgments: list[dict]) -> list[dict]:
        already: set[tuple[str, str]] = {(j["character_id"], j["stat"]) for j in judgments}
        extra = []
        for j in judgments:
            if j["stat"] not in scene_all_investigators:
                continue
            for cid, cname in name_map.items():
                key = (cid, j["stat"])
                if key not in already:
                    already.add(key)
                    extra.append(_make_entry(cid, cname, j["stat"], j.get("damage_on", "")))
        return list(judgments) + extra

    pairs = _decide_check_pairs(backend_id, model_name, messages, name_map, is_ja, system=system)

    judgments = _resolve_judgments_from_pairs(pairs)

    validated: list[dict] = []
    for j in judgments:
        norm = _normalize_stat(j["stat"], j["character_id"])
        if norm is None:
            continue
        if norm != j["stat"]:
            j = {**j, "stat": norm, "stat_value": _stat_val_for(j["character_id"], norm)}
        validated.append(j)
    judgments = validated

    if scene_all_investigators:
        judgments = _expand_all_investigators(judgments)

    return judgments


def _decide_check_pairs(
    backend_id: str,
    model_name: str,
    messages: list[dict],
    name_map: dict,
    is_ja: bool,
    system=None,
) -> list[tuple[str, str]]:
    """(character_name, skill)ペアの生の一覧を返す(バリデーション前)。
    tool-calling対応モデルならtool-calling経由、非対応ならJSON-modeプロンプト
    経由で判定する。呼び出し・解析いずれかで失敗したら空リスト(判定無し扱い、
    fail-open——ナレーション自体は判定無しでも継続できるため)。"""
    system = system if system is not None else _registry.get(_registry.DEFAULT_RULE_SYSTEM)
    backend = LLM_BACKENDS.get(backend_id, {})
    char_names_str = ", ".join(name_map.values())

    if backend.get("chat_with_tools") and get_quirks(model_name).get("tool_calling_capable"):
        try:
            _tool_sys = system.judgment_system_prompt("tools", is_ja, char_names_str)
            result = backend["chat_with_tools"](
                [{"role": "system", "content": _tool_sys}, *messages],
                model_name, [_PROPOSE_CHECKS_TOOL], options={"num_predict": 200},
            )
            tool_calls = result.get("tool_calls")
            if not tool_calls:
                return []
            args = _json.loads(tool_calls[0]["function"]["arguments"])
            return [
                (c.get("character", ""), c.get("skill", ""))
                for c in args.get("checks", [])
                if c.get("character") and c.get("skill")
            ]
        except Exception as e:
            # 診断出力はベストエフォート。Windowsのコンソール/リダイレクト先がcp932等の
            # 場合、エラーメッセージに含まれる文字でUnicodeEncodeErrorが送出され、
            # except節内での新たな例外が本来のエラーを覆い隠してしまう（2026-08-22、
            # tgw.pyの同種の不具合とあわせて発覚・修正）。
            try:
                print(f"[judgment_planner:tool_calling] error: {e}", file=_sys.stderr)
            except UnicodeEncodeError:
                pass
            return []

    try:
        sys_prompt = system.judgment_system_prompt("json", is_ja, char_names_str)
        chat_fn = LLM_BACKENDS[backend_id]["chat"]
        raw = chat_fn(
            [{"role": "system", "content": sys_prompt}, *messages],
            model_name,
            json_mode=True,
            options={"num_predict": 200},
        )
        stripped = _re.sub(r"```[a-z]*\n?", "", raw or "").strip().strip("`").strip()
        data = _json.loads(stripped or "{}")
        return [
            (j.get("character", ""), j.get("skill", ""))
            for j in data.get("judgments", [])
            if j.get("character") and j.get("skill")
        ]
    except Exception as e:
        try:
            print(f"[judgment_planner:json_mode] error: {e} raw={locals().get('raw', '')!r:.200}", file=_sys.stderr)
        except UnicodeEncodeError:
            pass
        return []
