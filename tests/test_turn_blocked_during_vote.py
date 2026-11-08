"""投票中（発議〜確定）と追放の決定待ちの間は、ターンを進める操作を止めることのテスト。

以前はサーバー側ではターンが進められ、確定時に turn/round/action_count だけを発議時の値へ
巻き戻していた。その間の発言の履歴・発言力・発言済みの記録・指名は巻き戻らないため、
「手番は戻ったのにその人は発言済み」といった食い違いが起きていた（2026-11-08、
巻き戻す代わりに進めないことにした）。
"""

import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from def_kari.api.routes.session_turn_engine import (
    EXPEL_DECISION_PENDING,
    VOTE_IN_PROGRESS,
    HumanTurnRequest,
    _run_ai_turns,
    _turn_progress_blocked,
    ai_resume,
    human_turn_action,
    retake_turn,
    skip_turn,
)
from def_kari.api.routes.session_state import _sessions


def _session(sid: str, **extra) -> dict:
    sess = {
        "id": sid,
        "initiative": ["char_a", "char_b"],
        "human_char_ids": ["char_a"],
        "guest_chars": {},
        "players": {"tok_a": "char_a"},
        "ws_connections": {},
        "name_map": {"char_a": "Alice", "char_b": "Bob"},
        "counters": {},
        "history": [],
        "turn": 0,
        "round": 1,
        "action_count": 0,
        "actions_per_turn": 2,
        "ai_task": None,
        "ai_paused": False,
        "trpg_mode": False,
    }
    sess.update(extra)
    _sessions[sid] = sess
    return sess


@pytest.fixture
def sid():
    name = "_turn_blocked_test"
    yield name
    _sessions.pop(name, None)


def test_blocked_reason():
    assert _turn_progress_blocked({}) is None
    assert _turn_progress_blocked({"_pending_vote": {"vote_type": "topic_change"}}) == VOTE_IN_PROGRESS
    assert _turn_progress_blocked({"_pending_expel_followup": {"target_id": "x"}}) == EXPEL_DECISION_PENDING


@pytest.mark.asyncio
@pytest.mark.parametrize("pending_key,reason", [
    ("_pending_vote", VOTE_IN_PROGRESS),
    ("_pending_expel_followup", EXPEL_DECISION_PENDING),
])
async def test_keeper_endpoints_refuse_while_blocked(sid, pending_key, reason):
    sess = _session(sid, **{pending_key: {"target_id": "char_b"}})
    for call in (
        lambda: skip_turn(sid, _auth={"role": "host"}),
        lambda: retake_turn(sid, _auth={"role": "host"}),
        lambda: ai_resume(sid, _auth={"role": "host"}),
    ):
        with pytest.raises(HTTPException) as exc:
            await call()
        assert exc.value.status_code == 409
        assert exc.value.detail == reason
    assert sess["turn"] == 0
    assert sess["round"] == 1
    assert sess.get("ai_task") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["send", "skip", "extend", "interrupt"])
async def test_human_turn_action_refuses_while_vote_in_progress(sid, action):
    sess = _session(sid, _pending_vote={"vote_type": "topic_change"})
    req = HumanTurnRequest(action=action, text="こんにちは", character_id="char_a")
    with pytest.raises(HTTPException) as exc:
        await human_turn_action(sid, req, _auth={"role": "player", "character_id": "char_a", "jti": "j"})
    assert exc.value.status_code == 409
    assert exc.value.detail == VOTE_IN_PROGRESS
    assert sess["history"] == []
    assert sess["turn"] == 0
    assert sess["counters"] == {}


@pytest.mark.asyncio
async def test_run_ai_turns_does_nothing_while_vote_in_progress(sid):
    _session(sid, human_char_ids=[], _pending_vote={"vote_type": "topic_change"})
    with patch("def_kari.api.routes.session_turn_engine._execute_ai_turn") as mock_exec:
        await _run_ai_turns(sid)
    mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_disconnect_auto_skip_does_nothing_while_vote_in_progress(sid):
    from def_kari.api.routes.session import _schedule_disconnect_skip
    sess = _session(sid, _pending_vote={"vote_type": "topic_change"})
    try:
        with patch("def_kari.api.routes.session_turn_disconnect._disconnect_timeout_sec", return_value=0.05), \
             patch("def_kari.api.routes.session_turn_engine._run_ai_turns"):
            _schedule_disconnect_skip(sid, "char_a")
            await asyncio.sleep(0.15)
        assert sess["turn"] == 0
        assert sess["counters"].get("char_a") is None
    finally:
        task = sess.get("disconnect_skip_tasks", {}).get("char_a")
        if task and not task.done():
            task.cancel()


