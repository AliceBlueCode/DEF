"""切断（通信途絶）60秒タイムアウト→自動skipのテスト。

マルチプレイ設計書§3.7では「決定」と明記されていたが、実装されていたのは
PLAYER_DISCONNECTEDイベントによる切断検知の通知のみで、タイムアウト後の
自動スキップ処理は無かった（TODO.md）。
"""

import asyncio
from unittest.mock import patch

import pytest


def _base_session(sid: str, initiative: list[str], turn: int = 0) -> dict:
    return {
        "id": sid,
        "initiative": initiative,
        "human_char_ids": list(initiative),
        "guest_chars": {},
        "players": {},
        "ws_connections": {},
        "name_map": {c: c for c in initiative},
        "counters": {},
        "history": [],
        "turn": turn,
        "round": 1,
        "action_count": 0,
        "ai_task": None,
    }


# ── _apply_skip ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_skip_advances_turn_and_increments_counter():
    from def_kari.api.routes.session import _apply_skip, _sessions
    sid = "_apply_skip_test"
    _sessions[sid] = _base_session(sid, ["char_a", "char_b"], turn=0)
    try:
        with patch("def_kari.api.routes.session_turn_engine._run_ai_turns"):
            result = _apply_skip(sid, _sessions[sid], "char_a")
        assert result["action"] == "skip"
        assert _sessions[sid]["turn"] == 1
        assert _sessions[sid]["counters"]["char_a"] == 1
    finally:
        _sessions.pop(sid, None)


# ── _find_player_token ───────────────────────────────────────────────

def test_find_player_token_found_and_not_found():
    from def_kari.api.routes.session import _find_player_token
    session = {"players": {"tokA": "char_a", "tokB": "char_b"}}
    assert _find_player_token(session, "char_b") == "tokB"
    assert _find_player_token(session, "char_missing") is None


# ── _schedule_disconnect_skip / _cancel_disconnect_skip ────────────────

