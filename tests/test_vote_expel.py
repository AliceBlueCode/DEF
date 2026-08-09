"""投票expel（キック）可決時、人間プレイヤーを完全に追放できることのテスト。

以前は session["initiative"] から外すだけで、players辞書・ws_connections・
token_to_participantの削除やJWT無効化（revoke_token）を行っておらず、
対象が人間プレイヤーの場合、発言順からは外れるが接続・トークンは有効なまま
残り続けていた（TODO.md「投票expelが人間プレイヤーを完全に追放できていない」）。
"""

import pytest
from unittest.mock import AsyncMock, Mock


def _fake_request():
    """vote_commit（8.9でIPベースのレート制限用にrequest引数が必須になった）に
    渡す最小限のダミーRequest。DEF_BEHIND_CLOUDFLARE_TUNNELは未設定のテスト環境では
    request.client.hostのみが実際に参照される。"""
    req = Mock()
    req.client.host = "127.0.0.1"
    req.headers = {}
    return req


def _make_pending_vote(target_id: str, saved_turn: int = 0, saved_round: int = 1) -> dict:
    return {
        "vote_type": "expel",
        "detail": "",
        "target_id": target_id,
        "proposer_id": "_keeper",
        "vote_label": "退場投票",
        "detail_text": "",
        "saved_turn": saved_turn,
        "saved_round": saved_round,
        "saved_action_count": 0,
        "deliberation_texts": {},
    }


