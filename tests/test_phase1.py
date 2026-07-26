"""Phase 1 WebSocket / broadcast handler のテスト。"""

import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch


# ── GameEventBus ワイルドカード ──────────────────────────────────────

def test_event_bus_wildcard():
    """'*' ハンドラが全イベントで呼ばれること。"""
    from def_kari.gm.events import GameEventBus
    bus = GameEventBus()
    received = []
    bus.subscribe("*", lambda sid, ev: received.append(ev["type"]))
    bus.emit("s1", "SCENE_NARRATED", {})
    bus.emit("s1", "JUDGMENT_RESOLVED", {})
    assert received == ["SCENE_NARRATED", "JUDGMENT_RESOLVED"]


def test_event_bus_specific_and_wildcard():
    """特定ハンドラとワイルドカードが両方呼ばれること。"""
    from def_kari.gm.events import GameEventBus
    bus = GameEventBus()
    specific = []
    wildcard = []
    bus.subscribe("FLAG_UPDATED", lambda sid, ev: specific.append(ev["type"]))
    bus.subscribe("*", lambda sid, ev: wildcard.append(ev["type"]))
    bus.emit("s1", "FLAG_UPDATED", {})
    bus.emit("s1", "SCENE_NARRATED", {})
    assert specific == ["FLAG_UPDATED"]
    assert wildcard == ["FLAG_UPDATED", "SCENE_NARRATED"]


def test_event_bus_wildcard_handler_exception_ignored():
    """ワイルドカードハンドラが例外を投げても他のハンドラは実行されること。"""
    from def_kari.gm.events import GameEventBus
    bus = GameEventBus()
    ok = []
    bus.subscribe("*", lambda sid, ev: (_ for _ in ()).throw(RuntimeError("fail")))
    bus.subscribe("*", lambda sid, ev: ok.append(True))
    bus.emit("s1", "SCENE_NARRATED", {})
    assert ok == [True]


# ── _check_ws_rate ───────────────────────────────────────────────────

def test_check_ws_rate_allows_within_limit():
    """制限内のメッセージは許可されること。"""
    from def_kari.api.routes.session import _check_ws_rate, _sessions
    sid = "_rate_test_allow"
    _sessions[sid] = {"ws_rate": {}}
    try:
        for _ in range(60):
            assert _check_ws_rate(sid, "tok1", limit=60, window=60) is True
    finally:
        _sessions.pop(sid, None)


def test_check_ws_rate_blocks_over_limit():
    """61回目は制限超過になること。"""
    from def_kari.api.routes.session import _check_ws_rate, _sessions
    sid = "_rate_test_block"
    _sessions[sid] = {"ws_rate": {}}
    try:
        for _ in range(60):
            _check_ws_rate(sid, "tok2", limit=60, window=60)
        assert _check_ws_rate(sid, "tok2", limit=60, window=60) is False
    finally:
        _sessions.pop(sid, None)


def test_check_ws_rate_different_tokens_independent():
    """トークンごとに独立してカウントされること。"""
    from def_kari.api.routes.session import _check_ws_rate, _sessions
    sid = "_rate_test_indep"
    _sessions[sid] = {"ws_rate": {}}
    try:
        for _ in range(60):
            _check_ws_rate(sid, "tokA", limit=60, window=60)
        # tokB はまだ0回なので許可される
        assert _check_ws_rate(sid, "tokB", limit=60, window=60) is True
    finally:
        _sessions.pop(sid, None)


# ── WebSocket エンドポイント ─────────────────────────────────────────
# Phase 2（JWT認証追加）完了後にここにWSテストを追加する
