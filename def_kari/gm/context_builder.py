"""Context Builder: セッション用プロンプトコンテキストの組み立て。

GM / Player / NPC それぞれに渡す情報を構築する責務を持つ。
session.py から抽出した純粋関数群。
"""

import json
from pathlib import Path

_BASE = Path(__file__).parent.parent.parent
_TRPG_RULEBOOK_DIRS = [
    _BASE / "data" / "public" / "trpg_rules",
    _BASE / "data" / "private" / "trpg_rules",
]
_TRPG_SCENARIO_DIRS = [
    _BASE / "data" / "public" / "trpg_scenarios",
    _BASE / "data" / "private" / "trpg_scenarios",
]


def load_trpg_rulebook(rulebook_id: str) -> dict:
    if not rulebook_id:
        return {}
    for d in _TRPG_RULEBOOK_DIRS:
        path = d / f"{rulebook_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def load_trpg_scenario(scenario_id: str) -> dict:
    if not scenario_id:
        return {}
    for d in _TRPG_SCENARIO_DIRS:
        path = d / f"{scenario_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def build_trpg_context(rulebook: dict, scenario: dict | None, user_language: str) -> str:
    """TRPGモード時のルールブック・シナリオをシステムプロンプト用テキストに展開する。"""
    _is_ja = user_language == "ja"
    parts = []

    system_name = rulebook.get("rule_system_name", "")
    world = rulebook.get("world_setting", "")
    dice_sys = rulebook.get("dice_system", "1d100")
    judgment = rulebook.get("judgment", {})
    golden = rulebook.get("golden_rule", "")

    if _is_ja:
        parts.append(f"【TRPGルールブック: {system_name}】")
        if world:
            parts.append(f"世界観: {world}")
        parts.append(f"ダイスシステム: {dice_sys}")
        cond = judgment.get("success_condition", "roll_lte_skill")
        cond_label = {
            "roll_lte_skill": "ダイス目 ≤ スキル値で成功",
            "roll_gte_skill": "ダイス目 ≥ スキル値で成功",
        }.get(cond, cond)
        parts.append(f"判定: {cond_label}")
        if golden:
            parts.append(f"ゴールデンルール: {golden}")
    else:
        parts.append(f"[TRPG Rulebook: {system_name}]")
        if world:
            parts.append(f"World: {world}")
        parts.append(f"Dice system: {dice_sys}")
        cond = judgment.get("success_condition", "roll_lte_skill")
        cond_label = {
            "roll_lte_skill": "roll ≤ skill value = success",
            "roll_gte_skill": "roll ≥ skill value = success",
        }.get(cond, cond)
        parts.append(f"Judgment: {cond_label}")
        if golden:
            parts.append(f"Golden rule: {golden}")

    if scenario:
        title = scenario.get("title", "")
        synopsis = scenario.get("synopsis", "")
        current_scene = scenario.get("scenes", [{}])[0] if scenario.get("scenes") else {}
        scene_title = current_scene.get("title", "")
        scene_desc = current_scene.get("description", "")
        if _is_ja:
            parts.append(f"\n【シナリオ: {title}】")
            if synopsis:
                parts.append(f"概要: {synopsis}")
            if scene_title:
                parts.append(f"現在の場面: {scene_title}")
            if scene_desc:
                parts.append(scene_desc)
        else:
            parts.append(f"\n[Scenario: {title}]")
            if synopsis:
                parts.append(f"Synopsis: {synopsis}")
            if scene_title:
                parts.append(f"Current scene: {scene_title}")
            if scene_desc:
                parts.append(scene_desc)

    return "\n".join(parts)


