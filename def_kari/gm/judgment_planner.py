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

from def_kari.llm.backend import LLM_BACKENDS
from def_kari.models.registry import get_quirks

# DEF 定義スキルのホワイトリスト
_DEF_ALLOWED_SKILLS: frozenset[str] = frozenset({
    "察知", "調査", "医学", "博学", "推理", "解読", "記憶", "操縦",
    "説得", "欺瞞", "威圧", "魅了", "意志力", "共感", "煽動", "危機察知",
    "回避", "格闘", "射撃", "隠密", "運動", "耐久", "治療", "運転",
    "社交", "情報収集", "調達", "偽装", "生存", "追跡", "潜入", "製作",
    "思考", "情動", "身体", "環境",
})

# CoC / 他システム由来の誤りを DEF スキルに補正するマップ
_SKILL_CORRECTION_MAP: dict[str, str] = {
    "目星": "察知", "聞き耳": "察知", "斥候": "察知", "観察": "察知",
    "心理学": "共感", "精神分析": "共感",
    "説得力": "説得", "交渉": "説得", "弁論": "説得",
    "機械修理": "製作", "機械工作": "製作", "電気修理": "製作",
    "製造": "製作", "工作": "製作",
    "忍び歩き": "隠密", "潜伏": "隠密",
    "水泳": "運動", "跳躍": "運動", "登攀": "運動", "登山": "運動",
    "図書館": "調査", "図書館使用": "調査", "文献調査": "調査",
    "応急手当": "治療", "医療": "医学", "外科": "医学",
    "ナビゲート": "操縦", "操縦技術": "操縦", "航法": "操縦",
    "追跡術": "追跡", "尾行": "追跡",
    "変装": "偽装",
    "天文学": "博学", "歴史": "博学", "地質学": "博学", "考古学": "博学",
    "射撃技術": "射撃", "狙撃": "射撃",
    "格闘技": "格闘", "武道": "格闘", "近接": "格闘",
    "ハッキング": "解読", "コンピュータ": "解読", "電子機器": "解読",
    "回避技術": "回避",
    "サバイバル": "生存",
    "隠蔽": "隠密",
    "威圧力": "威圧",
}

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
        if not sheet_id or not profiles:
            return 0
        raw = profiles.get(cid, {})
        sheet = raw.get("game_rules_sheets", {}).get(sheet_id, {})
        skills = sheet.get("skills", {})
        stats = sheet.get("stats", {})
        if stat in skills:
            return skills[stat]
        if stat in stats:
            return stats[stat].get("current", 0)
        return 0

    def _valid_stats_for_char(cid: str) -> frozenset[str]:
        sheet_id = char_game_sheets.get(cid, "")
        if not sheet_id or not profiles:
            return _DEF_ALLOWED_SKILLS
        raw = profiles.get(cid, {})
        sheet = raw.get("game_rules_sheets", {}).get(sheet_id, {})
        char_skills = frozenset(sheet.get("skills", {}).keys())
        char_stats = frozenset(sheet.get("stats", {}).keys())
        return _DEF_ALLOWED_SKILLS | char_skills | char_stats

    def _normalize_stat(stat: str, cid: str) -> str | None:
        valid = _valid_stats_for_char(cid)
        if stat in valid:
            return stat
        corrected = _SKILL_CORRECTION_MAP.get(stat)
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

    pairs = _decide_check_pairs(backend_id, model_name, messages, name_map, is_ja)

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
) -> list[tuple[str, str]]:
    """(character_name, skill)ペアの生の一覧を返す(バリデーション前)。
    tool-calling対応モデルならtool-calling経由、非対応ならJSON-modeプロンプト
    経由で判定する。呼び出し・解析いずれかで失敗したら空リスト(判定無し扱い、
    fail-open——ナレーション自体は判定無しでも継続できるため)。"""
    backend = LLM_BACKENDS.get(backend_id, {})
    char_names_str = ", ".join(name_map.values())

    if backend.get("chat_with_tools") and get_quirks(model_name).get("tool_calling_capable"):
        try:
            _tool_sys = (
                "あなたはTRPGの判定要否決定システムです。直近の会話を読み、"
                "探索者がスキルを使った・使うべき場面があればpropose_checksを呼び出してください。"
                f"\n探索者（このリストの名前のみ使用）：{char_names_str}"
                "\n使用できるスキル名（これ以外は絶対禁止）："
                "察知・調査・医学・博学・推理・解読・記憶・操縦・説得・欺瞞・威圧・魅了・意志力・共感・煽動・危機察知・"
                "回避・格闘・射撃・隠密・運動・耐久・治療・運転・社交・情報収集・調達・偽装・生存・追跡・潜入・製作、"
                "またはステータス名（思考・情動・身体・環境）"
            ) if is_ja else (
                "You are a TRPG judgment-necessity decider. Read the recent conversation and call "
                "propose_checks if any investigator's action calls for a skill check right now."
                f"\nInvestigators (use only these names): {char_names_str}"
                "\nOnly these exact skill names allowed: "
                "察知,調査,医学,博学,推理,解読,記憶,操縦,説得,欺瞞,威圧,魅了,意志力,共感,煽動,危機察知,"
                "回避,格闘,射撃,隠密,運動,耐久,治療,運転,社交,情報収集,調達,偽装,生存,追跡,潜入,製作,"
                "or stat names: 思考,情動,身体,環境"
            )
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
            print(f"[judgment_planner:tool_calling] error: {e}", file=_sys.stderr)
            return []

    try:
        sys_prompt = (
            "あなたはTRPGの判定要否決定システムです。直近の会話を読み、"
            "探索者がスキルを使った・使うべき場面があれば対象キャラ名とスキル名をJSONで返してください。"
            "「探索者たち」のようにまとめて書かれている場合は、場面に最も関わっているキャラを1〜2名選んでください。"
            f"\n探索者（このリストの名前のみ使用）：{char_names_str}"
            "\n使用できるスキル名（これ以外は絶対禁止・機械工作などCoCの技能名も禁止）："
            "察知・調査・医学・博学・推理・解読・記憶・操縦・説得・欺瞞・威圧・魅了・意志力・共感・煽動・危機察知・"
            "回避・格闘・射撃・隠密・運動・耐久・治療・運転・社交・情報収集・調達・偽装・生存・追跡・潜入・製作、"
            "またはステータス名（思考・情動・身体・環境）"
            "\nスキル目安：人の言動・感情を読む→共感、物や場所を観察する→察知、危険や気配を感じる→危機察知、説得・交渉→説得、機器操作→操縦、修理・製作→製作、走る・跳ぶ→運動"
            "\nなければ {\"judgments\":[]} を返してください。"
            "\n必ずJSONのみ返してください（コードブロック不要）。"
            "\n形式：{\"judgments\":[{\"character\":\"キャラ名\",\"skill\":\"スキル名\"}]}"
        ) if is_ja else (
            "You are a TRPG judgment-necessity decider. Read the recent conversation and return JSON listing "
            "any skill checks that should occur right now. "
            "If 'investigators' is used collectively, pick 1-2 most relevant characters."
            f"\nInvestigators (use only these names): {char_names_str}"
            "\nOnly these exact skill names allowed (no inventing names like 機械工作 etc.): "
            "察知,調査,医学,博学,推理,解読,記憶,操縦,説得,欺瞞,威圧,魅了,意志力,共感,煽動,危機察知,"
            "回避,格闘,射撃,隠密,運動,耐久,治療,運転,社交,情報収集,調達,偽装,生存,追跡,潜入,製作,"
            "or stat names: 思考,情動,身体,環境"
            "\nSkill guide: reading emotions/people→共感, observing objects/places→察知, "
            "sensing danger/presence→危機察知, persuading→説得, operating machinery→操縦, crafting/repairing→製作, "
            "running/jumping→運動, avoiding danger→回避"
            "\nIf none needed, return {\"judgments\":[]}."
            "\nReturn JSON only, no code blocks."
            "\nFormat: {\"judgments\":[{\"character\":\"name\",\"skill\":\"skill\"}]}"
        )
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
        print(f"[judgment_planner:json_mode] error: {e} raw={locals().get('raw', '')!r:.200}", file=_sys.stderr)
        return []
