"""def_kari/prompts.py (load_session_prompts/sp) のテスト。

2026-08-21、api/routes/session_lobby.pyから中立な置き場所へ移設
(gm/パッケージからも使うため、gm_agent.py§2-4対応)。既存の_load_session_prompts/
_spエイリアスがsession_lobby.py側で正しく同じ実体を指すことは
session_lobby.pyの通常のテストで既にカバーされる(session_voting.py経由)ため、
ここではprompts.py単体の挙動のみを検証する。
"""

from def_kari import prompts


def test_sp_returns_language_specific_text():
    assert prompts.sp("keeper_system", "en") == "You are the Keeper (GM/facilitator) of this session."


def test_sp_falls_back_to_japanese_for_unknown_lang():
    assert prompts.sp("keeper_system", "fr") == prompts.sp("keeper_system", "ja")


def test_sp_returns_empty_string_for_unknown_key():
    assert prompts.sp("this_key_does_not_exist", "ja") == ""


def test_load_session_prompts_returns_dict_with_expected_keys():
    data = prompts.load_session_prompts()
    assert isinstance(data, dict)
    assert "keeper_system" in data
    assert "gm_keeper_duties" in data


def test_load_session_prompts_is_cached():
    first = prompts.load_session_prompts()
    second = prompts.load_session_prompts()
    assert first is second
