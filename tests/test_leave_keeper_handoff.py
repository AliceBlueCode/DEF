"""自治規約62行目「キーパーが退場した場合はAIキーパーへ交代してセッションを継続する」の
明示的退室（POST /leave）経路でのテスト。

従来この処理はvote_commitのexpel可決パス（test_vote_expel.py参照）にしか実装されておらず、
leave_session（自分から「退室」ボタンを押す明示的退室）ではkeeper_char_id/keeper_char_name
がリセットされないまま残っていた。自治規約は退場理由（追放か自主退室か）を区別していない
ため、これは実装漏れ。leave_session側にもexpelと同じ交代処理を追加した。
"""

import pytest


@pytest.mark.asyncio
async def test_leave_of_keeper_char_hands_off_to_ai_keeper():
    """退室したキャラがkeeper_char_idと一致する場合、keeper_char_id/keeper_char_nameが
    空文字列にリセットされ（ai_keeper_narrate側で無名キーパーへ自動フォールバック）、
    履歴に交代の告知が追加されること。"""
    from def_kari.api.routes.session import leave_session, _sessions, issue_player_jwt

    sid = "_leave_test_keeper_handoff"
    token = issue_player_jwt(sid, "gm", "char_keeper_human")
    _sessions[sid] = {
        "initiative": ["char_keeper_human", "char_a"],
        "name_map": {"char_keeper_human": "KeeperHuman", "char_a": "Alice"},
        "human_char_ids": ["char_keeper_human", "char_a"],
        "players": {token: "char_keeper_human"},
        "token_to_participant": {token: "pid_keeper"},
        "joined_participants": [
            {"participant_id": "pid_keeper", "character_id": "char_keeper_human"},
        ],
        "ws_connections": {},
        "counters": {},
        "history": [],
        "keeper_char_id": "char_keeper_human",
        "keeper_char_name": "KeeperHuman",
        "human_keeper": True,
    }
    try:
        resp = await leave_session(sid, f"Bearer {token}")
        assert resp == {"status": "ok"}

        sess = _sessions[sid]
        assert sess["keeper_char_id"] == ""
        assert sess["keeper_char_name"] == ""
        assert "AIキーパー" in sess["history"][-1]["content"]
        assert sess["history"][-1]["character_id"] == "_keeper"
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_leave_of_non_keeper_char_leaves_keeper_untouched():
    """退室したキャラがkeeper_char_idと一致しない場合、キーパー設定・履歴は変更されないこと。"""
    from def_kari.api.routes.session import leave_session, _sessions, issue_player_jwt

    sid = "_leave_test_keeper_untouched"
    token = issue_player_jwt(sid, "player", "char_a")
    _sessions[sid] = {
        "initiative": ["char_keeper_ai", "char_a"],
        "name_map": {"char_keeper_ai": "KeeperAI", "char_a": "Alice"},
        "human_char_ids": ["char_a"],
        "players": {token: "char_a"},
        "token_to_participant": {token: "pid_a"},
        "joined_participants": [
            {"participant_id": "pid_a", "character_id": "char_a"},
        ],
        "ws_connections": {},
        "counters": {},
        "history": [],
        "keeper_char_id": "char_keeper_ai",
        "keeper_char_name": "KeeperAI",
    }
    try:
        resp = await leave_session(sid, f"Bearer {token}")
        assert resp == {"status": "ok"}

        sess = _sessions[sid]
        assert sess["keeper_char_id"] == "char_keeper_ai"
        assert sess["keeper_char_name"] == "KeeperAI"
        assert sess["history"] == []
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_leave_without_keeper_char_id_set_is_a_no_op_for_keeper_fields():
    """keeper_char_idが未設定（AIキーパーで開始したセッション等）の場合、
    退室処理がkeeper関連フィールドに一切触れず正常終了すること。"""
    from def_kari.api.routes.session import leave_session, _sessions, issue_player_jwt

    sid = "_leave_test_no_keeper_set"
    token = issue_player_jwt(sid, "player", "char_a")
    _sessions[sid] = {
        "initiative": ["char_a"],
        "name_map": {"char_a": "Alice"},
        "human_char_ids": ["char_a"],
        "players": {token: "char_a"},
        "token_to_participant": {token: "pid_a"},
        "joined_participants": [
            {"participant_id": "pid_a", "character_id": "char_a"},
        ],
        "ws_connections": {},
        "counters": {},
        "history": [],
        "keeper_char_id": "",
        "keeper_char_name": "",
    }
    try:
        resp = await leave_session(sid, f"Bearer {token}")
        assert resp == {"status": "ok"}

        sess = _sessions[sid]
        assert sess["keeper_char_id"] == ""
        assert sess["history"] == []
    finally:
        _sessions.pop(sid, None)