@pytest.mark.asyncio
async def test_expel_vote_removes_human_player_completely():
    """expel可決時、対象が人間プレイヤーならplayers/ws_connections/token_to_participant/
    joined_participantsから除去され、JWTが失効し、WS接続がcloseされること。"""
    from def_kari.api.routes.session import (
        vote_commit, VoteCommitRequest, _sessions, _revoked_jtis,
        issue_player_jwt, verify_jwt,
    )
    sid = "_expel_test_human"
    token_b = issue_player_jwt(sid, "player", "char_b")
    jti_b = verify_jwt(token_b)["jti"]
    fake_ws = AsyncMock()

    _sessions[sid] = {
        "initiative": ["char_a", "char_b"],
        "name_map": {"char_a": "Alice", "char_b": "Bob"},
        "char_backends": {},
        "backend": "tgw",
        "human_char_ids": ["char_a", "char_b"],  # 両方人間扱い → LLM審判をスキップ
        "players": {"token_a": "char_a", token_b: "char_b"},
        "token_to_participant": {"token_a": "pid_a", token_b: "pid_b"},
        "joined_participants": [
            {"participant_id": "pid_a", "character_id": "char_a"},
            {"participant_id": "pid_b", "character_id": "char_b"},
        ],
        "ws_connections": {token_b: fake_ws},
        "counters": {},
        "history": [],
        "turn": 0,
        "round": 1,
        "action_count": 0,
        "_pending_vote": _make_pending_vote("char_b"),
    }
    try:
        req = VoteCommitRequest(keeper_vote=True)  # 可決させる
        await vote_commit(sid, req, _fake_request(), _auth={})

        sess = _sessions[sid]
        assert "char_b" not in sess["initiative"]
        assert token_b not in sess["players"]
        assert token_b not in sess["ws_connections"]
        assert token_b not in sess["token_to_participant"]
        assert all(p["participant_id"] != "pid_b" for p in sess["joined_participants"])
        assert jti_b in _revoked_jtis
        fake_ws.close.assert_awaited_once_with(code=1000)
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_expel_vote_of_ai_character_does_not_touch_players():
    """対象がAIキャラ（playersに存在しない）の場合、players等の除去処理は素通りすること。"""
    from def_kari.api.routes.session import vote_commit, VoteCommitRequest, _sessions
    sid = "_expel_test_ai"
    _sessions[sid] = {
        "initiative": ["char_ai", "char_a"],
        "name_map": {"char_ai": "AI", "char_a": "Alice"},
        "char_backends": {},
        "backend": "tgw",
        "human_char_ids": ["char_a"],
        "guest_chars": {},
        "players": {"token_a": "char_a"},
        "token_to_participant": {"token_a": "pid_a"},
        "joined_participants": [{"participant_id": "pid_a", "character_id": "char_a"}],
        "ws_connections": {},
        "counters": {},
        "history": [],
        "turn": 0,
        "round": 1,
        "action_count": 0,
        "_pending_vote": _make_pending_vote("char_ai"),
    }
    try:
        req = VoteCommitRequest(keeper_vote=True)
        await vote_commit(sid, req, _fake_request(), _auth={})

        sess = _sessions[sid]
        assert "char_ai" not in sess["initiative"]
        assert sess["players"] == {"token_a": "char_a"}  # 変化なし
        assert sess["joined_participants"] == [{"participant_id": "pid_a", "character_id": "char_a"}]
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_expel_vote_of_keeper_char_hands_off_to_ai_keeper():
    """自治規約: キーパーが退場した場合はAIキーパー（無名）へ交代してセッションを継続する。
    expelの対象がkeeper_char_idと一致する場合、keeper_char_id/keeper_char_nameが
    空文字列にリセットされ（ai_keeper_narrate側で無名キーパーへ自動フォールバック）、
    履歴に交代の告知が追加されること。"""
    from def_kari.api.routes.session import vote_commit, VoteCommitRequest, _sessions
    sid = "_expel_test_keeper_handoff"
    _sessions[sid] = {
        "initiative": ["char_keeper_ai", "char_a"],
        "name_map": {"char_keeper_ai": "KeeperAI", "char_a": "Alice"},
        "char_backends": {},
        "backend": "tgw",
        "human_char_ids": ["char_a"],
        "guest_chars": {},
        "players": {"token_a": "char_a"},
        "token_to_participant": {"token_a": "pid_a"},
        "joined_participants": [{"participant_id": "pid_a", "character_id": "char_a"}],
        "ws_connections": {},
        "counters": {},
        "history": [],
        "turn": 0,
        "round": 1,
        "action_count": 0,
        "keeper_char_id": "char_keeper_ai",
        "keeper_char_name": "KeeperAI",
        "_pending_vote": _make_pending_vote("char_keeper_ai"),
    }
    try:
        req = VoteCommitRequest(keeper_vote=True)
        await vote_commit(sid, req, _fake_request(), _auth={})

        sess = _sessions[sid]
        assert "char_keeper_ai" not in sess["initiative"]
        assert sess["keeper_char_id"] == ""
        assert sess["keeper_char_name"] == ""
        assert "AIキーパー" in sess["history"][-1]["content"]
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_expel_vote_of_non_keeper_char_leaves_keeper_untouched():
    """expel対象がkeeper_char_idと一致しない場合、キーパー設定は一切変更されないこと。"""
    from def_kari.api.routes.session import vote_commit, VoteCommitRequest, _sessions
    sid = "_expel_test_keeper_untouched"
    _sessions[sid] = {
        "initiative": ["char_keeper_ai", "char_a"],
        "name_map": {"char_keeper_ai": "KeeperAI", "char_a": "Alice"},
        "char_backends": {},
        "backend": "tgw",
        "human_char_ids": ["char_a"],
        "guest_chars": {},
        "players": {"token_a": "char_a"},
        "token_to_participant": {"token_a": "pid_a"},
        "joined_participants": [{"participant_id": "pid_a", "character_id": "char_a"}],
        "ws_connections": {},
        "counters": {},
        "history": [],
        "turn": 0,
        "round": 1,
        "action_count": 0,
        "keeper_char_id": "char_keeper_ai",
        "keeper_char_name": "KeeperAI",
        "_pending_vote": _make_pending_vote("char_a"),
    }
    try:
        req = VoteCommitRequest(keeper_vote=True)
        await vote_commit(sid, req, _fake_request(), _auth={})

        sess = _sessions[sid]
        assert "char_a" not in sess["initiative"]
        assert sess["keeper_char_id"] == "char_keeper_ai"
        assert sess["keeper_char_name"] == "KeeperAI"
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_expel_vote_rejected_keeps_player():
    """expelが否決された場合、initiative・players等は一切変更されないこと。"""
    from def_kari.api.routes.session import (
        vote_commit, VoteCommitRequest, _sessions, issue_player_jwt,
    )
    sid = "_expel_test_rejected"
    token_b = issue_player_jwt(sid, "player", "char_b")
    fake_ws = AsyncMock()

    _sessions[sid] = {
        "initiative": ["char_a", "char_b"],
        "name_map": {"char_a": "Alice", "char_b": "Bob"},
        "char_backends": {},
        "backend": "tgw",
        "human_char_ids": ["char_a", "char_b"],
        "players": {"token_a": "char_a", token_b: "char_b"},
        "token_to_participant": {"token_a": "pid_a", token_b: "pid_b"},
        "joined_participants": [
            {"participant_id": "pid_a", "character_id": "char_a"},
            {"participant_id": "pid_b", "character_id": "char_b"},
        ],
        "ws_connections": {token_b: fake_ws},
        "counters": {},
        "history": [],
        "turn": 0,
        "round": 1,
        "action_count": 0,
        "_pending_vote": _make_pending_vote("char_b"),
    }
    try:
        req = VoteCommitRequest(keeper_vote=False)  # 否決させる（人間票はkeeper_voteが直接使われる）
        await vote_commit(sid, req, _fake_request(), _auth={})

        sess = _sessions[sid]
        assert "char_b" in sess["initiative"]
        assert token_b in sess["players"]
        assert token_b in sess["ws_connections"]
        fake_ws.close.assert_not_awaited()
    finally:
        _sessions.pop(sid, None)