def build_session_context(
    topic: str, rules: list[str], initiative: list[str],
    name_map: dict, speaker_name: str, user_language: str,
    trpg_context: str = "",
) -> str:
    """セッション参加者・お題・ルールのコンテキストを組み立てる。"""
    other_names = [name_map.get(c, c) for c in initiative if name_map.get(c, c) != speaker_name]
    parts = []
    if trpg_context:
        parts.append(trpg_context)
    if user_language == "ja":
        parts.append("【セッション情報】")
        if topic:
            parts.append(f"お題: 「{topic}」")
        parts.append(f"参加者: {', '.join(name_map.get(c, c) for c in initiative)}")
        parts.append(f"あなたの役割: {speaker_name}")
        if other_names:
            parts.append(f"対話相手: {', '.join(other_names)}")
        if rules:
            parts.append("ルール:\n" + "\n".join(f"・{r}" for r in rules))
    else:
        parts.append("[Session Info]")
        if topic:
            parts.append(f"Topic: \"{topic}\"")
        parts.append(f"Participants: {', '.join(name_map.get(c, c) for c in initiative)}")
        parts.append(f"Your role: {speaker_name}")
        if other_names:
            parts.append(f"Others: {', '.join(other_names)}")
        if rules:
            parts.append("Rules:\n" + "\n".join(f"- {r}" for r in rules))
    return "\n".join(parts)


def _append_knowledge(
    parts: list,
    char_id: str,
    character: dict,
    session: dict,
    is_ja: bool,
) -> None:
    """静的knowledge（profile）＋動的knowledge（セッション中獲得）を parts に追加する。"""
    static_knowledge = character.get("knowledge", [])
    dynamic_knowledge = session.get("player_knowledge", {}).get(char_id, [])
    all_knowledge = list(static_knowledge) + [k for k in dynamic_knowledge if k not in static_knowledge]
    if not all_knowledge:
        return
    if is_ja:
        parts.append("【あなたが知っていること】\n" + "\n".join(f"・{k}" for k in all_knowledge))
    else:
        parts.append("[What you know]\n" + "\n".join(f"- {k}" for k in all_knowledge))


def _get_current_chapter(scenario: dict, scene_index: int) -> dict | None:
    """現在のシーンインデックスからチャプターを取得する。"""
    scenes = scenario.get("scenes", [])
    if not scenes or scene_index >= len(scenes):
        return None
    current_scene_id = scenes[scene_index].get("id", "")
    return next(
        (c for c in scenario.get("chapters", []) if current_scene_id in c.get("scene_ids", [])),
        None,
    )


