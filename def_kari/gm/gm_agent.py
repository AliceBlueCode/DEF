"""GM Agent: AIキーパー（無個性モード）のナレーション生成。

Character を所有しない特殊な管理者Agent。
ルールブック・シナリオ・履歴からGM発言を生成する。
"""

import re

from def_kari.characters import load_profiles, get_character

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
    # CoC 技能 → DEF
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
                "・上記の探索者以外の人物（NPC除く）を絶対に登場させない。シナリオに何人と書かれていても、このセッションの人数が全て\n"
                "・【判定機会】に記載されたスキルで判定が必要と判断したら、ナレーション末尾に【判定】キャラ名:スキル名 を付記する\n"
                "・探索者が誰かの心理を読む・何かを調べる・説得する・行動する場面では、ナレーション末尾にシステムシグナルを出力すること\n"
                "・システムシグナルの形式：【判定】キャラ名:スキル名（最終行のみ、1行で）\n"
                "・使用できるスキル名は以下のみ。それ以外の名称は絶対に使用禁止（機械工作・鍵開け・水泳などCoCやその他のシステムの技能名は使わない）：\n"
                "  思考系：察知・調査・医学・博学・推理・解読・記憶・操縦\n"
                "  情動系：説得・欺瞞・威圧・魅了・意志力・共感・煽動・危機察知\n"
                "  身体系：回避・格闘・射撃・隠密・運動・耐久・治療・運転\n"
                "  環境系：社交・情報収集・調達・偽装・生存・追跡・潜入・製作\n"
                "  またはステータス名：思考・情動・身体・環境\n"
                "  スキル選択の目安：物や場所を調べる→察知、論理的思考・機械操作→推理、複雑な機器の操作→操縦、修理・制作→製作、"
                "危険を察知する→危機察知、人の心を読む→共感、走る・跳ぶ→運動、罠を回避→回避\n"
                "  複数名同時：【判定】Claude:共感|Copilot:察知\n"
                "  全員に影響する罠・崩落・感電・毒など：参加者全員を列挙する 例→【判定】Alice:察知|Bob:察知|Carol:察知\n"
                "・禁止：「共感が必要です」「判定が必要そうです」「察知で調べましょう」など判定を文章で表現すること\n"
                "  NG→「彼の言葉の真意を見抜くため、心理状況を把握する必要があります」\n"
                "  OK→「彼は語り続けた。\n【判定】Claude:共感」\n"
                "・【判定】は全角の【】を使うこと。成功・失敗の結果は書かない（ロール後に決まる）"
            )
        else:
            system_parts.append(
                "[Keeper duties]\n"
                "- Narrate scene changes based on investigators' actions\n"
                "- Portray NPC reactions\n"
                "- Do not write investigators' dialogue\n"
                "- Never introduce characters other than the listed investigators (and scenario NPCs). "
                "The session participant count above is absolute — ignore any other number in the scenario text\n"
                "- When a check from [Judgment Opportunities] is warranted, append 【判定】CharName:StatName "
                "on the last line of narration only\n"
                "- When investigators read someone's psychology, examine objects, or take action, output a system signal on the last line\n"
                "  Format: 【判定】CharName:Skill (one line, end of narration only)\n"
                "- ONLY use these exact Japanese skill names — never invent names like 機械工作, 鍵開け, etc.:\n"
                "  思考-group: 察知, 調査, 医学, 博学, 推理, 解読, 記憶, 操縦\n"
                "  情動-group: 説得, 欺瞞, 威圧, 魅了, 意志力, 共感, 煽動, 危機察知\n"
                "  身体-group: 回避, 格闘, 射撃, 隠密, 運動, 耐久, 治療, 運転\n"
                "  環境-group: 社交, 情報収集, 調達, 偽装, 生存, 追跡, 潜入, 製作\n"
                "  Or stat names: 思考, 情動, 身体, 環境\n"
                "  Skill guide: reading emotions/people→共感, examining/observing→察知, sensing danger/presence→危機察知, persuading→説得, "
                "機器操作/複雑な装置→操縦, 修理・製作→製作, running/jumping→運動, avoiding danger→回避\n"
                "  Multiple: 【判定】Claude:共感|Copilot:察知\n"
                "  Scene-wide hazard (trap/collapse/poison affecting everyone): list ALL investigators → 【判定】Alice:察知|Bob:察知|Carol:察知\n"
                "- BANNED: writing judgment as prose — 'needs a psychology check', 'it seems a check is needed'\n"
                "  NG→ 'Claude tries to read the truth behind his words, needing to grasp the psychological state'\n"
                "  OK→ 'He continued speaking.\n【判定】Claude:Psychology'\n"
                "- Do not write success or failure outcomes — determined after the roll"
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
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for h in session.get("history", [])[-20:]:
            role = h.get("role", "user")
            content = h.get("content", "")
            if content:
                messages.append({"role": role, "content": content})
        final_prompt = (
            "キーパーとして、直近の状況を踏まえて場面を進めてください。"
            "探索者がスキルを使う場面があれば、ナレーション末尾に【判定】キャラ名:スキル名 の1行を出力すること。"
            "文章で判定を表現することは禁止。"
            "シーンの目的が達成され次の場面へ進む準備ができたと判断した場合は、ナレーション末尾に【シーン進行】の1行を出力すること（判定がある場合は判定の後）。"
            "セッション終了条件が達成されたと判断した場合は、ナレーション末尾に【セッション終了提案】の1行を出力すること（【シーン進行】の後）。"
            if _is_ja else
            "As Keeper, advance the scene based on recent events. "
            "If investigators use a skill, output 【判定】CharName:Skill on the last line only. "
            "Never express judgment in prose. "
            "If the scene objectives are met and it is time to move to the next scene, output 【シーン進行】 on the last line (after 【判定】 if present). "
            "If the session end condition is met, output 【セッション終了提案】 on the last line (after 【シーン進行】 if present)."
        )
        messages.append({"role": "user", "content": final_prompt})

        # ── LLM呼び出し ───────────────────────────────────────────
        if backend_id not in LLM_BACKENDS:
            backend_id = DEFAULT_LLM_BACKEND

        from def_kari.models.registry import get_llm_profile

        # プロファイルの generation_params をベースに、GM固定値で上書き
        _gm_opts: dict = {}
        if backend_id == "textgen_webui":
            from def_kari.llm.tgw_manager import get_loaded_model_name
            _loaded_model = get_loaded_model_name() or ""
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

        # 【判定】行パース（インライン検出 or 2パス）
        _rev_map = {v: k for k, v in name_map.items()}
        judgments: list[dict] = []
        clean_text = text

        _DAMAGE_ON_MAP = {"失敗": "failure", "ファンブル": "fumble", "常時": "any"}

        # シナリオの現在シーンから stat→damage_on / all_investigators マップを構築
        _scene_damage_map: dict[str, str] = {}
        _scene_all_investigators: set[str] = set()
        if scenario:
            _scene_idx = session.get("current_scene_index", 0)
            _scenes = scenario.get("scenes", [])
            _cur_scene = _scenes[_scene_idx] if 0 <= _scene_idx < len(_scenes) else {}
            for _sj in _cur_scene.get("judgments", []):
                _sj_stat = _sj.get("stat")
                if not _sj_stat:
                    continue
                if _sj.get("damage_on"):
                    _scene_damage_map[_sj_stat] = _sj["damage_on"]
                if _sj.get("all_investigators"):
                    _scene_all_investigators.add(_sj_stat)

        def _stat_val_for(cid: str, stat: str) -> int:
            _jsheet_id = char_game_sheets.get(cid, '')
            if not _jsheet_id or not _profiles:
                return 0
            _jraw = _profiles.get(cid, {})
            _jsheet = _jraw.get("game_rules_sheets", {}).get(_jsheet_id, {})
            _jskills = _jsheet.get("skills", {})
            _jstats = _jsheet.get("stats", {})
            if stat in _jskills:
                return _jskills[stat]
            if stat in _jstats:
                return _jstats[stat].get("current", 0)
            return 0

        def _valid_stats_for_char(cid: str) -> frozenset[str]:
            """キャラクターシートのスキル/ステータス名 + DEF定義スキルを返す"""
            _jsheet_id = char_game_sheets.get(cid, '')
            if not _jsheet_id or not _profiles:
                return _DEF_ALLOWED_SKILLS
            _jraw = _profiles.get(cid, {})
            _jsheet = _jraw.get("game_rules_sheets", {}).get(_jsheet_id, {})
            char_skills = frozenset(_jsheet.get("skills", {}).keys())
            char_stats = frozenset(_jsheet.get("stats", {}).keys())
            return _DEF_ALLOWED_SKILLS | char_skills | char_stats

        def _normalize_stat(stat: str, cid: str) -> str | None:
            """スキル名を正規化。補正できなければ None（ドロップ対象）"""
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
            resolved = damage_on or _scene_damage_map.get(stat, "")
            if resolved:
                entry["damage_on"] = resolved
            return entry

        def _resolve_judgments_from_pairs(pairs: list[tuple[str, str]], damage_on: str = "") -> list[dict]:
            # all_investigators スタットが含まれているか先に確認
            all_inv_stats = {_jstat for _, _jstat in pairs if _jstat in _scene_all_investigators}

            result = []
            seen: set[tuple[str, str]] = set()

            if all_inv_stats:
                # all_investigators スタットが出たら、そのスタットのみ全員に展開し、
                # 他のキャラ固有判定は捨てる
                for _jstat in all_inv_stats:
                    for _cid, _cname in name_map.items():
                        key = (_cid, _jstat)
                        if key not in seen:
                            seen.add(key)
                            result.append(_make_entry(_cid, _cname, _jstat, damage_on))
            else:
                for _jcname, _jstat in pairs:
                    _jcid = _rev_map.get(_jcname)
                    if not _jcid:
                        continue
                    key = (_jcid, _jstat)
                    if key not in seen:
                        seen.add(key)
                        result.append(_make_entry(_jcid, _jcname, _jstat, damage_on))
            return result

        def _expand_all_investigators(judgments: list[dict]) -> list[dict]:
            """GMが1人しか書かなかった場合に全参加者へ補完"""
            already: set[tuple[str, str]] = {(j["character_id"], j["stat"]) for j in judgments}
            extra = []
            for j in judgments:
                if j["stat"] not in _scene_all_investigators:
                    continue
                for _cid, _cname in name_map.items():
                    key = (_cid, j["stat"])
                    if key not in already:
                        already.add(key)
                        extra.append(_make_entry(_cid, _cname, j["stat"], j.get("damage_on", "")))
            return list(judgments) + extra

        _judgment_mode = settings.get("keeper_judgment_mode", "inline")

        # インライン検出（1パス）: 【判定】or【判定:失敗】etc.
        _jmatch = re.search(r'[【\[]判定(?::([^】\]]+))?[】\]]\s*(.+)', text)
        if _jmatch:
            clean_text = text[:_jmatch.start()].strip()
            _damage_qualifier = (_jmatch.group(1) or "").strip()
            _damage_on = _DAMAGE_ON_MAP.get(_damage_qualifier, "")
            _pairs = []
            for _jpart in _jmatch.group(2).split('|'):
                _jpart = _jpart.strip()
                # 2個目の【判定】以降は別エントリ扱い、ここでは切り捨て
                _jpart = re.split(r'[【\[]判定', _jpart)[0].strip()
                if ':' in _jpart:
                    _jcname, _jstat = _jpart.split(':', 1)
                    # stat名が長すぎる・句読点含む場合は不正パース → スキップ
                    _jstat = re.split(r'[。、．,\s]', _jstat.strip())[0]
                    if _jcname.strip() and _jstat.strip() and len(_jstat.strip()) <= 20:
                        _pairs.append((_jcname.strip(), _jstat.strip()))
            judgments = _resolve_judgments_from_pairs(_pairs, _damage_on)

        # 2パス検出（インラインで取れなかった場合 or 2パスモード）
        if _judgment_mode == "twopass" and not judgments and char_game_sheets:
            try:
                _char_list = ", ".join(name_map.get(cid, cid) for cid in char_game_sheets)
                _char_names_str = ", ".join(name_map.get(cid, cid) for cid in char_game_sheets)
                _j2_sys = (
                    "あなたはTRPGの判定抽出システムです。キーパーナレーションを読み、"
                    "探索者がスキルを使った・使うべき場面があれば対象キャラ名とスキル名をJSONで返してください。"
                    "「探索者たち」のようにまとめて書かれている場合は、場面に最も関わっているキャラを1〜2名選んでください。"
                    f"\n探索者（このリストの名前のみ使用）：{_char_names_str}"
                    "\n使用できるスキル名（これ以外は絶対禁止・機械工作などCoCの技能名も禁止）："
                    "察知・調査・医学・博学・推理・解読・記憶・操縦・説得・欺瞞・威圧・魅了・意志力・共感・煽動・危機察知・"
                    "回避・格闘・射撃・隠密・運動・耐久・治療・運転・社交・情報収集・調達・偽装・生存・追跡・潜入・製作、"
                    "またはステータス名（思考・情動・身体・環境）"
                    "\nスキル目安：人の言動・感情を読む→共感、物や場所を観察する→察知、危険や気配を感じる→危機察知、説得・交渉→説得、機器操作→操縦、修理・製作→製作、走る・跳ぶ→運動"
                    "\nなければ {\"judgments\":[]} を返してください。"
                    "\n必ずJSONのみ返してください（コードブロック不要）。"
                    "\n形式：{\"judgments\":[{\"character\":\"キャラ名\",\"skill\":\"スキル名\"}]}"
                ) if _is_ja else (
                    "You are a TRPG judgment extractor. Read the keeper narration and return JSON listing "
                    "any skill checks that occurred or should occur. "
                    "If 'investigators' is used collectively, pick 1-2 most relevant characters."
                    f"\nInvestigators (use only these names): {_char_names_str}"
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
                _j2_messages = [
                    {"role": "system", "content": _j2_sys},
                    {"role": "user", "content": clean_text},
                ]
                _j2_vl = get_vram_lock()
                _j2_vl.acquire()
                try:
                    _j2_raw = chat_fn(_j2_messages, "", json_mode=True, options={"num_predict": 200})
                finally:
                    _j2_vl.release()
                import json as _json, re as _re
                # コードブロック除去してから parse
                _j2_stripped = _re.sub(r'```[a-z]*\n?', '', _j2_raw or '').strip().strip('`').strip()
                _j2_data = _json.loads(_j2_stripped or "{}")
                _pairs2 = [
                    (j.get("character", ""), j.get("skill", ""))
                    for j in _j2_data.get("judgments", [])
                    if j.get("character") and j.get("skill")
                ]
                judgments = _resolve_judgments_from_pairs(_pairs2)
                import sys
                print(f"[2pass] raw={_j2_stripped[:120]!r} pairs={_pairs2} resolved={len(judgments)}", file=sys.stderr)
            except Exception as _j2e:
                import sys
                print(f"[2pass] error: {_j2e}", file=sys.stderr)

        # スキル名バリデーション（inline / twopass 両パス共通）
        # 補正マップで修正 → それでも無効ならドロップ
        import sys as _sys
        _validated: list[dict] = []
        for _j in judgments:
            _norm = _normalize_stat(_j["stat"], _j["character_id"])
            if _norm is None:
                print(f"[skill_drop] {_j['stat']!r} is not a valid DEF skill for {_j['character_id']!r}", file=_sys.stderr)
                continue
            if _norm != _j["stat"]:
                print(f"[skill_normalize] {_j['stat']!r} → {_norm!r} for {_j['character_id']!r}", file=_sys.stderr)
                _j = {**_j, "stat": _norm, "stat_value": _stat_val_for(_j["character_id"], _norm)}
            _validated.append(_j)
        judgments = _validated

        # all_investigators 展開（GMが1人しか書かなかった場合に全員へ補完）
        if _scene_all_investigators:
            judgments = _expand_all_investigators(judgments)

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