# ── 2026-11-08 レビュー指摘への対応 ─────────────────────────────────────

@pytest.mark.asyncio
async def test_vote_cancel_lifts_the_block(sid):
    """確定や選択のUIが失われても（タブの再読み込み等）、キーパーが取り消せば進められること。"""
    from def_kari.api.routes.session_voting import vote_cancel
    sess = _session(sid, _pending_vote={"vote_type": "topic_change"})
    result = await vote_cancel(sid, _auth={"role": "host"})
    assert result["status"] == "cancelled"
    assert _turn_progress_blocked(sess) is None
    with patch("def_kari.api.routes.session_turn_engine._run_ai_turns"):
        assert await ai_resume(sid, _auth={"role": "host"}) == {"status": "ok"}


@pytest.mark.asyncio
async def test_vote_cancel_with_nothing_pending(sid):
    from def_kari.api.routes.session_voting import vote_cancel
    _session(sid)
    assert (await vote_cancel(sid, _auth={"role": "host"}))["status"] == "nothing_pending"


def test_autosave_restore_drops_pending_vote(tmp_path):
    """再起動後は確定のUIを出せないので、保留中の投票・追放の決定待ちは復元しない。"""
    import json
    import time
    from def_kari.api.routes.session_persistence import _restore_one_autosave_file
    f = tmp_path / "_restore_test.json"
    f.write_text(json.dumps({
        "id": "_restore_test", "initiative": ["a"], "turn": 0, "round": 1,
        "_pending_vote": {"vote_type": "topic_change"}, "_pending_expel_followup": {"target_id": "a"},
    }), encoding="utf-8")
    try:
        with patch("def_kari.api.routes.session_persistence._AUTOSAVE_DIR", tmp_path):
            _restore_one_autosave_file(f, time.time())
        restored = _sessions["_restore_test"]
        assert "_pending_vote" not in restored
        assert "_pending_expel_followup" not in restored
    finally:
        _sessions.pop("_restore_test", None)


def test_ai_action_selected_during_vote_is_discarded(sid):
    """行動選択（LLM）の最中に投票が発議されたら、その選択（skip）を反映しない。"""
    from def_kari.api.routes.session_turn_engine import _resolve_ai_action, SessionNextRequest
    sess = _session(sid, trpg_mode=True, round=2, human_char_ids=[], counters={"char_b": 2}, turn=1)

    def _select_while_vote_starts(*args, **kwargs):
        sess["_pending_vote"] = {"vote_type": "topic_change"}
        return {"action": "skip"}

    with patch("def_kari.api.routes.session_turn_engine._ai_action_select", side_effect=_select_while_vote_starts):
        early, _, _ = _resolve_ai_action(
            sess, SessionNextRequest(session_id=sid), "char_b", 1, sess["counters"],
            sess["initiative"], sess["name_map"], "Bob", "mock", "", {}, "ja", 0,
        )
    assert early == {"discarded": True}
    assert sess["turn"] == 1
    assert sess["counters"] == {"char_b": 2}


@pytest.mark.asyncio
async def test_run_ai_turns_drops_discarded_result_silently(sid):
    _session(sid, human_char_ids=[])
    emitted = []
    with patch("def_kari.api.routes.session_turn_engine._execute_ai_turn", return_value={"discarded": True}), \
         patch("def_kari.api.routes.session_turn_engine._game_event_bus") as bus:
        bus.emit.side_effect = lambda *a, **kw: emitted.append(a[1])
        await _run_ai_turns(sid)
    assert "AI_TURN_COMPLETED" not in emitted


@pytest.mark.asyncio
async def test_run_ai_turns_does_nothing_while_expel_decision_pending(sid):
    """自動進行のオンやホストのAI引き継ぎなど、入口を通らない起動でも止まること。"""
    _session(sid, human_char_ids=[], _pending_expel_followup={"target_id": "char_a"})
    with patch("def_kari.api.routes.session_turn_engine._execute_ai_turn") as mock_exec:
        await _run_ai_turns(sid)
    mock_exec.assert_not_called()


def test_disconnect_skip_is_rearmed_when_block_is_lifted(sid):
    """投票中に捨てた切断の自動skipを、決着後に現在の手番の人へ仕掛け直す。"""
    from def_kari.api.routes.session_turn_engine import _on_turn_progress_unblocked
    sess = _session(sid)  # 現在の手番は人間のchar_a（ws_connectionsに無い＝切断中）
    with patch("def_kari.api.routes.session_turn_engine._maybe_schedule_disconnect_skip") as mock_sched:
        _on_turn_progress_unblocked(sid, sess)
    mock_sched.assert_called_once_with(sid, sess, "char_a")


