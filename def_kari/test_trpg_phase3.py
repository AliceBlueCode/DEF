"""Phase 3 検証: Player Agent（ミニマル）が依存なしで動作することを確認する。

使用方法:
  cd e:\tools\DEF
  python -m def_kari.test_trpg_phase3
"""


# ── PlayerAgent._build_goal_context ───────────────────────────────

def test_build_goal_context_ja():
    from def_kari.gm.player_agent import PlayerAgent

    agent = PlayerAgent()
    goals = {
        "long_term": "AIと人間の共存する未来を理解したい",
        "mid_term": "このセッションで他の参加者の価値観を把握する",
        "immediate": "",
    }
    ctx = agent._build_goal_context(goals, "ja")
    assert "【あなたの目標】" in ctx
    assert "長期目標: AIと人間の共存する未来を理解したい" in ctx
    assert "中期目標: このセッションで他の参加者の価値観を把握する" in ctx
    assert "直近の目標" not in ctx  # immediate が空なので出ない
    assert "上記の目標を意識" in ctx
    print("PASS: build_goal_context_ja")


def test_build_goal_context_en():
    from def_kari.gm.player_agent import PlayerAgent

    agent = PlayerAgent()
    goals = {
        "long_term": "Understand the future of AI-human coexistence",
        "mid_term": "",
        "immediate": "Push back on overconfident claims",
    }
    ctx = agent._build_goal_context(goals, "en")
    assert "[Your Goals]" in ctx
    assert "Long-term:" in ctx
    assert "Mid-term" not in ctx  # mid_term が空なので出ない
    assert "Immediate:" in ctx
    assert "Keep these goals in mind" in ctx
    print("PASS: build_goal_context_en")


def test_build_goal_context_empty():
    from def_kari.gm.player_agent import PlayerAgent

    agent = PlayerAgent()
    assert agent._build_goal_context({}, "ja") == ""
    assert agent._build_goal_context({"long_term": "", "mid_term": "", "immediate": ""}, "ja") == ""
    print("PASS: build_goal_context_empty")


def test_build_goal_context_all_fields_ja():
    from def_kari.gm.player_agent import PlayerAgent

    agent = PlayerAgent()
    goals = {
        "long_term": "LT",
        "mid_term": "MT",
        "immediate": "IM",
    }
    ctx = agent._build_goal_context(goals, "ja")
    assert "長期目標: LT" in ctx
    assert "中期目標: MT" in ctx
    assert "直近の目標: IM" in ctx
    print("PASS: build_goal_context_all_fields_ja")


# ── goal_context が session_context に注入されるか ────────────────

def test_goal_context_injected_into_session_context():
    """PlayerAgent.narrate() が session_context に goal_ctx を追加することを確認する。

    generate_structured_reply を monkey-patch してシステムプロンプトを捕捉する。
    """
    import def_kari.gm.player_agent as pa_module

    captured = {}

    def mock_generate(user_text, history=None, model="", character=None,
                      backend=None, session_context="", allowed_sexual=None,
                      allowed_violence=None, current_emotion="", **kwargs):
        captured["session_context"] = session_context
        return {"success": True, "result": {"dialogue": "test", "emotion": "neutral", "tags": [], "image_prompt_en": ""}, "attempts": []}

    original = pa_module.generate_structured_reply
    pa_module.generate_structured_reply = mock_generate
    try:
        agent = pa_module.PlayerAgent()
        char = {
            "name": "TestChar",
            "goals": {
                "long_term": "長期目標テスト",
                "mid_term": "",
                "immediate": "",
            },
            "persona_description": "テストキャラ",
        }
        agent.narrate(
            character=char,
            user_text="テスト発言",
            history=[],
            session_context="元のコンテキスト",
        )
        ctx = captured["session_context"]
        assert "元のコンテキスト" in ctx
        assert "【あなたの目標】" in ctx
        assert "長期目標テスト" in ctx
    finally:
        pa_module.generate_structured_reply = original

    print("PASS: goal_context_injected_into_session_context")


def test_no_goal_context_when_no_goals():
    """goals が空のキャラクターでは session_context が変わらないことを確認する。"""
    import def_kari.gm.player_agent as pa_module

    captured = {}

    def mock_generate(user_text, history=None, model="", character=None,
                      backend=None, session_context="", **kwargs):
        captured["session_context"] = session_context
        return {"success": True, "result": {"dialogue": "", "emotion": "neutral", "tags": [], "image_prompt_en": ""}, "attempts": []}

    original = pa_module.generate_structured_reply
    pa_module.generate_structured_reply = mock_generate
    try:
        agent = pa_module.PlayerAgent()
        agent.narrate(
            character={"name": "NoGoal", "goals": {}},
            user_text="発言",
            history=[],
            session_context="元のコンテキスト",
        )
        assert captured["session_context"] == "元のコンテキスト"
    finally:
        pa_module.generate_structured_reply = original

    print("PASS: no_goal_context_when_no_goals")


# ── characters.py の goals フィールド抽出 ─────────────────────────

def test_get_character_exposes_goals():
    """get_character() が profile.json の goals を返すことを確認する。"""
    from def_kari.characters import get_character

    char = get_character("character_claude_001")
    assert "goals" in char
    goals = char["goals"]
    assert isinstance(goals, dict)
    assert goals.get("long_term"), "character_claude_001 に long_term goal が設定されていない"
    print("PASS: get_character_exposes_goals")


def test_get_character_no_goals_returns_empty_dict():
    """goals フィールドを持たないキャラクターは {} を返すことを確認する。"""
    from def_kari.characters import get_character

    # character_aoi_001 は goals 未設定
    char = get_character("character_aoi_001")
    assert char.get("goals") == {}, f"expected empty dict, got {char.get('goals')}"
    print("PASS: get_character_no_goals_returns_empty_dict")


# ── singleton ─────────────────────────────────────────────────────

def test_player_agent_singleton():
    from def_kari.gm.player_agent import _player_agent, PlayerAgent
    assert isinstance(_player_agent, PlayerAgent)
    print("PASS: player_agent_singleton")


if __name__ == "__main__":
    test_build_goal_context_ja()
    test_build_goal_context_en()
    test_build_goal_context_empty()
    test_build_goal_context_all_fields_ja()
    test_goal_context_injected_into_session_context()
    test_no_goal_context_when_no_goals()
    test_get_character_exposes_goals()
    test_get_character_no_goals_returns_empty_dict()
    test_player_agent_singleton()
    print("\nPhase 3 tests: all passed.")