@pytest.mark.asyncio
async def test_disconnect_timeout_triggers_auto_skip_for_current_speaker():
    """現在のターン担当者が切断したまま短いタイムアウトが経過すると、自動でskipされること。"""
    from def_kari.api.routes.session import (
        _schedule_disconnect_skip, _sessions,
    )
    sid = "_disc_skip_test"
    sess = _base_session(sid, ["char_a", "char_b"], turn=0)
    sess["players"] = {"tok_a": "char_a"}
    # ws_connections に tok_a が無い＝切断中
    _sessions[sid] = sess
    try:
        with patch("def_kari.api.routes.session_turn_engine._disconnect_timeout_sec", return_value=0.05), \
             patch("def_kari.api.routes.session_turn_engine._run_ai_turns"):
            _schedule_disconnect_skip(sid, "char_a")
            await asyncio.sleep(0.15)
            assert _sessions[sid]["turn"] == 1
            assert _sessions[sid]["counters"].get("char_a") == 1
    finally:
        task = _sessions.get(sid, {}).get("disconnect_skip_tasks", {}).get("char_a")
        if task and not task.done():
            task.cancel()
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_reconnect_cancels_disconnect_timer_and_prevents_skip():
    """タイムアウト前に再接続（_cancel_disconnect_skip）すれば、skipが実行されないこと。"""
    from def_kari.api.routes.session import (
        _schedule_disconnect_skip, _cancel_disconnect_skip, _sessions,
    )
    sid = "_disc_skip_reconnect_test"
    sess = _base_session(sid, ["char_a", "char_b"], turn=0)
    sess["players"] = {"tok_a": "char_a"}
    _sessions[sid] = sess
    try:
        with patch("def_kari.api.routes.session_turn_engine._disconnect_timeout_sec", return_value=0.05), \
             patch("def_kari.api.routes.session_turn_engine._run_ai_turns"):
            _schedule_disconnect_skip(sid, "char_a")
            # 再接続（token再登録 + タイマーキャンセル）を模す
            _sessions[sid]["ws_connections"]["tok_a"] = object()
            _cancel_disconnect_skip(sid, "char_a")
            await asyncio.sleep(0.15)
            assert _sessions[sid]["turn"] == 0  # skipされていない
            assert "char_a" not in _sessions[sid]["counters"]
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_disconnect_timeout_noop_if_turn_already_advanced():
    """タイムアウト発火時、既に別経緯でターンが進んでいれば何もしないこと。"""
    from def_kari.api.routes.session import _schedule_disconnect_skip, _sessions
    sid = "_disc_skip_stale_test"
    sess = _base_session(sid, ["char_a", "char_b"], turn=0)
    sess["players"] = {"tok_a": "char_a"}
    _sessions[sid] = sess
    try:
        with patch("def_kari.api.routes.session_turn_engine._disconnect_timeout_sec", return_value=0.05), \
             patch("def_kari.api.routes.session_turn_engine._run_ai_turns"):
            _schedule_disconnect_skip(sid, "char_a")
            # タイマー発火前にターンが別経緯で進んでしまったことを模す
            _sessions[sid]["turn"] = 1
            await asyncio.sleep(0.15)
            # char_a はもう current speaker ではないので counters は変化しない
            assert "char_a" not in _sessions[sid]["counters"]
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_schedule_disconnect_skip_does_not_duplicate_timer():
    """同一キャラに対して連続で呼んでも、既存タイマーが生きていれば重複起動しないこと。"""
    from def_kari.api.routes.session import _schedule_disconnect_skip, _sessions
    sid = "_disc_skip_dup_test"
    sess = _base_session(sid, ["char_a"], turn=0)
    sess["players"] = {"tok_a": "char_a"}
    _sessions[sid] = sess
    try:
        with patch("def_kari.api.routes.session_turn_engine._disconnect_timeout_sec", return_value=5.0):
            _schedule_disconnect_skip(sid, "char_a")
            first_task = _sessions[sid]["disconnect_skip_tasks"]["char_a"]
            _schedule_disconnect_skip(sid, "char_a")
            second_task = _sessions[sid]["disconnect_skip_tasks"]["char_a"]
            assert first_task is second_task
    finally:
        for t in _sessions.get(sid, {}).get("disconnect_skip_tasks", {}).values():
            if not t.done():
                t.cancel()
        _sessions.pop(sid, None)


# ── _maybe_schedule_disconnect_skip ─────────────────────────────────────

def test_maybe_schedule_only_when_disconnected():
    """接続中のキャラにはタイマーを仕込まないこと。"""
    from def_kari.api.routes.session import _maybe_schedule_disconnect_skip, _sessions
    sid = "_maybe_sched_connected_test"
    sess = _base_session(sid, ["char_a"], turn=0)
    sess["players"] = {"tok_a": "char_a"}
    sess["ws_connections"] = {"tok_a": object()}  # 接続中
    _sessions[sid] = sess
    try:
        _maybe_schedule_disconnect_skip(sid, sess, "char_a")
        assert "char_a" not in sess.get("disconnect_skip_tasks", {})
    finally:
        _sessions.pop(sid, None)


def test_maybe_schedule_skips_chars_without_player_token():
    """オフラインセッション等、そもそもplayersに存在しないキャラにはタイマーを仕込まないこと。"""
    from def_kari.api.routes.session import _maybe_schedule_disconnect_skip, _sessions
    sid = "_maybe_sched_no_token_test"
    sess = _base_session(sid, ["char_a"], turn=0)
    # players が空＝WS接続で操作されていないキャラ
    _sessions[sid] = sess
    try:
        _maybe_schedule_disconnect_skip(sid, sess, "char_a")
        assert "char_a" not in sess.get("disconnect_skip_tasks", {})
    finally:
        _sessions.pop(sid, None)
