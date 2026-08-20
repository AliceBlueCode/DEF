"""GM Agent: AIキーパー（無個性モード）のナレーション生成。

Character を所有しない特殊な管理者Agent。
ルールブック・シナリオ・履歴からGM発言を生成する。
"""

import re

from def_kari.characters import load_profiles, get_character
from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.settings import load_settings
from def_kari.gm.context_builder import (
    build_trpg_context,
    build_for_gm,
    load_trpg_rulebook,
    load_trpg_scenario,
)
from def_kari.gm.judgment_planner import plan_judgments


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

        # ── キーパーキャラクター人格の取得 ──────────────────────────
        _keeper_char_id = session.get("keeper_char_id", "")
        _keeper_char_name = session.get("keeper_char_name", "")
        _keeper_persona_desc = ""
        _keeper_speech_style = ""
        if _keeper_char_id:
            _kp_char = get_character(_keeper_char_id)
            if _kp_char:
                _keeper_persona_desc = _kp_char.get("persona_description", "")
                _keeper_speech_style = _kp_char.get("speech_style", "")
        _keeper_display_name = _keeper_char_name or _keeper_char_id

        import sys as _sys_gm
        print(
            f"[gm_agent] keeper_char_id={_keeper_char_id!r} "
            f"keeper_char_name={_keeper_char_name!r} "
            f"persona_len={len(_keeper_persona_desc)} "
            f"speech_style={_keeper_speech_style[:60]!r}",
            file=_sys_gm.stderr,
        )

        # ── システムプロンプト組み立て ──────────────────────────────
        # 人物設定は _keeper_char_id の有無で判定（char_name が空でも機能する）
        _has_keeper_persona = bool(_keeper_char_id and _keeper_persona_desc)
        system_parts = []
        if _is_ja:
            if _has_keeper_persona:
                system_parts.append(
                    f"あなたは「{_keeper_display_name}」という人物です。\n"
                    f"{_keeper_persona_desc}\n\n"
                    f"あなた（{_keeper_display_name}）が今、TRPGのゲームマスターとして参加者に場面を語りかけます。"
                    "GMとしての役割（判定・シーン進行）は後述の形式で行いますが、"
                    "ナレーション本文はあなた自身の口調・感情・個性でそのまま語ってください。"
                    "必ず3〜5文で終わらせてください。それ以上書いてはいけません。"
                    "「---」などの区切り線は使用禁止。同じ文章を繰り返してはいけません。"
                    "必ず日本語のみで回答すること。英語は一切使用しない。"
                )
            else:
                system_parts.append(
                    "あなたはTRPGのゲームマスター（キーパー）です。"
                    "語り手として物語を進行させてください。"
                    "個性や感情表現は持たず、簡潔かつ情景豊かに語ります。"
                    "必ず3〜5文で終わらせてください。それ以上書いてはいけません。"
                    "「---」などの区切り線は使用禁止。同じ文章を繰り返してはいけません。"
                    "必ず日本語のみで回答すること。英語は一切使用しない。"
                )
        else:
            if _has_keeper_persona:
                system_parts.append(
                    f"You are \"{_keeper_display_name}\" — a specific character with the profile below.\n"
                    f"{_keeper_persona_desc}\n\n"
                    f"You ({_keeper_display_name}) are narrating a TRPG session as the Game Master. "
                    "GM mechanics (judgment signals, scene-advance) follow the rules below, "
                    "but the narration text itself must come through in your own voice and personality. "
                    "Always end after exactly 3-5 sentences. Do not write more. "
                    "Never use separator lines like '---'. Never repeat phrases."
                )
            else:
                system_parts.append(
                    "You are the Game Master (Keeper) of this TRPG session. "
                    "Narrate as a neutral storyteller. Be concise and vivid. "
                    "Always end after exactly 3-5 sentences. Do not write more. "
                    "Never use separator lines like '---'. Never repeat phrases."
                )

        trpg_ctx = build_for_gm(rulebook, scenario or None, session, user_lang)
        if trpg_ctx:
            system_parts.append(trpg_ctx)

        # 探索者ステータス（キャラクターシート）の注入
        char_game_sheets = session.get("char_game_sheets", {})
        name_map = session.get("name_map", {})
        _profiles: dict = {}
        char_lines = []
        if char_game_sheets:
            _profiles = load_profiles()
            for _cid, _sid in char_game_sheets.items():
                _raw = _profiles.get(_cid, {})
                _sheet = _raw.get("game_rules_sheets", {}).get(_sid, {})
                _stats = _sheet.get("stats", {})
                _cname = name_map.get(_cid, _cid)
                if _stats:
                    # runtime_stats があれば current 値を上書き
                    _runtime = session.get("runtime_stats", {}).get(_cid, {})
                    _display_stats = {
                        k: {**v, "current": _runtime.get(k, v.get("current", 0))}
                        for k, v in _stats.items()
                    }
                    _is_dead = any(v["current"] <= 0 for v in _display_stats.values())
                    _stat_str = "／".join(f"{k}{v['current']}" for k, v in _display_stats.items())
                    if _is_dead:
                        char_lines.append(f"・{_cname}（{_stat_str}）【死亡済み——死者視点で継続中】")
                    else:
                        char_lines.append(f"・{_cname}（{_stat_str}）")
                else:
                    char_lines.append(f"・{_cname}")
        elif name_map:
            # char_game_sheets がない場合でも参加者名を注入する
            char_lines = [f"・{n}" for n in name_map.values()]

        # ── 判定要否の決定(ナレーション生成前に完結させる、2026-08-20設計) ──
        # 直近履歴を使って先に判定を確定させ、ナレーション側は「判定済みの結果を
        # 自然に描写する」役割に限定する(judgment_planner.plan_judgments参照)。
        if backend_id not in LLM_BACKENDS:
            backend_id = DEFAULT_LLM_BACKEND
        _loaded_model = ""
        if backend_id == "textgen_webui":
            from def_kari.llm.tgw_manager import get_loaded_model_name
            _loaded_model = get_loaded_model_name() or ""
        _history_messages: list[dict] = []
        for h in session.get("history", [])[-20:]:
            _h_role = h.get("role", "user")
            _h_content = h.get("content", "")
            if _h_content:
                _history_messages.append({"role": _h_role, "content": _h_content})
        judgments = plan_judgments(
            session, backend_id, _loaded_model, _history_messages,
            name_map, char_game_sheets, _profiles, scenario, user_lang,
        )

        if char_lines:
            header = "【探索者】" if _is_ja else "[Investigators]"
            _participant_count = len(char_lines)
            if _is_ja:
                system_parts.append(
                    f"{header}（このセッションの参加者は以下の{_participant_count}人のみ）\n"
                    + "\n".join(char_lines)
                )
            else:
                system_parts.append(
                    f"{header} (Only these {_participant_count} participants exist in this session)\n"
                    + "\n".join(char_lines)
                )

        # 名前制約ブロック（探索者リストの直後に独立して配置）
        if name_map:
            _allowed_names_str = "・".join(name_map.values())
            _npc_names_str = ""
            if scenario:
                _npc_names = [n.get("name", "") for n in scenario.get("npcs", []) if n.get("name")]
                if _npc_names:
                    _npc_names_str = "、".join(_npc_names)
            if _is_ja:
                _name_constraint = (
                    f"【人物名の絶対制約】ナレーションに登場できる名前は「{_allowed_names_str}」"
                )
                if _npc_names_str:
                    _name_constraint += f"およびシナリオNPC「{_npc_names_str}」"
                _name_constraint += (
                    "のみ。"
                    "これ以外の人物名（Saburo・Celina 等、上記リストに存在しない名前）は絶対に出力禁止。"
                    "不明な場合は名前を使わず「誰かが」「その人物が」と表現すること。"
                )
                system_parts.append(_name_constraint)
            else:
                _allowed_names_en = ", ".join(name_map.values())
                _name_constraint_en = (
                    f"[Absolute name rule] Only use these names: {_allowed_names_en}"
                )
                if _npc_names_str:
                    _name_constraint_en += f" and scenario NPCs ({_npc_names_str})"
                _name_constraint_en += (
                    ". Never invent names not in this list. "
                    "Use 'someone' or 'a figure' when uncertain."
                )
                system_parts.append(_name_constraint_en)

        if _is_ja:
            system_parts.append(
                "【キーパーの役割】\n"
                "・探索者の行動・発言を受けて場面の状況や変化を描写する\n"
                "・NPCの言動・表情・反応を描写する\n"
                "・次の展開への布石を置く\n"
                "・探索者の台詞は書かない\n"
                "・上記の探索者以外の人物（NPC除く）を絶対に登場させない。シナリオに何人と書かれていても、このセッションの人数が全て"
            )
        else:
            system_parts.append(
                "[Keeper duties]\n"
                "- Narrate scene changes based on investigators' actions\n"
                "- Portray NPC reactions\n"
                "- Do not write investigators' dialogue\n"
                "- Never introduce characters other than the listed investigators (and scenario NPCs). "
                "The session participant count above is absolute — ignore any other number in the scenario text"
            )

        # ── 判定結果の伝達(2026-08-20設計) ─────────────────────────
        # 判定要否は上でplan_judgments()により既に確定済み。ナレーション側は
        # マーカーを自分で判断・出力する必要はなく、確定済みの内容を自然に
        # 描写するだけでよい（DiceFrameのgm_systemプロンプトと同じ「ナレーション
        # 専任・再判定禁止」の考え方）。
        if judgments:
            _judgment_desc = "・".join(f"{j['character_name']}:{j['stat']}" for j in judgments)
            if _is_ja:
                system_parts.append(
                    f"【判定確定済み】今回のターンでは既に「{_judgment_desc}」の判定が必要と決定済みです。"
                    "ナレーション本文でこの状況（誰が何のために判定を試みるか）を自然に描写してください。"
                    "成功・失敗の結果は書かないこと（ロール後に決まる）。"
                    "新たな【判定】マーカーを出力する必要はありません（システム側が別途処理します）。"
                )
            else:
                system_parts.append(
                    f"[Check already decided] This turn already determined a check is needed: {_judgment_desc}. "
                    "Narrate this situation naturally (who is attempting what, and why). "
                    "Do not write success or failure outcomes — determined after the roll. "
                    "Do not output a 【判定】 marker yourself — the system handles this separately."
                )

        # キーパーキャラクターの語り口リマインダー（duties より後に置いて優先度を上げる）
        if _keeper_char_id and _keeper_speech_style:
            if _is_ja:
                system_parts.append(
                    f"【語り口の最終指示（必須）】あなたは「{_keeper_display_name}」本人として語ります。\n"
                    f"{_keeper_speech_style}\n\n"
                    "▼ ナレーション本文で必ず実行すること:\n"
                    "・「探索者たちは…」「あなたたちは…」など無個性の三人称叙述は禁止。"
                    "一人称「私」か、参加者への直接語りかけで書くこと\n"
                    f"・{_keeper_display_name}の感情・口癖・独白が本文に1文以上あること\n"
                    "・過去の会話履歴の文体を踏襲しないこと。毎回その瞬間の自分の言葉で新しく語ること\n"
                    "・NG例:「探索者たちは慎重に歩を進めた。」\n"
                    "・OK例:「……私には、いやな予感がします。あなたたち、一歩一歩確かめながら進んでください。」"
                )
            else:
                system_parts.append(
                    f"[Final style directive — REQUIRED] You are \"{_keeper_display_name}\", narrating in your own voice.\n"
                    f"{_keeper_speech_style}\n\n"
                    "▼ You MUST do all of the following in your narration:\n"
                    "- No generic third-person like 'The investigators...' or 'You all...' — use first-person 'I' or direct address\n"
                    f"- At least one sentence showing {_keeper_display_name}'s emotion, quirk, or inner voice\n"
                    "- Do NOT copy the neutral tone of past history entries. Narrate fresh, in your own words each time"
                )

        system_prompt = "\n\n".join(system_parts)

        # ── メッセージ構築 ─────────────────────────────────────────
        # 直近履歴は判定決定フェーズで使ったものと同じスライス(_history_messages)
        # をそのまま再利用する。
        messages: list[dict] = [{"role": "system", "content": system_prompt}, *_history_messages]
        final_prompt = (
            "キーパーとして、直近の状況を踏まえて場面を進めてください。"
            "シーンの目的が達成され次の場面へ進む準備ができたと判断した場合は、ナレーション末尾に【シーン進行】の1行を出力すること。"
            "セッション終了条件が達成されたと判断した場合は、ナレーション末尾に【セッション終了提案】の1行を出力すること（【シーン進行】の後）。"
            if _is_ja else
            "As Keeper, advance the scene based on recent events. "
            "If the scene objectives are met and it is time to move to the next scene, output 【シーン進行】 on the last line. "
            "If the session end condition is met, output 【セッション終了提案】 on the last line (after 【シーン進行】 if present)."
        )
        messages.append({"role": "user", "content": final_prompt})

        # ── LLM呼び出し ───────────────────────────────────────────
        from def_kari.models.registry import get_llm_profile

        # プロファイルの generation_params をベースに、GM固定値で上書き
        _gm_opts: dict = {}
        if _loaded_model:
            _profile = get_llm_profile(_loaded_model)
            _gm_opts = dict(_profile.get("generation_params", {}))
        _gm_opts.update({"num_predict": 300, "repetition_penalty": 1.18})

        try:
            chat_fn = LLM_BACKENDS[backend_id]["chat"]
            text = chat_fn(messages, "", json_mode=False, options=_gm_opts)
        except Exception as e:
            return {"text": "", "judgments": [], "error": str(e)}

        # ── テキスト後処理 ────────────────────────────────────────
        text = (text or "").strip()
        for _pfx in (
            "🎩 キーパー: ", "🎩 Keeper: ", "🎩キーパー:", "🎩Keeper:",
            "**キーパー:**", "**Keeper:**", "**キーパー：**", "**Keeper：**",
            "キーパー:", "Keeper:", "キーパー：", "Keeper：",
        ):
            if text.startswith(_pfx):
                text = text[len(_pfx):].strip()
                break

        # --- 区切り線を除去
        text = re.sub(r'\n\s*---+\s*\n?', '\n', text)
        text = re.sub(r'^---+\s*\n?', '', text)

        # GM内部情報ブロックを以降ごと除去
        _gm_leak = re.search(
            r'(\*{0,2}[【\[](?:GMメモ|GM Notes|GM提示|判定機会|Judgment|判定を促す[^\]】]*)[】\]]\*{0,2}'
            r'|\*{0,2}判定を促すトリガー[：:]\*{0,2}'
            r'|\*{0,2}[【\[]推奨ラウンド数[】\]]\*{0,2}'
            r'|\*{0,2}[【\[]次の展開[】\]]\*{0,2}'
            r'|\*{0,2}判定提示'
            r'|\*{0,2}[【\[]GM提示[】\]]'
            r'|\*\(?GMメモ'
            r'|（GMメモ'
            r'|\*\(判定'
            r'|\(判定機会'
            r'|次の行動を(?:考え|決め)(?:てください|ましょう)'
            r'|今の場面で探索者がスキルを使う瞬間があったか'
            r'|Did any investigator use a skill this moment'
            r'|roll_lte)',
            text,
        )
        if _gm_leak:
            text = text[:_gm_leak.start()].strip()

        # メタ指示テキストを除去（*(…)* 形式・括弧内の進行ヒント）
        text = re.sub(r'\*\([^)]*\)\*', '', text)
        text = re.sub(r'\([^)]*次の行動[^)]*\)', '', text)
        text = re.sub(r'\([^)]*判定[^)]*\)', '', text)
        # *roll_xxx* 系テキストを除去
        text = re.sub(r'\*roll_\w+[^*]*\*', '', text)
        text = text.strip()

        # 判定は既にplan_judgments()で決定済み（本関数冒頭）。ここでは
        # ナレーションテキストの後処理（シーン進行/セッション終了シグナルの
        # 検出・hallucination除去）のみを行う。
        clean_text = text

        # 【シーン進行】シグナル検出
        _advance_scene = False
        if "【シーン進行】" in clean_text:
            clean_text = re.sub(r'[\n\s]*【シーン進行】[\n\s]*', '', clean_text).strip()
            _advance_scene = True

        # 【セッション終了提案】シグナル検出
        _propose_end = False
        if "【セッション終了提案】" in clean_text:
            clean_text = re.sub(r'[\n\s]*【セッション終了提案】[\n\s]*', '', clean_text).strip()
            _propose_end = True

        # フォールバック: 最終シーンで推奨ラウンドの2倍を超えたら強制提案
        if not _propose_end and scenario:
            _fb_scenes = scenario.get("scenes", [])
            _fb_idx = session.get("current_scene_index", 0)
            _fb_is_last = len(_fb_scenes) > 0 and _fb_idx == len(_fb_scenes) - 1
            _fb_end_cond = scenario.get("end_condition", "")
            if _fb_is_last and _fb_end_cond:
                _fb_rec = (_fb_scenes[_fb_idx] if _fb_idx < len(_fb_scenes) else {}).get("recommended_rounds", 3)
                _fb_start = session.get("scene_round_start", 0)
                _fb_cur = session.get("round", 1)
                _fb_elapsed = _fb_cur - _fb_start
                if _fb_elapsed >= _fb_rec * 2:
                    _propose_end = True

        # ── 存在しない人物名（hallucination）を履歴混入前に除去 ────
        if name_map and clean_text:
            _hall_allowed: set[str] = set(name_map.values())
            if _keeper_char_name:
                _hall_allowed.add(_keeper_char_name)
            if scenario:
                for _hnpc in scenario.get("npcs", []):
                    _hn = _hnpc.get("name", "")
                    if _hn:
                        _hall_allowed.add(_hn)
                        _hn_m = re.search(r'[（(]([^）)]+)[）)]', _hn)
                        if _hn_m:
                            _hall_allowed.add(_hn_m.group(1))
            _hall_re = re.compile(
                r'([A-Za-z゠-ヿ一-鿿぀-ゟ]{1,20})さん'
            )
            for _hm in list(_hall_re.finditer(clean_text)):
                _hcand = _hm.group(1)
                if not any(_hcand in n or n in _hcand for n in _hall_allowed):
                    _replacement = "誰か" if _is_ja else "someone"
                    clean_text = clean_text.replace(_hm.group(0), _replacement, 1)
                    print(
                        f"[hallucination_fix] '{_hm.group(0)}' → '{_replacement}'",
                        file=_sys_gm.stderr,
                    )

        # ── 履歴注入 ──────────────────────────────────────────────
        if inject_history and clean_text:
            _default_label = "🎩 キーパー" if _is_ja else "🎩 Keeper"
            label = f"🎩 {_keeper_display_name}" if _keeper_display_name else _default_label
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
            "advance_scene": _advance_scene,
            "propose_end": _propose_end,
            "error": None,
        }


# モジュールレベルのシングルトン（session.py から参照）
_gm_agent = GMAgent()