def build_for_gm(
    rulebook: dict,
    scenario: dict | None,
    session: dict,
    user_language: str,
) -> str:
    """GM専用コンテキスト: gm_notes / NPC目標 / 全フラグを含む完全情報。"""
    _is_ja = user_language == "ja"
    parts = []

    base = build_trpg_context(rulebook, None, user_language)
    if base:
        parts.append(base)

    if not scenario:
        return "\n".join(parts)

    current_scene_idx = session.get("current_scene_index", 0)
    scenes = scenario.get("scenes", [])
    current_scene = (
        scenes[current_scene_idx]
        if 0 <= current_scene_idx < len(scenes)
        else (scenes[0] if scenes else {})
    )
    title = scenario.get("title", "")
    synopsis = scenario.get("synopsis", "")
    current_chapter = _get_current_chapter(scenario, current_scene_idx)

    if _is_ja:
        parts.append(f"\n【シナリオ: {title}（GM全情報）】")
        if synopsis:
            parts.append(f"概要: {synopsis}")
        if current_chapter:
            parts.append(f"現在のチャプター: {current_chapter.get('title', '')}")
        if current_scene.get("title"):
            parts.append(f"現在の場面: {current_scene['title']}")
        if current_scene.get("description"):
            parts.append(current_scene["description"])
        if current_scene.get("gm_notes"):
            parts.append(f"[GMメモ] {current_scene['gm_notes']}")
        if current_scene.get("recommended_rounds"):
            parts.append(
                f"[推奨ラウンド数] {current_scene['recommended_rounds']}ラウンド程度。"
                "場の盛り上がりや探索者の反応に応じて増減してよい。"
            )

        npc_ids = current_scene.get("npcs", [])
        all_npcs = {n["id"]: n for n in scenario.get("npcs", []) if "id" in n}
        npc_lines = []
        for nid in npc_ids:
            npc = all_npcs.get(nid)
            if npc:
                line = f"・{npc.get('name', nid)}: {npc.get('description', '')}"
                if npc.get("gm_notes"):
                    line += f" [真実: {npc['gm_notes']}]"
                if npc.get("goal"):
                    line += f" [目的: {npc['goal']}]"
                npc_lines.append(line)
        if npc_lines:
            parts.append("【登場NPC（GM情報）】\n" + "\n".join(npc_lines))

        scene_judgments = current_scene.get("judgments", [])
        if scene_judgments:
            j_lines = []
            for j in scene_judgments:
                stat = j.get("stat", "")
                desc = j.get("description", "")
                success = j.get("success", "")
                failure = j.get("failure", "")
                damage_on = j.get("damage_on", "")
                line = f"・{desc} → {stat}判定"
                if success:
                    line += f"（成功: {success}）"
                if failure:
                    line += f"（失敗: {failure}）"
                if damage_on == "failure":
                    line += "【失敗時ダメージあり→【判定:失敗】キャラ名:スキル名 を使うこと】"
                elif damage_on == "fumble":
                    line += "【ファンブル時ダメージあり→【判定:ファンブル】キャラ名:スキル名 を使うこと】"
                elif damage_on == "any":
                    line += "【結果に関わらずダメージあり→【判定:常時】キャラ名:スキル名 を使うこと】"
                j_lines.append(line)
            parts.append(
                "【判定機会（GM専用）】\n"
                "判定が必要と判断したらナレーション末尾に【判定】または【判定:失敗】【判定:ファンブル】キャラ名:スキル名 を付記する。\n"
                + "\n".join(j_lines)
            )

        flags = scenario.get("flags", [])
        if flags:
            flag_lines = [
                f"・{f['key']}: {f['value']}{'（GM専用）' if f.get('gm_only') else ''}"
                for f in flags
            ]
            parts.append("【フラグ状態】\n" + "\n".join(flag_lines))

        _end_cond = scenario.get("end_condition", "")
        _is_last_scene = (len(scenes) > 0 and current_scene_idx == len(scenes) - 1)
        if _end_cond:
            if _is_last_scene:
                _rec_r = current_scene.get("recommended_rounds", 3)
                _scene_start = session.get("scene_round_start", 0)
                _cur_r = session.get("round", 1)
                _elapsed = _cur_r - _scene_start
                _remaining = max(0, _rec_r * 2 - _elapsed)
                _urgency = (
                    f"（経過{_elapsed}ラウンド／推奨{_rec_r}――あと{_remaining}ラウンドで自動終了）"
                    if _remaining > 0
                    else "（⚠ 推奨ラウンド2倍超過——次のナレーションで必ず締めること）"
                )
                parts.append(
                    f"【⚠ 最終シーン／セッション終了条件】現在は最終シーン「{current_scene.get('title', '')}」です。{_urgency}\n"
                    f"終了条件: {_end_cond}\n"
                    "上記の条件が達成されたと判断したら、そのナレーションの末尾の最後の行に"
                    "【セッション終了提案】とだけ書いた1行を必ず追加すること。"
                    "（【シーン進行】がある場合はその直後。条件が未達成なら出力しない。）"
                )
            else:
                parts.append(
                    f"【セッション終了条件】{_end_cond}\n"
                    "上記の終了条件が物語上で達成されたと判断したら、ナレーション末尾に"
                    "【セッション終了提案】の1行を追加すること（【シーン進行】がある場合はその後）。"
                )
        else:
            parts.append(
                "【セッション終了について】全シーンが完了し、探索者の目的が達成されて物語が"
                "自然に完結したと判断した場合のみ、ナレーション末尾に【セッション終了提案】の1行を追加してよい。"
            )
    else:
        parts.append(f"\n[Scenario: {title} (GM Full Info)]")
        if synopsis:
            parts.append(f"Synopsis: {synopsis}")
        if current_chapter:
            parts.append(f"Current chapter: {current_chapter.get('title', '')}")
        if current_scene.get("title"):
            parts.append(f"Current scene: {current_scene['title']}")
        if current_scene.get("description"):
            parts.append(current_scene["description"])
        if current_scene.get("gm_notes"):
            parts.append(f"[GM Notes] {current_scene['gm_notes']}")
        if current_scene.get("recommended_rounds"):
            parts.append(
                f"[Recommended rounds] ~{current_scene['recommended_rounds']}. "
                "Adjust based on the flow of the scene."
            )

        npc_ids = current_scene.get("npcs", [])
        all_npcs = {n["id"]: n for n in scenario.get("npcs", []) if "id" in n}
        npc_lines = []
        for nid in npc_ids:
            npc = all_npcs.get(nid)
            if npc:
                line = f"- {npc.get('name', nid)}: {npc.get('description', '')}"
                if npc.get("gm_notes"):
                    line += f" [Truth: {npc['gm_notes']}]"
                if npc.get("goal"):
                    line += f" [Goal: {npc['goal']}]"
                npc_lines.append(line)
        if npc_lines:
            parts.append("[NPCs (GM Info)]\n" + "\n".join(npc_lines))

        scene_judgments = current_scene.get("judgments", [])
        if scene_judgments:
            j_lines = []
            for j in scene_judgments:
                stat = j.get("stat", "")
                desc = j.get("description", "")
                success = j.get("success", "")
                failure = j.get("failure", "")
                damage_on = j.get("damage_on", "")
                line = f"- {desc} → {stat} check"
                if success:
                    line += f" (success: {success})"
                if failure:
                    line += f" (failure: {failure})"
                if damage_on == "failure":
                    line += " [DAMAGE ON FAILURE → use 【判定:失敗】CharName:Skill]"
                elif damage_on == "fumble":
                    line += " [DAMAGE ON FUMBLE → use 【判定:ファンブル】CharName:Skill]"
                elif damage_on == "any":
                    line += " [DAMAGE ALWAYS → use 【判定:常時】CharName:Skill]"
                j_lines.append(line)
            parts.append(
                "[Judgment Opportunities (GM only)]\n"
                "When a check is warranted, append 【判定】or 【判定:失敗】【判定:ファンブル】CharName:StatName at end of narration.\n"
                + "\n".join(j_lines)
            )

        flags = scenario.get("flags", [])
        if flags:
            flag_lines = [
                f"- {f['key']}: {f['value']}{' (GM only)' if f.get('gm_only') else ''}"
                for f in flags
            ]
            parts.append("[Flag State]\n" + "\n".join(flag_lines))

        _end_cond = scenario.get("end_condition", "")
        _is_last_scene = (len(scenes) > 0 and current_scene_idx == len(scenes) - 1)
        if _end_cond:
            if _is_last_scene:
                parts.append(
                    f"[⚠ FINAL SCENE / Session End Condition] Current scene '{current_scene.get('title', '')}' is the LAST scene.\n"
                    f"End condition: {_end_cond}\n"
                    "When this condition is met, you MUST append 【セッション終了提案】 as the very last line of your narration "
                    "(after 【シーン進行】 if present). Do not output it before the condition is met."
                )
            else:
                parts.append(
                    f"[Session End Condition] {_end_cond}\n"
                    "When this condition is narratively met, output 【セッション終了提案】 on the last line "
                    "(after 【シーン進行】 if present)."
                )
        else:
            parts.append(
                "[Session End] Only when all scenes are complete and the investigators' goal is naturally achieved, "
                "you may output 【セッション終了提案】 on the last line."
            )

    return "\n".join(parts)