def test_disconnect_skip_not_rearmed_while_still_blocked(sid):
    from def_kari.api.routes.session_turn_engine import _on_turn_progress_unblocked
    sess = _session(sid, _pending_expel_followup={"target_id": "char_b"})
    with patch("def_kari.api.routes.session_turn_engine._maybe_schedule_disconnect_skip") as mock_sched:
        _on_turn_progress_unblocked(sid, sess)
    mock_sched.assert_not_called()


def test_second_vote_while_one_is_pending_is_refused(sid):
    from def_kari.api.routes.session_voting import vote_deliberate, VoteRequest
    from unittest.mock import Mock
    _session(sid, _pending_vote={"vote_type": "topic_change"})
    req = Mock()
    req.client.host = "127.0.0.1"
    req.headers = {}
    with patch("def_kari.api.routes.session_voting._check_circuit_breaker", return_value=True), \
         patch("def_kari.api.routes.session_voting._check_generation_rate", return_value=True), \
         patch("def_kari.api.routes.session_voting._check_daily_generation_limit", return_value=True), \
         patch("def_kari.api.routes.session_voting.record_generation_event"):
        with pytest.raises(HTTPException) as exc:
            vote_deliberate(sid, VoteRequest(vote_type="end_session"), req, _auth={"jti": "j"})
    assert exc.value.status_code == 409


# ── 2026-11-08 レビュー指摘（2回目）への対応 ─────────────────────────────

def _fake_http_request():
    from unittest.mock import Mock
    req = Mock()
    req.client.host = "127.0.0.1"
    req.headers = {}
    return req


def _deliberate_patches():
    return (
        patch("def_kari.api.routes.session_voting._check_circuit_breaker", return_value=True),
        patch("def_kari.api.routes.session_voting._check_generation_rate", return_value=True),
        patch("def_kari.api.routes.session_voting._check_daily_generation_limit", return_value=True),
        patch("def_kari.api.routes.session_voting.record_generation_event"),
        patch("def_kari.api.routes.session._start_background_tts", return_value=""),
    )


def test_vote_cancelled_during_deliberation_stops_cleanly(sid):
    """弁明の生成中に取り消されたら、KeyErrorで落ちず、残りの弁明も書かずに打ち切る。"""
    from def_kari.api.routes.session_voting import vote_deliberate, VoteRequest
    sess = _session(sid, human_char_ids=[])
    calls = []

    def _reply_then_cancel(**kwargs):
        calls.append(1)
        sess.pop("_pending_vote", None)  # 1人目の生成中にキーパーが取り消した
        return {"success": True, "result": {"dialogue": "反対です", "emotion": "neutral", "tags": []}}

    p1, p2, p3, p4, p5 = _deliberate_patches()
    with p1, p2, p3, p4, p5, patch("def_kari.api.routes.session_voting.generate_structured_reply", side_effect=_reply_then_cancel):
        result = vote_deliberate(sid, VoteRequest(vote_type="end_session"), _fake_http_request(), _auth={"jti": "j", "role": "host"})
    assert result.get("cancelled") is True
    assert len(calls) == 1  # 2人目の弁明は生成しない
    assert not any(h.get("character_id") in ("char_a", "char_b") for h in sess["history"])
    assert "_pending_vote" not in sess


def test_vote_cancel_of_passed_expulsion_says_target_stays(sid):
    import asyncio as _asyncio
    from def_kari.api.routes.session_voting import vote_cancel
    sess = _session(sid, _pending_expel_followup={"target_id": "char_b"})
    result = _asyncio.run(vote_cancel(sid, _auth={"role": "host"}))
    assert "Bob" in result["result_text"]
    assert sess["initiative"] == ["char_a", "char_b"]


def test_autosave_restore_leaves_a_note_in_history(tmp_path):
    import json
    import time
    from def_kari.api.routes.session_persistence import _restore_one_autosave_file
    f = tmp_path / "_restore_note_test.json"
    f.write_text(json.dumps({
        "id": "_restore_note_test", "initiative": ["a", "b"], "name_map": {"b": "Bob"}, "history": [],
        "_pending_expel_followup": {"target_id": "b"},
    }), encoding="utf-8")
    try:
        with patch("def_kari.api.routes.session_persistence._AUTOSAVE_DIR", tmp_path):
            _restore_one_autosave_file(f, time.time())
            # 何も操作しないまま再起動がもう1回: 復元直後に保存し直しているので、通知は増えない
            _sessions.pop("_restore_note_test", None)
            _restore_one_autosave_file(f, time.time())
        notes = [h["content"] for h in _sessions["_restore_note_test"]["history"]]
        assert len(notes) == 1 and "Bob" in notes[0]
    finally:
        _sessions.pop("_restore_note_test", None)


