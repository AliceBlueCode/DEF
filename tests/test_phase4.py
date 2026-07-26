"""Phase 4: サーバー自律AIターン（_run_ai_turns / _execute_ai_turn / _end_session）のテスト。"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock


# ── _get_current_speaker ─────────────────────────────────────────────

def test_get_current_speaker_normal():
    from def_kari.api.routes.session import _get_current_speaker
    sess = {"initiative": ["alice", "bob", "carol"], "turn": 1}
    assert _get_current_speaker(sess) == "bob"


def test_get_current_speaker_wrap():
    from def_kari.api.routes.session import _get_current_speaker
    sess = {"initiative": ["alice", "bob"], "turn": 4}
    assert _get_current_speaker(sess) == "alice"  # 4 % 2 == 0


def test_get_current_speaker_empty():
    from def_kari.api.routes.session import _get_current_speaker
    assert _get_current_speaker({"initiative": [], "turn": 0}) is None


# ── _run_ai_turns: 人間ターンで即停止 ──────────────────────────────

@pytest.mark.asyncio
async def test_run_ai_turns_stops_at_human():
    """現在のスピーカーが人間なら即停止してAIターンを実行しない。"""
    from def_kari.api.routes.session import _run_ai_turns, _sessions
    sid = "test-phase4-human"
    _sessions[sid] = {
        "initiative": ["char_human"],
        "turn": 0,
        "human_char_ids": ["char_human"],
        "guest_chars": {},
        "ai_task": None,
        "idle_shutdown_task": None,
    }
    called = []
    with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=lambda s: called.append(s) or {}):
        await _run_ai_turns(sid)
    assert called == []  # AIターンは呼ばれない
    del _sessions[sid]


@pytest.mark.asyncio
async def test_run_ai_turns_stops_on_error():
    """_execute_ai_turn が error を返したら停止する。"""
    from def_kari.api.routes.session import _run_ai_turns, _sessions
    sid = "test-phase4-error"
    _sessions[sid] = {
        "initiative": ["char_ai"],
        "turn": 0,
        "human_char_ids": [],
        "guest_chars": {},
        "ai_task": None,
        "idle_shutdown_task": None,
        "name_map": {"char_ai": "AI"},
    }
    calls = []
    def _fake_execute(s):
        calls.append(s)
        return {"error": "backend down"}

    with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=_fake_execute):
        await _run_ai_turns(sid)
    assert len(calls) == 1  # 1回試みてerrorで停止
    del _sessions[sid]


@pytest.mark.asyncio
async def test_run_ai_turns_stops_on_waiting_for_human():
    """_execute_ai_turn が waiting_for_human を返したら停止する。"""
    from def_kari.api.routes.session import _run_ai_turns, _sessions
    sid = "test-phase4-wait"
    _sessions[sid] = {
        "initiative": ["char_ai"],
        "turn": 0,
        "human_char_ids": [],
        "guest_chars": {},
        "ai_task": None,
        "idle_shutdown_task": None,
    }
    calls = []
    def _fake_execute(s):
        calls.append(s)
        return {"waiting_for_human": True}

    with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=_fake_execute):
        await _run_ai_turns(sid)
    assert len(calls) == 1
    del _sessions[sid]


@pytest.mark.asyncio
async def test_run_ai_turns_cancelled():
    """キャンセルされたらCancelledErrorが伝播する（_end_session等でキャンセル可能）。"""
    from def_kari.api.routes.session import _run_ai_turns, _sessions
    sid = "test-phase4-cancel"
    _sessions[sid] = {
        "initiative": ["char_ai"],
        "turn": 0,
        "human_char_ids": [],
        "guest_chars": {},
        "ai_task": None,
        "idle_shutdown_task": None,
    }

    blocker = asyncio.Event()

    def _slow_execute(s):
        # run_in_executor で呼ばれる同期関数の代わりに長時間ブロックをシミュレート
        import time
        time.sleep(0.05)
        return {}

    async def _run():
        with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=_slow_execute):
            await _run_ai_turns(sid)

    task = asyncio.create_task(_run())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    del _sessions[sid]


# ── _end_session ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_end_session_cancels_ai_task():
    """_end_session が ai_task をキャンセルすること。"""
    from def_kari.api.routes.session import _end_session, _sessions

    sid = "test-phase4-end"
    cancelled = []

    async def _long_task():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    ai_task = asyncio.create_task(_long_task())
    await asyncio.sleep(0)  # タスクを sleep まで進める
    _sessions[sid] = {
        "ai_task": ai_task,
        "idle_shutdown_task": None,
        "ws_connections": {},
        "players": {},
    }
    await _end_session(sid)
    assert cancelled == [True]
    # _end_session が pop するので既に削除済み
    assert sid not in _sessions


@pytest.mark.asyncio
async def test_end_session_no_session_is_noop():
    """存在しないセッションに _end_session を呼んでも例外が出ないこと。"""
    from def_kari.api.routes.session import _end_session
    await _end_session("nonexistent-session-id")  # 例外なし


# ── human_turn の send 後に ai_task が作られること ─────────────────

def test_human_turn_send_creates_ai_task():
    """POST /{session_id}/human_turn (send) で ai_task がセットされること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    # セッション作成（キャラなし）
    start = client.post("/api/session/start", json={"character_ids": []})
    sid = start.json()["session_id"]

    # 最初のキャラを人間にする（initiative が空なので手動でセット）
    sess = _sessions[sid]
    sess["initiative"] = ["char_human"]
    sess["turn"] = 0
    sess["human_char_ids"] = ["char_human"]
    sess["name_map"]["char_human"] = "Human"
    sess["counters"] = {}

    resp = client.post(f"/api/session/{sid}/human_turn", json={
        "action": "send",
        "text": "Hello world",
    })
    assert resp.status_code == 200
    assert resp.json()["action"] == "send"
    # ai_task が作成されていること（まだ done かもしれないが None ではない）
    assert sess["ai_task"] is not None