def build_for_player(
    char_id: str,
    character: dict,
    rulebook: dict,
    scenario: dict | None,
    session: dict,
    user_language: str,
) -> str:
    """プレイヤー専用コンテキスト: そのキャラが知っている情報のみ。

    - シーンの description のみ（gm_notes 除外）
    - NPC の description のみ（gm_notes / goal 除外）
    - 自分の knowledge（静的＋セッション中獲得）
    - gm_only: false のフラグのみ
    """
    _is_ja = user_language == "ja"
    parts = []

    if scenario:
        if _is_ja:
            parts.append(
                "【重要】あなたはこのシーンにいる探索者としてロールプレイしてください。"
                "AIモデルとしての自己紹介・AI技術の解説・メタコメントは禁止です。"
                "シーンの状況と自分のキャラクターとして自然に行動してください。"
                "以下のメタデータを出力することは絶対に禁止です："
                "image_prompt_en・image_prompt・emotion・tags・---区切り線・括弧内のト書き注記（例: *（声は低く）*）。"
                "セリフと行動描写のみを出力してください。"
            )
        else:
            parts.append(
                "[IMPORTANT] Roleplay as an explorer in this scene. "
                "Do not introduce yourself as an AI model or make technical/meta commentary. "
                "Act naturally as your character within the scene. "
                "Never output metadata fields: image_prompt_en, image_prompt, emotion, tags, "
                "separator lines (---), or parenthetical stage directions like *(quietly)*. "
                "Output only dialogue and action narrative."
            )

    base = build_trpg_context(rulebook, None, user_language)
    if base:
        parts.append(base)

    if not scenario:
        _append_knowledge(parts, char_id, character, session, _is_ja)
        return "\n".join(parts)

    current_scene_idx = session.get("current_scene_index", 0)
    scenes = scenario.get("scenes", [])
    current_scene = (
        scenes[current_scene_idx]
        if 0 <= current_scene_idx < len(scenes)
        else (scenes[0] if scenes else {})
    )
    title = scenario.get("title", "")
    current_chapter = _get_current_chapter(scenario, current_scene_idx)

    if _is_ja:
        parts.append(f"\n【シナリオ: {title}】")
        if current_chapter:
            parts.append(f"チャプター: {current_chapter.get('title', '')}")
        if current_scene.get("title"):
            parts.append(f"現在の場面: {current_scene['title']}")
        if current_scene.get("description"):
            parts.append(current_scene["description"])

        npc_ids = current_scene.get("npcs", [])
        all_npcs = {n["id"]: n for n in scenario.get("npcs", []) if "id" in n}
        npc_lines = [
            f"・{all_npcs[nid].get('name', nid)}: {all_npcs[nid].get('description', '')}"
            for nid in npc_ids if nid in all_npcs
        ]
        if npc_lines:
            parts.append("【登場NPC】\n" + "\n".join(npc_lines))

        public_flags = [f for f in scenario.get("flags", []) if not f.get("gm_only")]
        if public_flags:
            parts.append("【状況】\n" + "\n".join(f"・{f['key']}: {f['value']}" for f in public_flags))
    else:
        parts.append(f"\n[Scenario: {title}]")
        if current_chapter:
            parts.append(f"Chapter: {current_chapter.get('title', '')}")
        if current_scene.get("title"):
            parts.append(f"Current scene: {current_scene['title']}")
        if current_scene.get("description"):
            parts.append(current_scene["description"])

        npc_ids = current_scene.get("npcs", [])
        all_npcs = {n["id"]: n for n in scenario.get("npcs", []) if "id" in n}
        npc_lines = [
            f"- {all_npcs[nid].get('name', nid)}: {all_npcs[nid].get('description', '')}"
            for nid in npc_ids if nid in all_npcs
        ]
        if npc_lines:
            parts.append("[NPCs]\n" + "\n".join(npc_lines))

        public_flags = [f for f in scenario.get("flags", []) if not f.get("gm_only")]
        if public_flags:
            parts.append("[Status]\n" + "\n".join(f"- {f['key']}: {f['value']}" for f in public_flags))

    _append_knowledge(parts, char_id, character, session, _is_ja)
    return "\n".join(parts)