def test_autosave_restore_with_null_history_still_restores(tmp_path):
    """想定外の形（historyがnull）でも、通知の失敗でセッションごと復元できなくならない。"""
    import json
    import time
    from def_kari.api.routes.session_persistence import _restore_one_autosave_file
    f = tmp_path / "_restore_null_test.json"
    f.write_text(json.dumps({
        "id": "_restore_null_test", "initiative": ["a"], "history": None,
        "_pending_vote": {"vote_type": "topic_change"},
    }), encoding="utf-8")
    try:
        with patch("def_kari.api.routes.session_persistence._AUTOSAVE_DIR", tmp_path):
            _restore_one_autosave_file(f, time.time())
        assert "_restore_null_test" in _sessions
        assert "_pending_vote" not in _sessions["_restore_null_test"]
    finally:
        _sessions.pop("_restore_null_test", None)


def test_new_vote_right_after_cancel_does_not_get_old_deliberations(sid):
    """弁明の生成中に取り消し、その直後に別の発議が入っても、古い弁明が新しい投票に混ざらない
    （投票オブジェクトの参照を比べる対策の本来の目的）。"""
    from def_kari.api.routes.session_voting import vote_deliberate, VoteRequest
    sess = _session(sid, human_char_ids=[])
    newer_vote = {"vote_type": "topic_change", "deliberation_texts": {}, "human_votes": {}}

    def _reply_then_replaced(**kwargs):
        sess["_pending_vote"] = newer_vote  # 取り消しの直後に、別の発議が入った
        return {"success": True, "result": {"dialogue": "古い投票への弁明", "emotion": "neutral", "tags": []}}

    p1, p2, p3, p4, p5 = _deliberate_patches()
    with p1, p2, p3, p4, p5, patch("def_kari.api.routes.session_voting.generate_structured_reply", side_effect=_reply_then_replaced):
        result = vote_deliberate(sid, VoteRequest(vote_type="end_session"), _fake_http_request(), _auth={"jti": "j", "role": "host"})
    assert result.get("cancelled") is True
    assert newer_vote["deliberation_texts"] == {}


def test_failed_generation_is_not_retried_while_vote_in_progress(sid):
    """投票中の生成失敗は再試行しない（どのみち捨てる。LLM呼び出しの無駄）。"""
    from def_kari.api.routes.session_turn_engine import _generate_ai_turn_reply
    sess = _session(sid, human_char_ids=[])
    failed = {"success": False, "result": None, "attempts": []}

    def _fail_while_vote_starts(**kwargs):
        sess["_pending_vote"] = {"vote_type": "topic_change"}
        return failed

    with patch("def_kari.api.routes.session_turn_engine._player_agent.narrate", side_effect=_fail_while_vote_starts) as mock_narrate, \
         patch("time.sleep"):
        _generate_ai_turn_reply(sess, "char_b", {}, "", [], "", "mock", "", ["general"], ["general"],
                                sess["name_map"], "", 1, False)
    assert mock_narrate.call_count == 1


@pytest.mark.asyncio
async def test_commit_lifts_block_and_rearms_disconnect_skip(sid):
    """確定の後、止めていた入口が再び通り、切断中の人の自動skipが仕掛け直される（通し）。"""
    from def_kari.api.routes.session_voting import vote_commit, VoteCommitRequest
    sess = _session(sid, _pending_vote={
        "vote_type": "topic_change", "detail": "", "target_id": "", "proposer_id": "_keeper",
        "vote_label": "お題変更", "detail_text": "", "deliberation_texts": {}, "human_votes": {},
    })
    with patch("def_kari.api.routes.session_turn_engine._maybe_schedule_disconnect_skip") as mock_sched:
        await vote_commit(sid, VoteCommitRequest(keeper_vote=False), _fake_http_request(), _auth={"role": "host"})
    assert _turn_progress_blocked(sess) is None
    mock_sched.assert_called_once_with(sid, sess, "char_a")
    with patch("def_kari.api.routes.session_turn_engine._run_ai_turns"):
        assert await ai_resume(sid, _auth={"role": "host"}) == {"status": "ok"}


# ── 流れた投票の発言力を戻す（2026-11-08、ユーザー決定: 取り消しでも再起動でも戻す） ──

def _propose(sess, sid, proposer="char_b"):
    """AIキャラ proposer の発議を、正規の経路（行動選択で発議を記録→キーパーのタブが受け付ける）で行う。"""
    from def_kari.api.routes.session_voting import vote_deliberate, VoteRequest
    if "_ai_vote_proposal" not in sess:
        spent = sess["counters"].get(proposer, 0)
        sess["counters"][proposer] = 0
        sess["_ai_vote_proposal"] = {"proposer_id": proposer, "spent": spent, "reason": "そろそろ終わりにしよう"}
    p1, p2, p3, p4, p5 = _deliberate_patches()
    with p1, p2, p3, p4, p5, patch(
        "def_kari.api.routes.session_voting.generate_structured_reply",
        return_value={"success": True, "result": {"dialogue": "賛成", "emotion": "neutral", "tags": []}},
    ):
        vote_deliberate(sid, VoteRequest(vote_type="end_session", proposer_id=proposer),
                        _fake_http_request(), _auth={"jti": "j", "role": "host"})


