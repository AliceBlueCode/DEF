"""GM Agent: AIキーパー（無個性モード）のナレーション生成。

Character を所有しない特殊な管理者Agent。
ルールブック・シナリオ・履歴からGM発言を生成する。
"""

import re

from def_kari.characters import load_profiles
from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.settings import load_settings
from def_kari.gm.context_builder import (
    build_trpg_context,
    build_for_gm,
    load_trpg_rulebook,
    load_trpg_scenario,
)


class GMAgent:
    """TRPGセッションのGM（キーパー）ナレーション生成を担う。

    Character非依存の管理者Agent。
    World / Story / Rule / Director の責務を統合して実行する。
    """

    def narrate(
        self,
        session: dict,
        backend_id: str = DEFAULT_LLM_BACKEND,
        inject_history: bool = True,
        session_id: str = "",
    ) -> dict:
        """セッション履歴・ルールブック・シナリオからGMナレーションを生成する。

        Args:
            session: セッション状態 dict（_sessions から渡す）
            backend_id: 使用するLLMバックエンドID
            inject_history: True なら生成テキストをセッション履歴に追加する

        Returns:
            {"text": str, "judgments": list[dict], "error": str | None}
        """
        try:
            settings = load_settings()
        except Exception:
            settings = {}
        user_lang = settings.get("user_language", "ja") or "ja"
        _is_ja = user_lang == "ja"

        rulebook = load_trpg_rulebook(session.get("trpg_rulebook", ""))
        scenario = load_trpg_scenario(session.get("trpg_scenario", ""))

        # ── システムプロンプト組み立て ──────────────────────────────
        system_parts = []
        if _is_ja:
            system_parts.append(
                "あなたはTRPGのゲームマスター（キーパー）です。"
                "語り手として物語を進行させてください。"
                "個性や感情表現は持たず、簡潔かつ情景豊かに語ります。3〜5文を目安にしてください。"
            )
        else:
            system_parts.append(
                "You are the Game Master (Keeper) of this TRPG session. "
                "Narrate as a neutral storyteller. Be concise and vivid. 3-5 sentences."
            )

        trpg_ctx = build_for_gm(rulebook, scenario or None, session, user_lang)
        if trpg_ctx:
            system_parts.append(trpg_ctx)

        # 探索者ステータス（キャラクターシート）の注入
        char_game_sheets = session.get("char_game_sheets", {})
        name_map = session.get("name_map", {})
        _profiles: dict = {}
        if char_game_sheets:
            _profiles = load_profiles()
            char_lines = []
            for _cid, _sid in char_game_sheets.items():
                _raw = _profiles.get(_cid, {})
                _sheet = _raw.get("game_rules_sheets", {}).get(_sid, {})
                _stats = _sheet.get("stats", {})
                _cname = name_map.get(_cid, _cid)
                if _stats:
                    _stat_str = "／".join(f"{k}{v['current']}" for k, v in _stats.items())
                    char_lines.append(f"・{_cname}（{_stat_str}）")
            if char_lines:
                header = "【探索者】" if _is_ja else "[Investigators]"
                system_parts.append(header + "\n" + "\n".join(char_lines))

        if _is_ja:
            system_parts.append(
                "【キーパーの役割】\n"
                "・探索者の行動・発言を受けて場面の状況や変化を描写する\n"
                "・NPCの言動・表情・反応を描写する\n"
                "・緊張感のある場面では判定が必要な状況を示唆する\n"
                "・次の展開への布石を置く\n"
                "・探索者の台詞は書かない"
            )
        else:
            system_parts.append(
                "[Keeper duties]\n"
                "- Narrate scene changes based on investigators' actions\n"
                "- Portray NPC reactions\n"
                "- Suggest when ability checks are needed\n"
                "- Do not write investigators' dialogue"
            )

        system_prompt = "\n\n".join(system_parts)

        # ── メッセージ構築 ─────────────────────────────────────────
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for h in session.get("history", [])[-20:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            if content:
                messages.append({"role": role, "content": content})
        final_prompt = (
            "キーパーとして、直近の状況を踏まえて場面を進めてください。"
            if _is_ja else
            "As Keeper, advance the scene based on recent events."
        )
        messages.append({"role": "user", "content": final_prompt})

        # ── LLM呼び出し ───────────────────────────────────────────
        if backend_id not in LLM_BACKENDS:
            backend_id = DEFAULT_LLM_BACKEND

        from def_kari.resources.vram_lock import get_vram_lock
        _vl = get_vram_lock()
        _vl.acquire()
        try:
            chat_fn = LLM_BACKENDS[backend_id]["chat"]
            text = chat_fn(messages, "", json_mode=False, options={"num_predict": 400})
        except Exception as e:
            return {"text": "", "judgments": [], "error": str(e)}
        finally:
            _vl.release()

        # ── テキスト後処理 ────────────────────────────────────────
        text = (text or "").strip()
        for _pfx in ("🎩 キーパー: ", "🎩 Keeper: ", "🎩キーパー:", "🎩Keeper:"):
            if text.startswith(_pfx):
                text = text[len(_pfx):].strip()
                break

        # 【判定】行パース（LLMが出力した場合のみ）
        _jmatch = re.search(r'【判定】(.+)', text)
        judgments: list[dict] = []
        clean_text = text
        if _jmatch:
            clean_text = text[:_jmatch.start()].strip()
            _rev_map = {v: k for k, v in name_map.items()}
            for _jpart in _jmatch.group(1).split('|'):
                _jpart = _jpart.strip()
                if ':' not in _jpart:
                    continue
                _jcname, _jstat = _jpart.split(':', 1)
                _jcname = _jcname.strip()
                _jstat = _jstat.strip()
                _jcid = _rev_map.get(_jcname)
                if not _jcid:
                    continue
                _jsheet_id = char_game_sheets.get(_jcid, '')
                _jstat_val = 0
                if _jsheet_id and _profiles:
                    _jraw = _profiles.get(_jcid, {})
                    _jsheet = _jraw.get("game_rules_sheets", {}).get(_jsheet_id, {})
                    _jstat_val = _jsheet.get("stats", {}).get(_jstat, {}).get("current", 0)
                judgments.append({
                    "character_id": _jcid,
                    "character_name": _jcname,
                    "stat": _jstat,
                    "stat_value": _jstat_val,
                })

        # ── 履歴注入 ──────────────────────────────────────────────
        if inject_history and clean_text:
            label = "🎩 キーパー" if _is_ja else "🎩 Keeper"
            session["history"].append({
                "role": "user",
                "content": f"{label}: {clean_text}",
                "character_id": "_keeper",
            })

        # ── イベントバス通知 ───────────────────────────────────────
        if session_id and clean_text:
            from def_kari.gm.events import game_event_bus, SCENE_NARRATED
            game_event_bus.emit(session_id, SCENE_NARRATED, {
                "text": clean_text,
                "judgments": judgments,
            })

        return {
            "text": clean_text,
            "judgments": judgments,
            "error": None,
        }


# モジュールレベルのシングルトン（session.py から参照）
_gm_agent = GMAgent()
