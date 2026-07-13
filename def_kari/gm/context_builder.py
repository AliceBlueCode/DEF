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


def build_turn_instruction(
    action_count: int, speaker_name: str, other_names: list[str],
    topic: str, session_history: list[dict], current_char_id: str,
    session: dict, directives: dict, user_language: str,
) -> str:
    """ターンごとの発言指示テキストを組み立てる。"""
    _is_ja = user_language == "ja"
    if not session_history:
        if _is_ja:
            return "まず簡潔に自己紹介し、このお題に対するあなたの考えや立場を述べてください。"
        return "Start with a brief self-introduction, then state your position on the topic."
    if action_count == 0:
        others_have_spoken = any(
            h.get("role") == "assistant" and h.get("character_id") != current_char_id
            for h in session_history
        )
        if _is_ja:
            if others_have_spoken:
                return "上記の発言記録を踏まえ、他の参加者の発言に触れながら、あなた自身の立場から意見を述べてください。"
            return "上記の発言記録を踏まえ、あなた自身の立場から意見を述べてください。"
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