def test_proposing_spends_counter_and_records_it(sid):
    sess = _session(sid, human_char_ids=[], counters={"char_b": 4})
    _propose(sess, sid)
    assert sess["counters"]["char_b"] == 0
    assert sess["_pending_vote"]["proposer_counter_spent"] == 4


@pytest.mark.asyncio
async def test_cancel_refunds_proposer_counter(sid):
    from def_kari.api.routes.session_voting import vote_cancel
    sess = _session(sid, human_char_ids=[], counters={"char_b": 4})
    _propose(sess, sid)
    sess["counters"]["char_b"] += 1  # 投票中にキーパーが調整した分も失わない
    result = await vote_cancel(sid, _auth={"role": "host"})
    assert sess["counters"]["char_b"] == 5
    assert result["counters"]["char_b"] == 5


@pytest.mark.asyncio
async def test_commit_does_not_refund_proposer_counter(sid):
    from def_kari.api.routes.session_voting import vote_commit, VoteCommitRequest
    sess = _session(sid, human_char_ids=[], counters={"char_b": 4})
    _propose(sess, sid)
    await vote_commit(sid, VoteCommitRequest(keeper_vote=False), _fake_http_request(), _auth={"role": "host"})
    assert sess["counters"]["char_b"] == 0


def test_autosave_restore_refunds_proposer_counter(tmp_path):
    import json
    import time
    from def_kari.api.routes.session_persistence import _restore_one_autosave_file
    f = tmp_path / "_restore_refund_test.json"
    f.write_text(json.dumps({
        "id": "_restore_refund_test", "initiative": ["a", "b"], "history": [], "counters": {"b": 0},
        "_pending_vote": {"vote_type": "end_session", "proposer_id": "b", "proposer_counter_spent": 3},
    }), encoding="utf-8")
    try:
        with patch("def_kari.api.routes.session_persistence._AUTOSAVE_DIR", tmp_path):
            _restore_one_autosave_file(f, time.time())
        assert _sessions["_restore_refund_test"]["counters"]["b"] == 3
    finally:
        _sessions.pop("_restore_refund_test", None)


def _ai_propose_vote(sess, sid):
    from def_kari.api.routes.session_turn_engine import _resolve_ai_action, SessionNextRequest
    with patch("def_kari.api.routes.session_turn_engine._ai_action_select",
               return_value={"action": "vote", "vote_type": "topic_change"}):
        early, _, _ = _resolve_ai_action(
            sess, SessionNextRequest(session_id=sid), "char_b", 1, sess["counters"],
            sess["initiative"], sess["name_map"], "Bob", "mock", "", {}, "ja", 0,
        )
    return early


def test_ai_vote_proposal_spends_counter_at_proposal(sid):
    """AIの発議は行動選択の時点で発言力を消費する。vote_deliberate が呼ばれなかった
    （レート制限・タブが落ちた等）場合に、同じAIが次の手番で発議を繰り返さないため
    （2026-11-08レビュー指摘）。応答の counters も消費後の値になる。"""
    sess = _session(sid, trpg_mode=True, round=2, human_char_ids=[], counters={"char_b": 4}, turn=1)
    early = _ai_propose_vote(sess, sid)
    assert early["action"] == "vote_proposal"
    assert sess["counters"]["char_b"] == 0
    assert early["counters"]["char_b"] == 0
    assert sess["_ai_vote_proposal"]["proposer_id"] == "char_b"
    assert sess["_ai_vote_proposal"]["spent"] == 4


@pytest.mark.asyncio
async def test_ai_vote_proposal_spent_is_refunded_when_cancelled(sid):
    """vote_deliberate はAIの発議の記録を引き継ぎ、取り消しでその量を戻す。"""
    from def_kari.api.routes.session_voting import vote_cancel
    sess = _session(sid, trpg_mode=True, round=2, human_char_ids=[], counters={"char_b": 4}, turn=1)
    _ai_propose_vote(sess, sid)
    _propose(sess, sid, proposer="char_b")
    assert "_ai_vote_proposal" not in sess
    assert sess["_pending_vote"]["proposer_counter_spent"] == 4
    await vote_cancel(sid, _auth={"role": "host"})
    assert sess["counters"]["char_b"] == 4