def build_for_npc(
    npc_id: str,
    npc_data: dict,
    rulebook: dict,
    scenario: dict | None,
    session: dict,
    user_language: str,
) -> str:
    """NPC専用コンテキスト: そのNPCの目標・知識・関係性を含む。

    npc_data（シナリオ静的定義）と session["npc_state"][npc_id]（動的更新分）をマージする。
    - knowledge: 静的 + 動的（重複排除）
    - relationship: 静的をベースに動的で上書き（動的優先）
    """
    _is_ja = user_language == "ja"
    parts = []

    current_scene_idx = session.get("current_scene_index", 0)
    scenes = (scenario or {}).get("scenes", [])
    current_scene = (
        scenes[current_scene_idx]
        if scenario and 0 <= current_scene_idx < len(scenes)
        else {}
    )

    # セッション中に動的更新された NPC 状態をマージ
    dynamic = session.get("npc_state", {}).get(npc_id, {})
    static_knowledge = npc_data.get("knowledge", [])
    dynamic_knowledge = dynamic.get("knowledge", [])
    knowledge = list(static_knowledge) + [k for k in dynamic_knowledge if k not in static_knowledge]

    static_rel = npc_data.get("relationship", {})
    dynamic_rel = dynamic.get("relationship", {})
    relationships = {**static_rel, **dynamic_rel}  # 動的優先

    if _is_ja:
        if current_scene.get("description"):
            parts.append(f"現在の場面: {current_scene['description']}")
        if npc_data.get("goal"):
            parts.append(f"【あなたの目的】{npc_data['goal']}")
        if knowledge:
            parts.append("【あなたが知っていること】\n" + "\n".join(f"・{k}" for k in knowledge))
        if relationships:
            rel_lines = [
                f"・{cid}: 信頼{v.get('trust', 50)} 敵意{v.get('hostility', 0)}"
                for cid, v in relationships.items()
            ]
            parts.append("【関係性】\n" + "\n".join(rel_lines))
    else:
        if current_scene.get("description"):
            parts.append(f"Current scene: {current_scene['description']}")
        if npc_data.get("goal"):
            parts.append(f"[Your goal] {npc_data['goal']}")
        if knowledge:
            parts.append("[What you know]\n" + "\n".join(f"- {k}" for k in knowledge))
        if relationships:
            rel_lines = [
                f"- {cid}: trust={v.get('trust', 50)} hostility={v.get('hostility', 0)}"
                for cid, v in relationships.items()
            ]
            parts.append("[Relationships]\n" + "\n".join(rel_lines))

    return "\n".join(parts)


