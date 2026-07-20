"""Phase 4 検証: Memory分離 + Player Agent（LLM強化）が正しく動作することを確認する。

使用方法:
  cd e:\tools\DEF
  python -m def_kari.test_trpg_phase4
"""

import json
import tempfile
from pathlib import Path


# ── memory.py ────────────────────────────────────────────────────

def test_load_episodic_missing_dir_returns_empty():
    from def_kari.gm.memory import load_episodic
    result = load_episodic("__nonexistent_char__")
    assert result == [], f"Expected [], got {result}"
    print("PASS: load_episodic returns [] when char dir does not exist")


def test_save_and_load_episodic(tmp_path):
    """save_episodic → load_episodic のラウンドトリップを確認する。"""
    from def_kari.gm import memory as mem_module

    char_id = "char_test_memory_001"
    # _CHAR_DIRS を一時ディレクトリに向け替える
    original_dirs = mem_module._CHAR_DIRS[:]
    fake_base = tmp_path / "data" / "public" / "characters"
    fake_base.mkdir(parents=True)
    (fake_base / char_id).mkdir()
    mem_module._CHAR_DIRS = [fake_base]

    try:
        entry1 = {"session_id": "s1", "date": "2026-07-01T10:00:00", "topic": "テスト1", "key_moments": ["発言A"], "emotion_at_end": "calm", "round_count": 2, "participants": []}
        entry2 = {"session_id": "s2", "date": "2026-07-10T10:00:00", "topic": "テスト2", "key_moments": ["発言B", "発言C"], "emotion_at_end": "excited", "round_count": 3, "participants": []}

        mem_module.save_episodic(char_id, entry1)
        mem_module.save_episodic(char_id, entry2)

        results = mem_module.load_episodic(char_id, limit=5)
        assert len(results) == 2, f"Expected 2, got {len(results)}"
        assert results[0]["topic"] == "テスト1", "古い方が先に来るべき"
        assert results[1]["topic"] == "テスト2"
    finally:
        mem_module._CHAR_DIRS = original_dirs

    print("PASS: save_episodic and load_episodic roundtrip")


def test_load_episodic_limit(tmp_path):
    """load_episodic の limit パラメータが機能することを確認する。"""
    from def_kari.gm import memory as mem_module

    char_id = "char_test_limit_001"
    original_dirs = mem_module._CHAR_DIRS[:]
    fake_base = tmp_path / "data" / "public" / "characters"
    fake_base.mkdir(parents=True)
    (fake_base / char_id).mkdir()
    mem_module._CHAR_DIRS = [fake_base]

    try:
        for i in range(5):
            mem_module.save_episodic(char_id, {"session_id": f"s{i}", "topic": f"topic{i}", "date": f"2026-07-0{i+1}T00:00:00", "key_moments": [], "emotion_at_end": "neutral", "round_count": 1, "participants": []})

        results = mem_module.load_episodic(char_id, limit=3)
        assert len(results) == 3, f"Expected 3, got {len(results)}"
        # limit=3 なら直近3件（topic2, 3, 4）が古い順で返る
        assert results[-1]["topic"] == "topic4"
    finally:
        mem_module._CHAR_DIRS = original_dirs

    print("PASS: load_episodic respects limit parameter")


# ── PlayerAgent._build_memory_context ────────────────────────────

def test_build_memory_context_ja():
    from def_kari.gm.player_agent import PlayerAgent

    agent = PlayerAgent()
    episodes = [
        {"date": "2026-07-01T10:00:00", "topic": "AIの倫理", "key_moments": ["熊澤と対立した", "共通点を見つけた"], "emotion_at_end": "calm"},
        {"date": "2026-07-10T12:00:00", "topic": "創造性とは何か", "key_moments": ["赤城の発言に共感した"], "emotion_at_end": "inspired"},
    ]
    ctx = agent._build_memory_context(episodes, "ja")
    assert "【過去のセッションの記憶】" in ctx
    assert "2026-07-01" in ctx
    assert "AIの倫理" in ctx
    assert "2026-07-10" in ctx
    assert "創造性とは何か" in ctx
    print("PASS: _build_memory_context_ja formats correctly")


def test_build_memory_context_empty():
    from def_kari.gm.player_agent import PlayerAgent

    agent = PlayerAgent()
    assert agent._build_memory_context([], "ja") == ""
    print("PASS: _build_memory_context returns empty string for no episodes")


# ── PlayerAgent._plan_action (mocked LLM) ────────────────────────

def test_plan_action_skips_when_no_goals():
    from def_kari.gm.player_agent import PlayerAgent

    agent = PlayerAgent()
    result = agent._plan_action(
        character={"name": "テスト"},
        situation="何かが起きている",
        goals={},
        user_lang="ja",
        backend_id="__invalid__",
        model="",
    )
    assert result == "", f"Expected empty string, got {result!r}"
    print("PASS: _plan_action skips when goals empty")


