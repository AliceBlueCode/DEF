"""セッションの画像生成で、使うバックエンド・モデルを選べるのはローカルのホストだけ（2026-11-08）。

以前は参加者の権限で、本文の backend / t2i_backend / t2i_model を指定でき、課金APIの画像生成や
ホストのPCにある任意のモデルを使わせられた（全体レビューの第2回で指摘）。
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from def_kari.api.main import app
from def_kari.api.routes.session import _sessions, issue_player_jwt

client = TestClient(app)

_PICKED = {"backend": "openai", "t2i_backend": "openai", "t2i_model": "some-private-model"}


def _call(token: str, sid: str) -> dict:
    seen = {}

    def fake_impl(session_id, req):
        seen.update(backend=req.backend, t2i_backend=req.t2i_backend, t2i_model=req.t2i_model)
        return {"status": "ok"}

    with patch("def_kari.api.routes.session_image._generate_session_image_impl", fake_impl):
        r = client.post(f"/api/session/{sid}/generate-image", json=_PICKED,
                        headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return seen


def test_player_cannot_pick_backend_or_model():
    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True}).json()
    sid = start["session_id"]
    try:
        tok = issue_player_jwt(sid, "player", "char_p")
        _sessions[sid]["players"][tok] = "char_p"
        seen = _call(tok, sid)
        assert seen == {"backend": "", "t2i_backend": "", "t2i_model": ""}
    finally:
        _sessions.pop(sid, None)


def test_local_host_can_still_pick_backend_and_model():
    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True}).json()
    sid = start["session_id"]
    try:
        seen = _call(start["host_token"], sid)
        assert seen == _PICKED
    finally:
        _sessions.pop(sid, None)
