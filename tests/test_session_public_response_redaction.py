"""GET /{session_id}（無認証）が認証トークン・招待コードを平文で返さないことのテスト。

以前は`_session_for_json`（autosave用に「全部残す」設計）をGETレスポンスにも
そのまま流用しており、host_token・invited_gm_token・players（{token: char_id}、
キーが全参加者の認証トークン）・invite_codes・token_to_participantが無認証で
丸見えになっていた。session_idさえ知っていれば（＝招待コードで参加した時点で
必ず知っている）GETリクエスト1発でセッション内の全員に完全になりすませる状態
だった（DEF_kari_セキュリティ設計書_内部用.md 8.1参照）。
"""

from fastapi.testclient import TestClient
from def_kari.api.main import app

client = TestClient(app)

_SECRET_KEYS = {"host_token", "invited_gm_token", "players", "invite_codes", "token_to_participant"}


def test_get_session_does_not_leak_tokens_or_invite_codes():
    start = client.post("/api/session/start", json={"character_ids": []})
    assert start.status_code == 200
    sid = start.json()["session_id"]
    host_token = start.json()["host_token"]

    inv = client.post(
        f"/api/session/{sid}/invite",
        json={"rating": "SFW"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert inv.status_code == 200

    resp = client.get(f"/api/session/{sid}")
    assert resp.status_code == 200
    session = resp.json()["session"]

    leaked = _SECRET_KEYS & session.keys()
    assert not leaked, f"GET /{{session_id}} leaked secret fields: {leaked}"

    body_str = str(session)
    assert host_token not in body_str, "host_token value must not appear anywhere in the public response"


def test_get_session_still_exposes_gameplay_fields():
    """機密フィールドの除外が過剰になっていないこと（initiative等は引き続き見える）の回帰確認。"""
    start = client.post("/api/session/start", json={"character_ids": []})
    sid = start.json()["session_id"]

    resp = client.get(f"/api/session/{sid}")
    session = resp.json()["session"]
    assert "initiative" in session
    assert "name_map" in session


def test_autosave_serialization_still_keeps_tokens_for_restore():
    """`_session_for_json`（autosave用）は引き続きhost_token等を保持すること
    （復元に必要なため、公開用の除外を適用してはいけない）。"""
    from def_kari.api.routes.session import _session_for_json, _sessions

    sid = "_redaction_autosave_test"
    _sessions[sid] = {
        "id": sid,
        "host_token": "secret_host_token_value",
        "invite_codes": {"SFW-ABC-123": {"rating": "SFW", "used": False}},
        "initiative": [],
    }
    try:
        serialized = _session_for_json(_sessions[sid])
        assert serialized.get("host_token") == "secret_host_token_value"
        assert "SFW-ABC-123" in serialized.get("invite_codes", {})
    finally:
        _sessions.pop(sid, None)
