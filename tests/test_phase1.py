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


# ── _check_generation_rate / _try_acquire_generation_lock（S-6）────────

def test_check_generation_rate_allows_within_limit():
    """制限内の生成リクエストは許可されること。"""
    from def_kari.api.routes.session import _check_generation_rate, _sessions
    sid = "_gen_rate_test_allow"
    _sessions[sid] = {"gen_rate": {}}
    try:
        for _ in range(6):
            assert _check_generation_rate(sid, "tok1", limit=6, window=60) is True
    finally:
        _sessions.pop(sid, None)


def test_check_generation_rate_blocks_over_limit():
    """7回目は制限超過になること（デフォルト: 6回/分）。"""
    from def_kari.api.routes.session import _check_generation_rate, _sessions
    sid = "_gen_rate_test_block"
    _sessions[sid] = {"gen_rate": {}}
    try:
        for _ in range(6):
            _check_generation_rate(sid, "tok2", limit=6, window=60)
        assert _check_generation_rate(sid, "tok2", limit=6, window=60) is False
    finally:
        _sessions.pop(sid, None)


def test_check_generation_rate_independent_from_ws_rate():
    """generation用のバケットは _check_ws_rate（発言用）とは独立していること。"""
    from def_kari.api.routes.session import _check_generation_rate, _check_ws_rate, _sessions
    sid = "_gen_rate_test_indep"
    _sessions[sid] = {"gen_rate": {}, "ws_rate": {}}
    try:
        for _ in range(6):
            _check_generation_rate(sid, "tok3", limit=6, window=60)
        # gen_rate は上限に達しているが、ws_rate 側は別バケットなので影響を受けない
        assert _check_ws_rate(sid, "tok3", limit=60, window=60) is True
    finally:
        _sessions.pop(sid, None)


def test_check_generation_rate_ip_key_independent_from_jti_key():
    """8.6対策: IPベースのキー（ip:接頭辞）はjtiベースのキーとは独立したバケットで
    動作しつつ、同じ_check_generation_rate関数・同じgen_rate辞書を共有すること
    （generate_session_imageがjtiキーとIPキーの両方をチェックする実装の前提）。"""
    from def_kari.api.routes.session import _check_generation_rate, _sessions
    sid = "_gen_rate_test_ip_key"
    _sessions[sid] = {"gen_rate": {}}
    try:
        for _ in range(6):
            _check_generation_rate(sid, "jti_a", limit=6, window=60)
        assert _check_generation_rate(sid, "jti_a", limit=6, window=60) is False  # jti単位で制限超過

        # 別のjti（joinをやり直して使い捨てトークンを得た体）は制限内に見える
        assert _check_generation_rate(sid, "jti_b", limit=6, window=60) is True
        # しかしIPキーは呼び出しごとに積み上がるため、jtiを変え続けても最終的に制限される
        for _ in range(20):
            _check_generation_rate(sid, "ip:203.0.113.5", limit=20, window=60)
        assert _check_generation_rate(sid, "ip:203.0.113.5", limit=20, window=60) is False
    finally:
        _sessions.pop(sid, None)


def test_check_daily_generation_limit_unlimited_by_default():
    """9.2 Layer2「コスト上限キルスイッチ」: session_daily_generation_limitが0
    （デフォルト）なら常に許可されること。"""
    from def_kari.api.routes.session import _check_daily_generation_limit, _sessions
    sid = "_daily_limit_test_unlimited"
    _sessions[sid] = {"id": sid}  # 空dictはif not sess:でfalsy判定されてしまうため非空にする
    try:
        for _ in range(100):
            assert _check_daily_generation_limit(sid) is True
    finally:
        _sessions.pop(sid, None)


def test_check_daily_generation_limit_blocks_after_reaching_limit():
    """9.2 Layer2: 上限に達すると同じセッションの以降の呼び出しは拒否されること。"""
    from def_kari.api.routes.session import _check_daily_generation_limit, _sessions
    sid = "_daily_limit_test_block"
    _sessions[sid] = {"id": sid}
    try:
        with patch("def_kari.settings.load_settings", return_value={"session_daily_generation_limit": 3}):
            assert _check_daily_generation_limit(sid) is True
            assert _check_daily_generation_limit(sid) is True
            assert _check_daily_generation_limit(sid) is True
            assert _check_daily_generation_limit(sid) is False
    finally:
        _sessions.pop(sid, None)


