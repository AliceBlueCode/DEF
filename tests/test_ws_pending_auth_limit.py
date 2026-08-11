"""8.32対策: WS接続はfirst-message authを最大5秒待つが、それまでの「未認証で保持中」の
接続数には上限が無く、_check_ws_rate（認証後、token単位）もこのフェーズには効かない
ため、authを送らず大量に同時接続することでTCP/asyncioタスク/メモリを際限なく消費できた
（2026-08-11、外部レビュー指摘）。IP単位・プロセス全体単位の同時接続数上限のテスト。
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from def_kari.api.main import app
from def_kari.api.routes import session as session_module

client = TestClient(app)


def _start(c=None):
    c = c or client
    resp = c.post("/api/session/start", json={"character_ids": []})
    assert resp.status_code == 200
    return resp.json()["session_id"]


@pytest.fixture(autouse=True)
def _reset_ws_pending_auth_state():
    session_module._ws_pending_auth_by_ip.clear()
    session_module._ws_pending_auth_total["n"] = 0
    yield
    session_module._ws_pending_auth_by_ip.clear()
    session_module._ws_pending_auth_total["n"] = 0


def test_acquire_and_release_slot_tracks_per_ip_and_total():
    from def_kari.api.routes.session import (
        _try_acquire_ws_pending_auth_slot, _release_ws_pending_auth_slot,
        _ws_pending_auth_by_ip, _ws_pending_auth_total,
    )
    assert _try_acquire_ws_pending_auth_slot("1.2.3.4") is True
    assert _ws_pending_auth_by_ip["1.2.3.4"] == 1
    assert _ws_pending_auth_total["n"] == 1

    _release_ws_pending_auth_slot("1.2.3.4")
    assert "1.2.3.4" not in _ws_pending_auth_by_ip
    assert _ws_pending_auth_total["n"] == 0


def test_acquire_rejects_when_per_ip_limit_reached(monkeypatch):
    from def_kari.api.routes.session import _try_acquire_ws_pending_auth_slot
    monkeypatch.setattr(session_module, "_WS_PENDING_AUTH_LIMIT_PER_IP", 2)
    assert _try_acquire_ws_pending_auth_slot("1.2.3.4") is True
    assert _try_acquire_ws_pending_auth_slot("1.2.3.4") is True
    assert _try_acquire_ws_pending_auth_slot("1.2.3.4") is False
    # 別IPは影響を受けない
    assert _try_acquire_ws_pending_auth_slot("5.6.7.8") is True


def test_acquire_rejects_when_total_limit_reached(monkeypatch):
    from def_kari.api.routes.session import _try_acquire_ws_pending_auth_slot
    monkeypatch.setattr(session_module, "_WS_PENDING_AUTH_LIMIT_TOTAL", 2)
    assert _try_acquire_ws_pending_auth_slot("1.1.1.1") is True
    assert _try_acquire_ws_pending_auth_slot("2.2.2.2") is True
    assert _try_acquire_ws_pending_auth_slot("3.3.3.3") is False


def test_release_is_idempotent_and_never_goes_negative():
    from def_kari.api.routes.session import (
        _release_ws_pending_auth_slot, _ws_pending_auth_total,
    )
    _release_ws_pending_auth_slot("nonexistent-ip")
    assert _ws_pending_auth_total["n"] == 0


def test_ws_connection_over_per_ip_limit_closes_1013(monkeypatch):
    """未認証接続をper-IP上限まで保持した状態で、上限超過分は即座にclose(1013)
    され、5秒のauthタイムアウトを待たされないこと。"""
    monkeypatch.setattr(session_module, "_WS_PENDING_AUTH_LIMIT_PER_IP", 2)
    sid = _start()

    with client.websocket_connect(f"/api/session/{sid}/ws"):
        with client.websocket_connect(f"/api/session/{sid}/ws"):
            # ここまでで2本（上限）を消費している。3本目は即座に拒否される。
            with pytest.raises(WebSocketDisconnect) as exc:
                with client.websocket_connect(f"/api/session/{sid}/ws") as ws3:
                    ws3.receive_json()
            assert exc.value.code == 1013


def test_ws_connection_within_limit_still_authenticates_normally(monkeypatch):
    """上限以内であれば、既存のauth成功フローに一切影響しないこと（回帰確認）。"""
    from def_kari.api.routes.session import issue_player_jwt

    monkeypatch.setattr(session_module, "_WS_PENDING_AUTH_LIMIT_PER_IP", 20)
    sid = _start()
    token = issue_player_jwt(sid, "host")
    session_module._sessions[sid]["players"][token] = ""

    with client.websocket_connect(f"/api/session/{sid}/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.send_json({"type": "pong"})
        received = ws.receive_json()
        assert received.get("type") == "PLAYER_RECONNECTED"


def test_slot_released_after_successful_auth_allows_reuse(monkeypatch):
    """認証成功後は保留枠が解放され、同じIPから新たな接続を張り直せること
    （上限に達したまま塞がれっぱなしにならないこと）。"""
    from def_kari.api.routes.session import issue_player_jwt

    monkeypatch.setattr(session_module, "_WS_PENDING_AUTH_LIMIT_PER_IP", 1)
    sid = _start()
    token = issue_player_jwt(sid, "host")
    session_module._sessions[sid]["players"][token] = ""

    with client.websocket_connect(f"/api/session/{sid}/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.receive_json()  # PLAYER_RECONNECTED

    # 1本目は認証完了して抜けたので枠が解放されているはず。2本目も上限内で通る。
    with client.websocket_connect(f"/api/session/{sid}/ws") as ws2:
        ws2.send_json({"type": "auth", "token": token})
        ws2.receive_json()
