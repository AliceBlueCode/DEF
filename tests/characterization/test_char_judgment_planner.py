"""C-001: `gm/judgment_planner.py` の def_original に固有の部分を固定する（技能の一覧、補正の表、
LLM に渡すプロンプト、確かめと補正の結果）。LLM はモックする。

B-030・B-031 で、技能の一覧と補正の表とプロンプトは def_original の実装へ移す。移した後も、
def_original の卓では同じ一覧・同じ表・同じプロンプトになることを、このテストで確かめる。
"""

import json
from unittest.mock import patch

import pytest

from char_helpers import assert_snapshot
from def_kari.gm import judgment_planner as jp

_NAME_MAP = {"char_a": "Claude", "char_b": "Copilot"}
_MESSAGES = [{"role": "user", "content": "Claudeは物陰に何かの気配を感じた。"}]


def test_allowed_skills_snapshot():
    assert_snapshot("judgment_planner_allowed_skills.json",
                    json.dumps(sorted(jp._DEF_ALLOWED_SKILLS), ensure_ascii=False, indent=1) + "\n")


def test_correction_map_snapshot():
    assert_snapshot("judgment_planner_correction_map.json",
                    json.dumps(jp._SKILL_CORRECTION_MAP, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def _capture_prompt(lang: str, tools: bool) -> str:
    """LLM に渡したシステムプロンプトを取り出す（json_mode 経路か tool-calling 経路）。"""
    captured = {}

    def fake_chat(messages, model, **kw):
        captured["sys"] = messages[0]["content"]
        return '{"judgments":[]}'

    def fake_tools(messages, model, tool_list, **kw):
        captured["sys"] = messages[0]["content"]
        return {"tool_calls": []}

    backend = {"chat": fake_chat}
    if tools:
        backend["chat_with_tools"] = fake_tools
    with patch.dict(jp.LLM_BACKENDS, {"_char_test": backend}), \
            patch.object(jp, "get_quirks", return_value={"tool_calling_capable": tools}):
        jp._decide_check_pairs("_char_test", "", _MESSAGES, _NAME_MAP, lang == "ja")
    return captured["sys"]


@pytest.mark.parametrize("lang", ["ja", "en"])
@pytest.mark.parametrize("tools", [False, True])
def test_prompt_snapshot(lang, tools):
    route = "tools" if tools else "json"
    assert_snapshot(f"judgment_planner_prompt_{route}_{lang}.txt", _capture_prompt(lang, tools) + "\n")


def _plan(pairs, **kw):
    args = dict(session={}, backend_id="_x", model_name="", messages=_MESSAGES, name_map=_NAME_MAP,
                char_game_sheets={}, profiles={}, scenario=None, user_lang="ja")
    args.update(kw)
    with patch.object(jp, "_decide_check_pairs", return_value=pairs):
        return jp.plan_judgments(**args)


def test_validation_and_correction():
    out = _plan([
        ("Claude", "目星"),        # 補正 → 察知
        ("Claude", "思考"),        # 能力値の名前はそのまま
        ("Copilot", "機械工作"),    # 補正 → 製作
        ("Copilot", "クトゥルフ神話"),  # 一覧にも補正の表にも無い → 落とす
        ("Nobody", "察知"),        # 参加していない名前 → 落とす
        ("Claude", "察知"),        # 補正の後と重なるが、重複の除き方は補正の前で行う
    ])
    assert [(j["character_id"], j["stat"], j["stat_value"]) for j in out] == [
        ("char_a", "察知", 0),
        ("char_a", "思考", 0),
        ("char_b", "製作", 0),
        ("char_a", "察知", 0),
    ]