def test_check_daily_generation_limit_resets_on_new_day():
    """9.2 Layer2: 保存されている日付が今日と違えばカウンターがリセットされること
    （日をまたいだホストがキルスイッチをリセットし忘れても翌日には自動的に復帰する）。"""
    from def_kari.api.routes.session import _check_daily_generation_limit, _sessions
    sid = "_daily_limit_test_reset"
    _sessions[sid] = {"daily_gen_date": "2000-01-01", "daily_gen_count": 999}
    try:
        with patch("def_kari.settings.load_settings", return_value={"session_daily_generation_limit": 5}):
            assert _check_daily_generation_limit(sid) is True
            assert _sessions[sid]["daily_gen_count"] == 1
    finally:
        _sessions.pop(sid, None)


def test_try_acquire_generation_lock_prevents_double_acquire():
    """同一トークンからの多重取得を防ぐこと。"""
    from def_kari.api.routes.session import _try_acquire_generation_lock, _release_generation_lock, _sessions
    sid = "_gen_lock_test"
    _sessions[sid] = {"gen_inflight": set()}
    try:
        assert _try_acquire_generation_lock(sid, "tok4") is True
        assert _try_acquire_generation_lock(sid, "tok4") is False  # 既に取得中
        _release_generation_lock(sid, "tok4")
        assert _try_acquire_generation_lock(sid, "tok4") is True  # 解放後は再取得できる
    finally:
        _sessions.pop(sid, None)


def test_try_acquire_generation_lock_independent_per_token():
    """トークンごとに独立してロックされること。"""
    from def_kari.api.routes.session import _try_acquire_generation_lock, _sessions
    sid = "_gen_lock_test_indep"
    _sessions[sid] = {"gen_inflight": set()}
    try:
        assert _try_acquire_generation_lock(sid, "tokA") is True
        assert _try_acquire_generation_lock(sid, "tokB") is True  # 別トークンは影響を受けない
    finally:
        _sessions.pop(sid, None)


# ── _check_circuit_breaker / _record_violation_and_maybe_trip（9.3 Layer3）───

def test_check_circuit_breaker_allows_by_default():
    """circuit_brokenフラグが立っていなければ許可されること。"""
    from def_kari.api.routes.session import _check_circuit_breaker, _sessions
    sid = "_breaker_test_default"
    _sessions[sid] = {"id": sid}
    try:
        assert _check_circuit_breaker(sid) is True
    finally:
        _sessions.pop(sid, None)


def test_check_circuit_breaker_blocks_when_tripped():
    """circuit_broken=Trueなら拒否されること。"""
    from def_kari.api.routes.session import _check_circuit_breaker, _sessions
    sid = "_breaker_test_tripped"
    _sessions[sid] = {"id": sid, "circuit_broken": True}
    try:
        assert _check_circuit_breaker(sid) is False
    finally:
        _sessions.pop(sid, None)


def test_record_violation_and_maybe_trip_sets_flag_at_threshold():
    """閾値到達時、セッションのcircuit_brokenフラグが自動的に立つこと。"""
    from def_kari.api.routes.session import _record_violation_and_maybe_trip, _sessions
    from def_kari.safety import audit_log
    sid = "_breaker_test_trip_flag"
    _sessions[sid] = {"id": sid}
    audit_log._violations.pop(sid, None)
    try:
        for _ in range(9):
            _record_violation_and_maybe_trip("vote_deliberate", sid, "203.0.113.9", "jti-x")
        assert _sessions[sid].get("circuit_broken", False) is False
        _record_violation_and_maybe_trip("vote_deliberate", sid, "203.0.113.9", "jti-x")  # 10回目
        assert _sessions[sid]["circuit_broken"] is True
    finally:
        _sessions.pop(sid, None)
        audit_log._violations.pop(sid, None)


# ── WebSocket エンドポイント ─────────────────────────────────────────
# Phase 2（JWT認証追加）完了後にここにWSテストを追加する
