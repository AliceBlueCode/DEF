"""WS につないだタブに、参加者の一覧と接続の状況が送り直されること（PARTICIPANTS_SNAPSHOT）。

タブは読み込みのときに GET で参加者の一覧を取ってから WS につなぐ。その間に他の参加者が
接続し直すと PLAYER_RECONNECTED を取りこぼし、その参加者が「切断中」のまま残っていた
（2026-11-13、e2e restart_recovery D-4 の失敗で発覚）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from def_kari.api.main import app
from def_kari.api.routes.session_state import _sessions


def _start_online(client: TestClient) -> tuple[str, str, str]:
    r = client.post("/api/session/start", json={"character_ids": [], "online_mode": True}).json()
    return r["session_id"], r["host_token"], r["invite_code"]


def _join_observer(client: TestClient, code: str) -> str:
    return client.post("/api/session/join", json={"invite_code": code}).json()["player_token"]


def _first_snapshot(ws, limit: int = 20) -> list[dict]:
    for _ in range(limit):
        m = ws.receive_json()
        if m.get("type") == "PARTICIPANTS_SNAPSHOT":
            return m["payload"]["participants"]
    raise AssertionError("PARTICIPANTS_SNAPSHOT not received")


def test_tab_that_connects_later_learns_who_is_connected():
    """参加者が先につながっていれば、後からつないだホストのタブは「接続中」として受け取る
    （その参加者の PLAYER_RECONNECTED は、ホストがつなぐ前に配られていて届かない）。"""
    with TestClient(app) as client:
        sid, host, code = _start_online(client)
        obs = _join_observer(client, code)
        try:
            with client.websocket_connect(f"/api/session/{sid}/ws") as wo:
                wo.send_json({"type": "auth", "token": obs})
                _first_snapshot(wo)  # 参加者の接続の処理が終わった
                with client.websocket_connect(f"/api/session/{sid}/ws") as wh:
                    wh.send_json({"type": "auth", "token": host})
                    snap = _first_snapshot(wh)
            pid = _sessions[sid]["token_to_participant"][obs]
            entry = next(p for p in snap if p["participant_id"] == pid)
            assert entry["connected"] is True
        finally:
            _sessions.pop(sid, None)


def test_snapshot_is_the_same_as_get_and_has_no_tokens():
    with TestClient(app) as client:
        sid, host, code = _start_online(client)
        obs = _join_observer(client, code)
        try:
            with client.websocket_connect(f"/api/session/{sid}/ws") as wo:
                wo.send_json({"type": "auth", "token": obs})
                snap = _first_snapshot(wo)
                got = client.get(f"/api/session/{sid}", headers={"Authorization": f"Bearer {obs}"}).json()
            assert snap == got["participants"]
            assert host not in str(snap) and obs not in str(snap)
            assert all("game_sheet_id" not in p for p in snap)
        finally:
            _sessions.pop(sid, None)