# ── 発議者の確認（発言の偽装を防ぐ、2026-11-08） ──────────────────────────

def _deliberate(sid, req_kwargs, auth):
    from def_kari.api.routes.session_voting import vote_deliberate, VoteRequest
    p1, p2, p3, p4, p5 = _deliberate_patches()
    with p1, p2, p3, p4, p5, patch(
        "def_kari.api.routes.session_voting.generate_structured_reply",
        return_value={"success": True, "result": {"dialogue": "賛成", "emotion": "neutral", "tags": []}},
    ):
        return vote_deliberate(sid, VoteRequest(vote_type="end_session", **req_kwargs), _fake_http_request(), _auth=auth)


_PLAYER_A = {"jti": "j", "role": "player", "char_id": "char_a"}


def test_player_cannot_propose_as_another_human(sid):
    _session(sid, human_char_ids=["char_a", "char_b"], counters={"char_b": 5})
    with pytest.raises(HTTPException) as exc:
        _deliberate(sid, {"proposer_id": "char_b", "proposer_text": "偽の発言"}, _PLAYER_A)
    assert exc.value.status_code == 409
    assert "_pending_vote" not in _sessions[sid]


def test_player_cannot_propose_as_ai(sid):
    sess = _session(sid, counters={"char_b": 5})  # char_b はAI
    with pytest.raises(HTTPException) as exc:
        _deliberate(sid, {"proposer_id": "char_b", "proposer_text": "偽の発言"}, _PLAYER_A)
    assert exc.value.status_code == 403
    assert not any("偽の発言" in h["content"] for h in sess["history"])


def test_keeper_cannot_propose_as_ai_that_did_not_propose(sid):
    _session(sid, counters={"char_b": 5})
    with pytest.raises(HTTPException) as exc:
        _deliberate(sid, {"proposer_id": "char_b", "proposer_text": "偽の発言"}, {"jti": "j", "role": "host"})
    assert exc.value.status_code == 403


def test_ai_proposal_text_comes_from_server_record_not_request(sid):
    sess = _session(sid, counters={"char_b": 0})
    sess["_ai_vote_proposal"] = {"proposer_id": "char_b", "spent": 4, "reason": "そろそろ終わりにしよう"}
    _deliberate(sid, {"proposer_id": "char_b", "proposer_text": "書き換えた発言"}, {"jti": "j", "role": "host"})
    contents = [h["content"] for h in sess["history"]]
    assert any("そろそろ終わりにしよう" in c for c in contents)
    assert not any("書き換えた発言" in c for c in contents)


def test_player_needs_three_speech_power_to_propose(sid):
    _session(sid, counters={"char_a": 2})
    with pytest.raises(HTTPException) as exc:
        _deliberate(sid, {"proposer_id": "char_a"}, _PLAYER_A)
    assert exc.value.status_code == 409


def test_player_cannot_propose_without_proposer(sid):
    _session(sid)
    with pytest.raises(HTTPException) as exc:
        _deliberate(sid, {"proposer_id": ""}, _PLAYER_A)
    assert exc.value.status_code == 403


def test_player_can_propose_as_own_character(sid):
    sess = _session(sid, counters={"char_a": 3})
    _deliberate(sid, {"proposer_id": "char_a", "proposer_text": "提案します"}, _PLAYER_A)
    assert sess["_pending_vote"]["proposer_id"] == "char_a"
    assert sess["counters"]["char_a"] == 0


# ── 受け付けられなかったAIの発議・投票の中身の確認（2026-11-08レビュー指摘） ──────

def test_unaccepted_ai_proposal_is_refunded_when_next_turn_starts(sid):
    """AIの発議が受け付けられないまま次の手番の処理が始まったら、流れたとみなして戻す。"""
    from def_kari.api.routes.session_turn_engine import _resolve_turn_start, SessionNextRequest
    sess = _session(sid, human_char_ids=["char_a"], counters={"char_b": 0}, turn=0)
    sess["_ai_vote_proposal"] = {"proposer_id": "char_b", "spent": 4, "reason": "古い理由"}
    _resolve_turn_start(sess, SessionNextRequest(session_id=sid))
    assert "_ai_vote_proposal" not in sess
    assert sess["counters"]["char_b"] == 4


def test_ai_proposal_is_kept_while_its_vote_is_pending(sid):
    from def_kari.api.routes.session_turn_engine import _resolve_turn_start, SessionNextRequest
    sess = _session(sid, human_char_ids=["char_a"], counters={"char_b": 0}, turn=0,
                    _pending_vote={"vote_type": "end_session"})
    sess["_ai_vote_proposal"] = {"proposer_id": "char_b", "spent": 4, "reason": "r"}
    _resolve_turn_start(sess, SessionNextRequest(session_id=sid))
    assert sess["counters"]["char_b"] == 0