def test_plan_action_returns_string_from_llm():
    """LLM をモックして _plan_action が文字列を返すことを確認する。"""
    import def_kari.gm.player_agent as pa_module
    import def_kari.llm.backend as backend_module

    original_backends = backend_module.LLM_BACKENDS.copy()
    backend_module.LLM_BACKENDS["mock"] = {
        "chat": lambda messages, system, **kwargs: "真実を問いただす",
        "default_model": "",
    }
    # player_agent はモジュールレベルで LLM_BACKENDS を参照
    pa_module.LLM_BACKENDS = backend_module.LLM_BACKENDS

    try:
        agent = pa_module.PlayerAgent()
        result = agent._plan_action(
            character={"name": "韓非"},
            situation="執事が嘘をついているように見える",
            goals={"long_term": "真実を暴く", "mid_term": "", "immediate": ""},
            user_lang="ja",
            backend_id="mock",
            model="",
        )
        assert result == "真実を問いただす", f"Expected plan string, got {result!r}"
    finally:
        backend_module.LLM_BACKENDS = original_backends
        pa_module.LLM_BACKENDS = original_backends

    print("PASS: _plan_action returns LLM output as string")


# ── narrate(): memory injection ───────────────────────────────────

def test_narrate_injects_memory_context(tmp_path):
    """narrate() が episodic memory を session_context に注入することを確認する。"""
    import def_kari.gm.player_agent as pa_module
    import def_kari.gm.memory as mem_module

    # episodic memory ディレクトリを偽装
    char_id = "char_test_inject_001"
    original_dirs = mem_module._CHAR_DIRS[:]
    fake_base = tmp_path / "data" / "public" / "characters"
    (fake_base / char_id).mkdir(parents=True)
    mem_module._CHAR_DIRS = [fake_base]
    mem_module.save_episodic(char_id, {
        "session_id": "prev",
        "date": "2026-07-01T10:00:00",
        "topic": "過去のお題",
        "key_moments": ["印象的な発言"],
        "emotion_at_end": "calm",
        "round_count": 2,
        "participants": [],
    })

    captured = {}

    def mock_generate(user_text, history=None, model="", character=None,
                      backend=None, session_context="", **kwargs):
        captured["session_context"] = session_context
        return {"success": True, "result": {"dialogue": "test", "emotion": "neutral", "tags": [], "image_prompt_en": ""}, "attempts": []}

    original_gen = pa_module.generate_structured_reply
    pa_module.generate_structured_reply = mock_generate
    try:
        agent = pa_module.PlayerAgent()
        agent.narrate(
            character={"name": "テスト", "goals": {}, "id": char_id},
            user_text="発言",
            history=[],
            session_context="ベースコンテキスト",
            char_id=char_id,
        )
        ctx = captured["session_context"]
        assert "過去のお題" in ctx, f"episodic memory が注入されていない:\n{ctx}"
        assert "【過去のセッションの記憶】" in ctx
    finally:
        pa_module.generate_structured_reply = original_gen
        mem_module._CHAR_DIRS = original_dirs

    print("PASS: narrate() injects episodic memory into session_context")


# ── characters.py id フィールド ───────────────────────────────────

def test_get_character_exposes_id():
    from def_kari.characters import get_character

    char = get_character("character_claude_001")
    assert "id" in char, "id フィールドが存在しない"
    assert char["id"] == "character_claude_001", f"id が一致しない: {char['id']}"
    print("PASS: get_character exposes id field")


# ── _save_session_episodic ────────────────────────────────────────

def test_save_session_episodic_writes_for_each_char(tmp_path):
    """_save_session_episodic が参加者全員分の episodic を書き込むことを確認する。"""
    import def_kari.api.routes.session as session_module
    import def_kari.gm.memory as mem_module

    char_a = "char_test_end_a"
    char_b = "char_test_end_b"

    original_dirs = mem_module._CHAR_DIRS[:]
    fake_base = tmp_path / "data" / "public" / "characters"
    (fake_base / char_a).mkdir(parents=True)
    (fake_base / char_b).mkdir(parents=True)
    mem_module._CHAR_DIRS = [fake_base]

    dummy_session = {
        "topic": "終了テスト",
        "initiative": [char_a, char_b],
        "name_map": {char_a: "Aさん", char_b: "Bさん"},
        "history": [
            {"role": "assistant", "character_id": char_a, "content": "Aさん: 発言1", "emotion": "curious"},
            {"role": "assistant", "character_id": char_b, "content": "Bさん: 発言2", "emotion": "neutral"},
        ],
        "round": 2,
    }

    try:
        session_module._save_session_episodic("test-session-end", dummy_session)

        eps_a = mem_module.load_episodic(char_a)
        eps_b = mem_module.load_episodic(char_b)

        assert len(eps_a) == 1, f"char_a に episodic が書かれていない: {eps_a}"
        assert eps_a[0]["topic"] == "終了テスト"
        assert "Bさん" in eps_a[0]["participants"]

        assert len(eps_b) == 1, f"char_b に episodic が書かれていない: {eps_b}"
        assert "Aさん" in eps_b[0]["participants"]
    finally:
        mem_module._CHAR_DIRS = original_dirs

    print("PASS: _save_session_episodic writes episodic for each participant")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        test_load_episodic_missing_dir_returns_empty()
        test_save_and_load_episodic(tmp_path / "t1")
        test_load_episodic_limit(tmp_path / "t2")
        test_build_memory_context_ja()
        test_build_memory_context_empty()
        test_plan_action_skips_when_no_goals()
        test_plan_action_returns_string_from_llm()
        test_narrate_injects_memory_context(tmp_path / "t3")
        test_get_character_exposes_id()
        test_save_session_episodic_writes_for_each_char(tmp_path / "t4")
    print("\nPhase 4 tests: all passed.")
