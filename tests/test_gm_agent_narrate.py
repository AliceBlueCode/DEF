"""GMAgent.narrate() のテスト(gm_agent.py再設計後)。

判定要否の決定はjudgment_planner.plan_judgments()へ切り出したため、ここでは
plan_judgmentsをモックした状態で、narrate()がシステムプロンプト・final_prompt
を正しく組み立てること、戻り値のシェイプが従来通りであること(session_gameplay.py
・フロントエンドの無改修が前提のため)を検証する。
"""

from unittest.mock import patch

from def_kari.gm.gm_agent import GMAgent


def _session(**overrides):
    base = {
        "trpg_rulebook": "",
        "trpg_scenario": "",
        "history": [{"role": "user", "content": "Claudeは扉に手をかけた。"}],
        "name_map": {"char_a": "Claude"},
        "keeper_char_id": "",
        "keeper_char_name": "",
    }
    base.update(overrides)
    return base


def _run_narrate(session, judgments, narration_text="扉の向こうから物音が聞こえる。"):
    with patch("def_kari.gm.gm_agent.load_trpg_rulebook", return_value={}), \
         patch("def_kari.gm.gm_agent.load_trpg_scenario", return_value=None), \
         patch("def_kari.gm.gm_agent.plan_judgments", return_value=judgments) as mock_plan, \
         patch.dict(
             "def_kari.gm.gm_agent.LLM_BACKENDS",
             {"textgen_webui": {"chat": lambda messages, model, json_mode, options: narration_text}},
         ):
        result = GMAgent().narrate(session, backend_id="textgen_webui", inject_history=False)
    return result, mock_plan


def test_return_shape_matches_legacy_contract():
    """session_gameplay.py::ai_keeper_narrateとフロントエンドが読む4フィールド
    (text/judgments/advance_scene/propose_end)+errorが揃っていること。"""
    result, _ = _run_narrate(_session(), judgments=[])
    assert set(result.keys()) == {"text", "judgments", "advance_scene", "propose_end", "error"}
    assert result["error"] is None


def test_judgments_from_plan_judgments_pass_through_unmodified():
    judgments = [{"character_id": "char_a", "character_name": "Claude", "stat": "察知", "stat_value": 60}]
    result, _ = _run_narrate(_session(), judgments=judgments)
    assert result["judgments"] == judgments


def test_plan_judgments_called_with_recent_history_and_backend():
    result, mock_plan = _run_narrate(_session(), judgments=[])
    assert mock_plan.called
    call_args = mock_plan.call_args[0]
    # (session, backend_id, model_name, messages, name_map, char_game_sheets, profiles, scenario, user_lang)
    assert call_args[1] == "textgen_webui"
    assert call_args[3] == [{"role": "user", "content": "Claudeは扉に手をかけた。"}]
    assert call_args[4] == {"char_a": "Claude"}


def test_no_judgments_means_no_check_instruction_in_prompt():
    captured = {}

    def _fake_chat(messages, model, json_mode, options):
        captured["messages"] = messages
        return "扉の向こうから物音が聞こえる。"

    with patch("def_kari.gm.gm_agent.load_trpg_rulebook", return_value={}), \
         patch("def_kari.gm.gm_agent.load_trpg_scenario", return_value=None), \
         patch("def_kari.gm.gm_agent.plan_judgments", return_value=[]), \
         patch.dict("def_kari.gm.gm_agent.LLM_BACKENDS", {"textgen_webui": {"chat": _fake_chat}}):
        GMAgent().narrate(_session(), backend_id="textgen_webui", inject_history=False)
    system_content = captured["messages"][0]["content"]
    assert "判定確定済み" not in system_content


def test_judgments_present_are_described_in_system_prompt_without_asking_model_to_decide():
    captured = {}

    def _fake_chat(messages, model, json_mode, options):
        captured["messages"] = messages
        return "Claudeは息を殺して気配を探った。"

    judgments = [{"character_id": "char_a", "character_name": "Claude", "stat": "察知", "stat_value": 60}]
    with patch("def_kari.gm.gm_agent.load_trpg_rulebook", return_value={}), \
         patch("def_kari.gm.gm_agent.load_trpg_scenario", return_value=None), \
         patch("def_kari.gm.gm_agent.plan_judgments", return_value=judgments), \
         patch.dict("def_kari.gm.gm_agent.LLM_BACKENDS", {"textgen_webui": {"chat": _fake_chat}}):
        GMAgent().narrate(_session(), backend_id="textgen_webui", inject_history=False)
    system_content = captured["messages"][0]["content"]
    assert "Claude:察知" in system_content
    assert "判定確定済み" in system_content


def test_final_prompt_no_longer_instructs_judgment_marker_output():
    captured = {}

    def _fake_chat(messages, model, json_mode, options):
        captured["messages"] = messages
        return "扉の向こうから物音が聞こえる。"

    with patch("def_kari.gm.gm_agent.load_trpg_rulebook", return_value={}), \
         patch("def_kari.gm.gm_agent.load_trpg_scenario", return_value=None), \
         patch("def_kari.gm.gm_agent.plan_judgments", return_value=[]), \
         patch.dict("def_kari.gm.gm_agent.LLM_BACKENDS", {"textgen_webui": {"chat": _fake_chat}}):
        GMAgent().narrate(_session(), backend_id="textgen_webui", inject_history=False)
    final_user_msg = captured["messages"][-1]["content"]
    assert "【判定】" not in final_user_msg
    assert "【シーン進行】" in final_user_msg


def test_llm_error_returns_empty_judgments_and_error_message():
    with patch("def_kari.gm.gm_agent.load_trpg_rulebook", return_value={}), \
         patch("def_kari.gm.gm_agent.load_trpg_scenario", return_value=None), \
         patch("def_kari.gm.gm_agent.plan_judgments", return_value=[]), \
         patch.dict(
             "def_kari.gm.gm_agent.LLM_BACKENDS",
             {"textgen_webui": {"chat": lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("backend down"))}},
         ):
        result = GMAgent().narrate(_session(), backend_id="textgen_webui", inject_history=False)
    assert result["judgments"] == []
    assert result["error"] == "backend down"