def test_autosave_restore_refunds_unaccepted_ai_proposal(tmp_path):
    import json
    import time
    from def_kari.api.routes.session_persistence import _restore_one_autosave_file
    f = tmp_path / "_restore_ai_prop_test.json"
    f.write_text(json.dumps({
        "id": "_restore_ai_prop_test", "initiative": ["a", "b"], "history": [], "counters": {"b": 0},
        "_ai_vote_proposal": {"proposer_id": "b", "spent": 3, "reason": "r"},
    }), encoding="utf-8")
    try:
        with patch("def_kari.api.routes.session_persistence._AUTOSAVE_DIR", tmp_path):
            _restore_one_autosave_file(f, time.time())
        restored = _sessions["_restore_ai_prop_test"]
        assert restored["counters"]["b"] == 3
        assert "_ai_vote_proposal" not in restored
    finally:
        _sessions.pop("_restore_ai_prop_test", None)


@pytest.mark.parametrize("req_kwargs", [
    {"vote_type": "something_else"},
    {"vote_type": "topic_change", "detail": "あ" * 201},
    {"vote_type": "expel", "target_id": "not_in_session"},
])
def test_vote_content_is_validated(sid, req_kwargs):
    from def_kari.api.routes.session_voting import vote_deliberate, VoteRequest
    sess = _session(sid)
    p1, p2, p3, p4, p5 = _deliberate_patches()
    with p1, p2, p3, p4, p5:
        with pytest.raises(HTTPException) as exc:
            vote_deliberate(sid, VoteRequest(**req_kwargs), _fake_http_request(), _auth={"jti": "j", "role": "host"})
    assert exc.value.status_code == 400
    assert "_pending_vote" not in sess


# ── ダイスの判定の名義（2026-11-08レビュー指摘。投票の発議者と同じ種類の偽装） ──────

def _roll(sid, auth, **kwargs):
    from def_kari.api.routes.session_gameplay import session_dice_roll, SessionDiceRollRequest
    req = SessionDiceRollRequest(notation="1d100", skill_value=50, **kwargs)
    with patch("def_kari.api.routes.session_gameplay._game_event_bus"):
        return session_dice_roll(sid, req, _auth=auth)


def test_player_cannot_roll_as_another_character(sid):
    sess = _session(sid, human_char_ids=["char_a", "char_b"])
    with pytest.raises(HTTPException) as exc:
        _roll(sid, _PLAYER_A, character_id="char_b", stat_name="射撃")
    assert exc.value.status_code == 409
    assert sess["history"] == []


def test_player_can_roll_as_own_character(sid):
    sess = _session(sid)
    _roll(sid, _PLAYER_A, character_id="char_a", stat_name="射撃")
    assert sess["history"] and "Alice" in sess["history"][-1]["content"]


def test_keeper_can_roll_for_any_character(sid):
    sess = _session(sid)
    _roll(sid, {"jti": "j", "role": "host"}, character_id="char_b", stat_name="射撃")
    assert "Bob" in sess["history"][-1]["content"]


def test_stat_name_is_length_limited(sid):
    _session(sid)
    with pytest.raises(HTTPException) as exc:
        _roll(sid, _PLAYER_A, character_id="char_a", stat_name="あ" * 41)
    assert exc.value.status_code == 400


# ── AIの発議の正規化（2026-11-08レビュー指摘: AIの追放の発議は必ず400になっていた） ──────

def _ai_select(sess, sid, action):
    from def_kari.api.routes.session_turn_engine import _resolve_ai_action, SessionNextRequest
    with patch("def_kari.api.routes.session_turn_engine._ai_action_select", return_value=action):
        early, ai_action, _ = _resolve_ai_action(
            sess, SessionNextRequest(session_id=sid), "char_b", 1, sess["counters"],
            sess["initiative"], sess["name_map"], "Bob", "mock", "", {}, "ja", 0,
        )
    return early, ai_action


def test_ai_expel_proposal_resolves_target_by_name_and_is_accepted(sid):
    sess = _session(sid, trpg_mode=True, round=2, human_char_ids=[], counters={"char_b": 3}, turn=1)
    early, _ = _ai_select(sess, sid, {"action": "vote", "vote_type": "expel", "target_name": "Alice",
                                      "vote_detail": "", "reason": "Aliceは進行を妨げている"})
    assert early["action"] == "vote_proposal"
    assert early["target_id"] == "char_a"
    # キーパーのタブは target_id を送らない（申告は使わず、記録の対象を使う）
    _deliberate(sid, {"proposer_id": "char_b", "target_id": ""}, {"jti": "j", "role": "host"})
    assert sess["_pending_vote"]["vote_type"] == "expel"
    assert sess["_pending_vote"]["target_id"] == "char_a"


