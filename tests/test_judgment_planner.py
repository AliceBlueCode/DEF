"""judgment_planner.plan_judgments() のテスト。

判定要否の決定をナレーション生成から独立させたフェーズ(2026-08-20設計、
gm_agent.py再設計§3)。tool-calling経路・JSON-modeフォールバック経路の両方、
既存のスキル補正・all_investigators展開ロジックの移設後の挙動を検証する。
"""

from unittest.mock import patch

from def_kari.gm.judgment_planner import plan_judgments

_NAME_MAP = {"char_a": "Claude", "char_b": "Copilot"}
_MESSAGES = [{"role": "user", "content": "Claudeは物陰に何かの気配を感じた。"}]


def _base_kwargs(**overrides):
    kwargs = dict(
        session={},
        backend_id="textgen_webui",
        model_name="",
        messages=_MESSAGES,
        name_map=_NAME_MAP,
        char_game_sheets={},
        profiles={},
        scenario=None,
        user_lang="ja",
    )
    kwargs.update(overrides)
    return kwargs


# ── tool-calling経路 ──────────────────────────────────────────────

def test_tool_calling_path_used_when_capable_and_supported():
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": True}), \
         patch.dict(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat_with_tools": lambda *a, **kw: {
                 "tool_calls": [{"function": {"arguments": '{"checks":[{"character":"Claude","skill":"察知"}]}'}}],
                 "content": "",
             }}},
         ):
        result = plan_judgments(**_base_kwargs())
    assert len(result) == 1
    assert result[0]["character_id"] == "char_a"
    assert result[0]["stat"] == "察知"


def test_tool_calling_path_no_tool_call_means_no_judgment():
    """モデルがtool呼び出しをしなかった(finish_reason != tool_calls)場合は
    「判定不要」という正当な決定として扱い、JSON-modeへはフォールバックしない。"""
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": True}), \
         patch.dict(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat_with_tools": lambda *a, **kw: {"tool_calls": None, "content": "no check needed"}}},
         ):
        result = plan_judgments(**_base_kwargs())
    assert result == []


def test_tool_calling_call_failure_fails_open():
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": True}), \
         patch.dict(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat_with_tools": lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom"))}},
         ):
        result = plan_judgments(**_base_kwargs())
    assert result == []


# ── JSON-modeフォールバック経路 ────────────────────────────────────

def test_json_mode_fallback_used_when_not_tool_calling_capable():
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": False}), \
         patch(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat": lambda *a, **kw: '{"judgments":[{"character":"Copilot","skill":"共感"}]}'}},
         ):
        result = plan_judgments(**_base_kwargs())
    assert len(result) == 1
    assert result[0]["character_id"] == "char_b"
    assert result[0]["stat"] == "共感"


def test_json_mode_fallback_strips_code_block():
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": False}), \
         patch(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat": lambda *a, **kw: '```json\n{"judgments":[{"character":"Claude","skill":"推理"}]}\n```'}},
         ):
        result = plan_judgments(**_base_kwargs())
    assert len(result) == 1
    assert result[0]["stat"] == "推理"


def test_json_mode_fallback_no_judgments_returns_empty():
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": False}), \
         patch(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat": lambda *a, **kw: '{"judgments":[]}'}},
         ):
        result = plan_judgments(**_base_kwargs())
    assert result == []


def test_json_mode_fallback_malformed_json_fails_open():
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": False}), \
         patch(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat": lambda *a, **kw: "not json at all"}},
         ):
        result = plan_judgments(**_base_kwargs())
    assert result == []


def test_missing_chat_with_tools_falls_back_to_json_mode_even_if_capable():
    """バックエンドにchat_with_tools自体が無ければ、quirksがTrueでもJSON-mode経路。"""
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": True}), \
         patch(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat": lambda *a, **kw: '{"judgments":[{"character":"Claude","skill":"察知"}]}'}},
         ):
        result = plan_judgments(**_base_kwargs())
    assert len(result) == 1
    assert result[0]["character_id"] == "char_a"


# ── スキル補正・検証(既存gm_agent.pyから移設したロジック) ─────────────

def test_coc_skill_name_is_corrected():
    """CoC由来の技能名(目星)はDEFスキル(察知)へ補正される。"""
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": False}), \
         patch(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat": lambda *a, **kw: '{"judgments":[{"character":"Claude","skill":"目星"}]}'}},
         ):
        result = plan_judgments(**_base_kwargs())
    assert len(result) == 1
    assert result[0]["stat"] == "察知"


def test_invalid_skill_name_is_dropped():
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": False}), \
         patch(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat": lambda *a, **kw: '{"judgments":[{"character":"Claude","skill":"存在しない技能"}]}'}},
         ):
        result = plan_judgments(**_base_kwargs())
    assert result == []


def test_unknown_character_name_is_dropped():
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": False}), \
         patch(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat": lambda *a, **kw: '{"judgments":[{"character":"誰でもない人","skill":"察知"}]}'}},
         ):
        result = plan_judgments(**_base_kwargs())
    assert result == []


def test_stat_value_resolved_from_game_sheet():
    profiles = {"char_a": {"game_rules_sheets": {"sheet1": {"skills": {"察知": 65}, "stats": {}}}}}
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": False}), \
         patch(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat": lambda *a, **kw: '{"judgments":[{"character":"Claude","skill":"察知"}]}'}},
         ):
        result = plan_judgments(**_base_kwargs(char_game_sheets={"char_a": "sheet1"}, profiles=profiles))
    assert result[0]["stat_value"] == 65


# ── all_investigators展開・damage_on解決(シナリオ設定由来) ────────────

def _scenario_with_all_investigators(stat="察知", damage_on="failure"):
    return {
        "scenes": [{"judgments": [{"stat": stat, "all_investigators": True, "damage_on": damage_on}]}],
    }


def test_all_investigators_expands_to_every_participant():
    scenario = _scenario_with_all_investigators()
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": False}), \
         patch(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat": lambda *a, **kw: '{"judgments":[{"character":"Claude","skill":"察知"}]}'}},
         ):
        result = plan_judgments(**_base_kwargs(scenario=scenario, session={"current_scene_index": 0}))
    assert {r["character_id"] for r in result} == {"char_a", "char_b"}
    assert all(r["damage_on"] == "failure" for r in result)


def test_all_investigators_with_no_judgments_still_yields_nothing():
    """判定自体が0件なら、all_investigators設定があっても展開先が無い。"""
    scenario = _scenario_with_all_investigators()
    with patch("def_kari.gm.judgment_planner.get_quirks", return_value={"tool_calling_capable": False}), \
         patch(
             "def_kari.gm.judgment_planner.LLM_BACKENDS",
             {"textgen_webui": {"chat": lambda *a, **kw: '{"judgments":[]}'}},
         ):
        result = plan_judgments(**_base_kwargs(scenario=scenario, session={"current_scene_index": 0}))
    assert result == []
