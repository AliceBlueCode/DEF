"""GET /{session_id} の情報境界のテスト（機密フィールド除外 + 参加者認証）。

以前は`_session_for_json`（autosave用に「全部残す」設計）をGETレスポンスにも
そのまま流用しており、host_token・invited_gm_token・players（{token: char_id}、
キーが全参加者の認証トークン）・invite_codes・token_to_participantが無認証で
丸見えになっていた。session_idさえ知っていれば（＝招待コードで参加した時点で
必ず知っている）GETリクエスト1発でセッション内の全員に完全になりすませる状態
だった（DEF_kari_セキュリティ設計書_内部用.md 8.1参照）。

さらに2026-08-11、エンドポイント自体を無認証から参加者認証（require_participant、
observer含む全ロール）に変更した。それまでは退室・追放済みの元参加者や
session_idを知った第三者が、セッション全体（history・npc_state・skill_values等）を
読み続けられた（expelの実効性を損なう）。機密フィールドの除外は「正規参加者にも
見せてはいけないもの」の防御として引き続き必要（多層防御）。
"""

from fastapi.testclient import TestClient
from def_kari.api.main import app

client = TestClient(app)

_SECRET_KEYS = {"host_token", "invited_gm_token", "players", "invite_codes", "token_to_participant"}


def _start_with_token():
    start = client.post("/api/session/start", json={"character_ids": []})
    assert start.status_code == 200
    return start.json()["session_id"], start.json()["host_token"]


def test_get_session_requires_participant_token():
    """無認証（ヘッダーなし）・不正トークン・他セッションのトークンをすべて拒否すること。"""
    sid, host_token = _start_with_token()
    other_sid, other_token = _start_with_token()

    # ヘッダーなし → FastAPIの必須Headerバリデーションで422
    assert client.get(f"/api/session/{sid}").status_code == 422
    # でたらめなトークン → 401
    assert client.get(
        f"/api/session/{sid}", headers={"Authorization": "Bearer not-a-jwt"}
    ).status_code == 401
    # 別セッション用の正規トークン → 403（BOLA対策のセッションスコープ検証）
    assert client.get(
        f"/api/session/{sid}", headers={"Authorization": f"Bearer {other_token}"}
    ).status_code == 403
    # 自セッションのトークン → 200
    assert client.get(
        f"/api/session/{sid}", headers={"Authorization": f"Bearer {host_token}"}
    ).status_code == 200


def test_get_session_rejects_revoked_token():
    """退室・追放でrevokeされたトークンでは読めなくなること（expelの実効性）。"""
    from def_kari.api.routes.session import revoke_token, _revoked_jtis, _get_jwt_secret
    from jose import jwt as _jwt

    sid, host_token = _start_with_token()
    assert client.get(
        f"/api/session/{sid}", headers={"Authorization": f"Bearer {host_token}"}
    ).status_code == 200

    revoke_token(host_token)
    try:
        assert client.get(
            f"/api/session/{sid}", headers={"Authorization": f"Bearer {host_token}"}
        ).status_code == 401
    finally:
        p = _jwt.decode(host_token, _get_jwt_secret(), algorithms=["HS256"])
        _revoked_jtis.pop(p["jti"], None)


def test_get_session_does_not_leak_tokens_or_invite_codes():
    sid, host_token = _start_with_token()

    inv = client.post(
        f"/api/session/{sid}/invite",
        json={"rating": "SFW"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert inv.status_code == 200

    resp = client.get(f"/api/session/{sid}", headers={"Authorization": f"Bearer {host_token}"})
    assert resp.status_code == 200
    session = resp.json()["session"]

    leaked = _SECRET_KEYS & session.keys()
    assert not leaked, f"GET /{{session_id}} leaked secret fields: {leaked}"

    body_str = str(session)
    assert host_token not in body_str, "host_token value must not appear anywhere in the public response"


def test_get_session_still_exposes_gameplay_fields():
    """機密フィールドの除外が過剰になっていないこと（initiative等は引き続き見える）の回帰確認。"""
    sid, host_token = _start_with_token()

    resp = client.get(f"/api/session/{sid}", headers={"Authorization": f"Bearer {host_token}"})
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