@pytest.mark.parametrize("action", [
    {"action": "vote", "vote_type": "dissolve_party", "vote_detail": "", "reason": "r"},
    {"action": "vote", "vote_type": "expel", "target_name": "誰でもない", "vote_detail": "", "reason": "r"},
    {"action": "vote", "vote_type": "expel", "target_name": "Bob", "vote_detail": "", "reason": "r"},  # 自分自身
])
def test_unworkable_ai_proposal_becomes_none_without_spending(sid, action):
    sess = _session(sid, trpg_mode=True, round=2, human_char_ids=[], counters={"char_b": 3}, turn=1)
    early, ai_action = _ai_select(sess, sid, dict(action))
    assert early is None or early.get("action") != "vote_proposal"
    assert ai_action["action"] == "none"
    assert sess["counters"]["char_b"] == 3
    assert "_ai_vote_proposal" not in sess


def test_ai_proposal_detail_is_truncated(sid):
    sess = _session(sid, trpg_mode=True, round=2, human_char_ids=[], counters={"char_b": 3}, turn=1)
    early, _ = _ai_select(sess, sid, {"action": "vote", "vote_type": "topic_change",
                                      "vote_detail": "あ" * 500, "reason": "r"})
    assert len(early["vote_detail"]) == 200


def test_ai_proposal_is_refunded_if_validation_fails_at_acceptance(sid):
    """発議の後に追放の対象が抜けていた場合など、受け付けで落ちたら発言力を戻す。"""
    sess = _session(sid, counters={"char_b": 0})
    sess["_ai_vote_proposal"] = {"proposer_id": "char_b", "spent": 4, "reason": "r",
                                 "vote_type": "expel", "detail": "", "target_id": "gone"}
    with pytest.raises(HTTPException):
        _deliberate(sid, {"proposer_id": "char_b"}, {"jti": "j", "role": "host"})
    assert sess["counters"]["char_b"] == 4
    assert "_ai_vote_proposal" not in sess


# ── 投票の決着の通知（VOTE_CLOSED、2026-11-08レビュー指摘: 決着をフロントに推測させない） ──

def _closed_events(emitted):
    return [e[2] for e in emitted if len(e) > 2 and e[1] == "VOTE_CLOSED"]


@pytest.mark.asyncio
async def test_cancel_emits_vote_closed_once(sid):
    from def_kari.api.routes.session_voting import vote_cancel
    _session(sid, _pending_vote={"vote_type": "topic_change"})
    emitted = []
    with patch("def_kari.api.routes.session_turn_engine._game_event_bus") as bus:
        bus.emit.side_effect = lambda *a, **kw: emitted.append(a)
        await vote_cancel(sid, _auth={"role": "host"})
    assert _closed_events(emitted) == [{"resume": True}]


def test_vote_closed_not_emitted_while_still_blocked(sid):
    """追放が可決されて決定待ちに入る確定は、まだ決着ではない。"""
    from def_kari.api.routes.session_turn_engine import _on_turn_progress_unblocked
    sess = _session(sid, _pending_expel_followup={"target_id": "char_b"})
    emitted = []
    with patch("def_kari.api.routes.session_turn_engine._game_event_bus") as bus:
        bus.emit.side_effect = lambda *a, **kw: emitted.append(a)
        _on_turn_progress_unblocked(sid, sess)
    assert _closed_events(emitted) == []


def test_vote_closed_tells_front_not_to_resume_when_keeper_will(sid):
    from def_kari.api.routes.session_turn_engine import _on_turn_progress_unblocked
    sess = _session(sid)
    emitted = []
    with patch("def_kari.api.routes.session_turn_engine._game_event_bus") as bus,          patch("def_kari.api.routes.session_turn_engine._maybe_schedule_disconnect_skip"):
        bus.emit.side_effect = lambda *a, **kw: emitted.append(a)
        _on_turn_progress_unblocked(sid, sess, allow_auto_resume=False)
    assert _closed_events(emitted) == [{"resume": False}]


def test_dice_uses_session_rulebook_even_if_request_omits_it(sid):
    """プレイヤーのタブはルールブックを選ぶ画面を通らず空を送る。セッションの設定で判定すること
    （2026-11-08、実機確認で発覚: プレイヤーの判定だけ成功・失敗が出なかった）。"""
    sess = _session(sid, trpg_rulebook="def_original")
    result = _roll(sid, _PLAYER_A, character_id="char_a", stat_name="察知", rulebook_id="")
    assert result.get("judgment") is not None
    assert "→" in sess["history"][-1]["content"]