def build_turn_instruction(
    action_count: int, speaker_name: str, other_names: list[str],
    topic: str, session_history: list[dict], current_char_id: str,
    session: dict, directives: dict, user_language: str,
) -> str:
    """ターンごとの発言指示テキストを組み立てる。"""
    _is_ja = user_language == "ja"
    _is_trpg = session.get("trpg_mode", False)
    if not session_history:
        if _is_ja:
            if _is_trpg:
                return "あなたはこのシーンにいる探索者です。AIとしての自己紹介は不要です。目の前の状況に自然に反応し、探索者として行動・発言してください。"
            return "まず簡潔に自己紹介し、このお題に対するあなたの考えや立場を述べてください。"
        if _is_trpg:
            return "You are an explorer in this scene. Do not introduce yourself as an AI. React naturally to the situation and act as your character."
        return "Start with a brief self-introduction, then state your position on the topic."
    if action_count == 0:
        others_have_spoken = any(
            h.get("role") == "assistant" and h.get("character_id") != current_char_id
            for h in session_history
        )
        if _is_ja:
            if _is_trpg:
                if others_have_spoken:
                    return "上記の状況と他の探索者の行動を踏まえ、探索者としてこの場面に自然に反応してください。AIとしての解説・メタコメントは禁止です。発言は3文以内で簡潔にまとめてください。"
                return "この場面の状況を踏まえ、探索者として自然に行動・発言してください。AIとしての解説・メタコメントは禁止です。発言は3文以内で簡潔にまとめてください。"
            if others_have_spoken:
                return "上記の発言記録を踏まえ、他の参加者の発言に触れながら、あなた自身の立場から意見を述べてください。"
            return "上記の発言記録を踏まえ、あなた自身の立場から意見を述べてください。"
        if _is_trpg:
            if others_have_spoken:
                return "Based on the situation and what other explorers have done, react naturally as your character. No AI meta-commentary. Keep your response to 3 sentences or fewer."
            return "React naturally to this scene as your character. No AI meta-commentary. Keep your response to 3 sentences or fewer."
        if others_have_spoken:
            return "Based on the discussion above, respond to what other participants have said and express your own position."
        return "Based on the discussion above, express your own position."
    _cur_round = session.get("round", 1)
    _cur_turn = session.get("turn", 0)
    turn_actions = [
        h["content"].split(": ", 1)[-1]
        for h in session_history
        if h.get("character_id") == current_char_id
        and h.get("round") == _cur_round
        and h.get("turn") == _cur_turn
    ]
    prev_block = "\n".join(f"・{a}" for a in turn_actions) if turn_actions else ""
    directive = directives.get(str(action_count), "")
    if _is_ja:
        text = f"このターンであなたは既に以下の発言をしています:\n{prev_block}\n\n"
        text += f"【アクション{action_count + 1}の指示】{directive}" if directive else "続けて発言してください。"
    else:
        text = f"You have already said the following this turn:\n{prev_block}\n\n"
        text += f"[Action {action_count + 1} directive] {directive}" if directive else "Please continue."
    return text
