"""投票expel（キック）可決時、人間プレイヤーを完全に追放できることのテスト。

以前は session["initiative"] から外すだけで、players辞書・ws_connections・
token_to_participantの削除やJWT無効化（revoke_token）を行っておらず、
対象が人間プレイヤーの場合、発言順からは外れるが接続・トークンは有効なまま
残り続けていた（TODO.md「投票expelが人間プレイヤーを完全に追放できていない」）。

2026-08-22: expelの実際の後始末（initiative除去・接続切断）はvote_commit直後ではなく、
キーパーが「このまま人数減で続行」/「AIに引き継ぐ」を選ぶvote_expel_resolve呼び出しまで
遅延するようになった（対象者が自分の画面で投票結果を見届けてから切断されるように、かつ
AI引き継ぎの場合はinitiativeを変更しない選択肢を成立させるための再設計）。
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, Mock, patch


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
        "human_votes": {},
    }


@pytest.mark.asyncio
async def test_expel_vote_removes_human_player_completely():
    """expel可決 → キーパーが「続行」を選ぶと、対象が人間プレイヤーならplayers/
    ws_connections/token_to_participant/joined_participantsから除去され、JWTが失効し、
    WS接続がcloseされること。"""
    from def_kari.api.routes.session import (
        vote_commit, VoteCommitRequest, vote_expel_resolve, VoteExpelResolveRequest,
        _sessions, _revoked_jtis, issue_player_jwt, verify_jwt,
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
        commit_result = await vote_commit(sid, req, _fake_request(), _auth={})

        sess = _sessions[sid]
        assert commit_result["expel_pending_followup"] == {"target_id": "char_b", "target_name": "Bob"}
        assert sess["_pending_expel_followup"] == {"target_id": "char_b"}
        # コミット直後はまだ何も切断されていない（対象者が結果を見届けられるように）
        assert "char_b" in sess["initiative"]
        assert token_b in sess["players"]
        assert token_b in sess["ws_connections"]
        fake_ws.close.assert_not_awaited()

        resolve_req = VoteExpelResolveRequest(choice="continue")
        await vote_expel_resolve(sid, resolve_req, _auth={"role": "host"})

        assert "_pending_expel_followup" not in sess
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
    from def_kari.api.routes.session import (
        vote_commit, VoteCommitRequest, vote_expel_resolve, VoteExpelResolveRequest, _sessions,
    )
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
        await vote_expel_resolve(sid, VoteExpelResolveRequest(choice="continue"), _auth={"role": "host"})

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
    from def_kari.api.routes.session import (
        vote_commit, VoteCommitRequest, vote_expel_resolve, VoteExpelResolveRequest, _sessions,
    )
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
        result = await vote_expel_resolve(sid, VoteExpelResolveRequest(choice="continue"), _auth={"role": "host"})

        sess = _sessions[sid]
        assert result["keeper_handed_off"] is True
        assert "char_keeper_ai" not in sess["initiative"]
        assert sess["keeper_char_id"] == ""
        assert sess["keeper_char_name"] == ""
        assert "AIキーパー" in sess["history"][-1]["content"]
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_expel_vote_of_non_keeper_char_leaves_keeper_untouched():
    """expel対象がkeeper_char_idと一致しない場合、キーパー設定は一切変更されないこと。"""
    from def_kari.api.routes.session import (
        vote_commit, VoteCommitRequest, vote_expel_resolve, VoteExpelResolveRequest, _sessions,
    )
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
        result = await vote_expel_resolve(sid, VoteExpelResolveRequest(choice="continue"), _auth={"role": "host"})

        sess = _sessions[sid]
        assert result["keeper_handed_off"] is False
        assert "char_a" not in sess["initiative"]
        assert sess["keeper_char_id"] == "char_keeper_ai"
        assert sess["keeper_char_name"] == "KeeperAI"
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_expel_vote_rejected_keeps_player():
    """expelが否決された場合、initiative・players等は一切変更されず、follow-up待ちにもならないこと。"""
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
        result = await vote_commit(sid, req, _fake_request(), _auth={})

        sess = _sessions[sid]
        assert result["expel_pending_followup"] is None
        assert "_pending_expel_followup" not in sess
        assert "char_b" in sess["initiative"]
        assert token_b in sess["players"]
        assert token_b in sess["ws_connections"]
        fake_ws.close.assert_not_awaited()
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_expel_vote_ai_handover_keeps_character_in_initiative_but_disconnects_player():
    """キーパーが「AIに引き継ぐ」を選んだ場合、initiativeは変更されずhuman_char_idsから
    外れる（=以後AI操作になる）だけである一方、対象人間プレイヤー自身の接続は
    「続行」の場合と同じく完全に除去されること。"""
    from def_kari.api.routes.session import (
        vote_commit, VoteCommitRequest, vote_expel_resolve, VoteExpelResolveRequest,
        _sessions, _revoked_jtis, issue_player_jwt, verify_jwt,
    )
    sid = "_expel_test_ai_handover"
    token_b = issue_player_jwt(sid, "player", "char_b")
    jti_b = verify_jwt(token_b)["jti"]
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
        req = VoteCommitRequest(keeper_vote=True)
        await vote_commit(sid, req, _fake_request(), _auth={})
        result = await vote_expel_resolve(sid, VoteExpelResolveRequest(choice="ai_handover"), _auth={"role": "host"})

        sess = _sessions[sid]
        assert "_pending_expel_followup" not in sess
        # initiativeは変わらない（AI引き継ぎ = 発言順に残ったままAI操作になる）
        assert "char_b" in sess["initiative"]
        assert "char_b" not in sess["human_char_ids"]
        assert result["human_char_ids"] == sess["human_char_ids"]
        # 人間プレイヤー自身の接続は「続行」の場合と同じく完全に除去される
        assert token_b not in sess["players"]
        assert token_b not in sess["ws_connections"]
        assert token_b not in sess["token_to_participant"]
        assert jti_b in _revoked_jtis
        fake_ws.close.assert_awaited_once_with(code=1000)
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_expel_vote_ai_handover_resumes_stuck_turn_when_target_is_current_speaker():
    """AI引き継ぎ対象がちょうど現在のターン担当キャラ(WAITING_FOR_HUMAN中)だった場合、
    human_char_idsから外すだけでは_run_ai_turnsが誰にも再起動されずセッションが
    止まったままになる不具合の修正確認(2026-08-22、実機のexpelでAI引き継ぎ直後に
    セッションが進まなくなる現象として発覚)。対象が現在のターンでなければ
    (直前のtest_expel_vote_ai_handover_keeps_character_in_initiative_but_disconnects_playerの
    ケース、target=char_b・turn=0でchar_aが現在の話者)この再起動は発生しないことも
    間接的に確認済み。"""
    from def_kari.api.routes.session import (
        vote_commit, VoteCommitRequest, vote_expel_resolve, VoteExpelResolveRequest, _sessions,
    )
    sid = "_expel_test_ai_handover_resume"
    fake_ws = AsyncMock()

    _sessions[sid] = {
        "initiative": ["char_b", "char_a"],  # turn=0 → char_bが現在の話者(=expel対象と一致)
        "name_map": {"char_a": "Alice", "char_b": "Bob"},
        "char_backends": {},
        "backend": "tgw",
        "human_char_ids": ["char_a", "char_b"],
        "players": {"token_b": "char_b"},
        "token_to_participant": {"token_b": "pid_b"},
        "joined_participants": [{"participant_id": "pid_b", "character_id": "char_b"}],
        "ws_connections": {"token_b": fake_ws},
        "counters": {},
        "history": [],
        "turn": 0,
        "round": 1,
        "action_count": 0,
        "_pending_vote": _make_pending_vote("char_b"),
    }
    try:
        req = VoteCommitRequest(keeper_vote=True)
        await vote_commit(sid, req, _fake_request(), _auth={})
        with patch("def_kari.api.routes.session_turn_engine._run_ai_turns") as mock_run_ai_turns:
            await vote_expel_resolve(sid, VoteExpelResolveRequest(choice="ai_handover"), _auth={"role": "host"})
            await asyncio.sleep(0.05)  # loop.create_task経由でスケジュールされた再開タスクの実行を待つ
            mock_run_ai_turns.assert_called_once_with(sid)

        sess = _sessions[sid]
        assert sess.get("ai_paused") is False
        assert sess.get("ai_task") is not None
    finally:
        _sessions.pop(sid, None)
