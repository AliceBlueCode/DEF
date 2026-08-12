"""Phase 2: JWT発行・検証・招待コード・参加APIのテスト。"""

import pytest
from unittest.mock import patch


# ── JWT 発行・検証 ─────────────────────────────────────────────────

def test_issue_and_verify_host_jwt():
    from def_kari.api.routes.session import issue_player_jwt, verify_jwt
    token = issue_player_jwt("sess-1", "host")
    payload = verify_jwt(token)
    assert payload["session_id"] == "sess-1"
    assert payload["role"] == "host"
    assert "jti" in payload


def test_issue_and_verify_player_jwt():
    from def_kari.api.routes.session import issue_player_jwt, verify_jwt
    token = issue_player_jwt("sess-2", "player", "char_alice")
    payload = verify_jwt(token)
    assert payload["role"] == "player"
    assert payload["char_id"] == "char_alice"


def test_revoke_token_blocks_verify():
    from def_kari.api.routes.session import issue_player_jwt, verify_jwt, revoke_token, _revoked_jtis
    from jose import JWTError
    token = issue_player_jwt("sess-r", "player")
    revoke_token(token)
    with pytest.raises(JWTError):
        verify_jwt(token)
    # クリーンアップ
    payload_raw = verify_jwt.__code__  # just to confirm import ok
    # jti 除去
    from jose import jwt as _jwt
    from def_kari.api.routes.session import _get_jwt_secret
    p = _jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
    _revoked_jtis.pop(p["jti"], None)


def test_revoke_token_stores_expiry_and_cleanup_prunes_expired_only():
    """以前は_cleanup_revoked_jtisがsession["players"]からpop済みのトークンを対象に
    difference_updateしており、revoke_token()で追加したjtiが実質永久にブラックリストへ
    残り続けるバグがあった（join/leaveを繰り返すたびに無制限に増加）。expベースの
    間引きに変更したことを検証する。"""
    import time as _time
    from def_kari.api.routes.session import (
        issue_player_jwt, revoke_token, _revoked_jtis,
        _cleanup_expired_revoked_jtis, _revoked_jtis_last_cleanup,
    )
    from jose import jwt as _jwt
    from def_kari.api.routes.session import _get_jwt_secret

    expired_token = issue_player_jwt("sess-cleanup-1", "player")
    fresh_token = issue_player_jwt("sess-cleanup-2", "player")
    revoke_token(expired_token)
    revoke_token(fresh_token)

    expired_jti = _jwt.decode(expired_token, _get_jwt_secret(), algorithms=["HS256"])["jti"]
    fresh_jti = _jwt.decode(fresh_token, _get_jwt_secret(), algorithms=["HS256"])["jti"]
    assert expired_jti in _revoked_jtis
    assert fresh_jti in _revoked_jtis

    try:
        # 片方だけ期限切れ扱いにする（本来は24h後のexpを過去に書き換えるのと等価）。
        _revoked_jtis[expired_jti] = _time.time() - 1.0
        # クリーンアップの間引き間隔（10分）を無視させて即座に実行させる。
        _revoked_jtis_last_cleanup["t"] = float("-inf")
        _cleanup_expired_revoked_jtis()

        assert expired_jti not in _revoked_jtis, "期限切れjtiがクリーンアップ後も残っている"
        assert fresh_jti in _revoked_jtis, "未失効のjtiが誤って削除された"
    finally:
        _revoked_jtis.pop(expired_jti, None)
        _revoked_jtis.pop(fresh_jti, None)


def test_invalid_token_raises():
    from def_kari.api.routes.session import verify_jwt
    from jose import JWTError
    with pytest.raises(JWTError):
        verify_jwt("not.a.valid.token")


# ── 招待コード生成 ──────────────────────────────────────────────────

def test_generate_invite_code_format():
    from def_kari.api.routes.session import _generate_invite_code
    code = _generate_invite_code("R18")
    parts = code.split("-")
    assert len(parts) == 3
    assert parts[0] == "R18"
    assert len(parts[1]) == 3
    assert len(parts[2]) == 3


def test_generate_invite_code_no_ambiguous_chars():
    from def_kari.api.routes.session import _generate_invite_code
    for _ in range(50):
        code = _generate_invite_code("SFW")
        alpha_part = code.split("-")[1]
        num_part = code.split("-")[2]
        assert "O" not in alpha_part and "I" not in alpha_part
        assert "0" not in num_part and "1" not in num_part


# ── 招待レートリミット ────────────────────────────────────────────

def test_invite_rate_allows_under_limit():
    from def_kari.api.routes.session import _check_invite_rate, _invite_fail_rate, _invite_locked_until
    _invite_fail_rate.clear()
    _invite_locked_until.clear()
    for _ in range(9):
        from def_kari.api.routes.session import _record_invite_fail
        _record_invite_fail("127.0.0.1")
    assert _check_invite_rate("127.0.0.1") is True
    _invite_fail_rate.clear()
    _invite_locked_until.clear()


def test_invite_rate_blocks_at_10():
    from def_kari.api.routes.session import (
        _check_invite_rate, _record_invite_fail,
        _invite_fail_rate, _invite_locked_until,
    )
    _invite_fail_rate.clear()
    _invite_locked_until.clear()
    for _ in range(10):
        _record_invite_fail("10.0.0.1")
    assert _check_invite_rate("10.0.0.1") is False
    _invite_fail_rate.clear()
    _invite_locked_until.clear()


# ── start_session に host_token が含まれること ──────────────────

def test_start_session_returns_host_token():
    """start_session レスポンスに host_token が含まれること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    # 最小限のリクエスト: character_ids は空でもセッション作成可能なことを確認
    resp = client.post("/api/session/start", json={"character_ids": []})
    assert resp.status_code == 200
    data = resp.json()
    assert "host_token" in data
    assert data["host_token"]


# ── invite エンドポイント ────────────────────────────────────────

def test_invite_endpoint_creates_code():
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)

    # セッション作成
    start = client.post("/api/session/start", json={"character_ids": []})
    assert start.status_code == 200
    session_id = start.json()["session_id"]
    host_token = start.json()["host_token"]

    # 招待コード発行
    resp = client.post(
        f"/api/session/{session_id}/invite",
        json={"rating": "SFW"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "invite_code" in data
    assert data["rating"] == "SFW"


def test_invite_endpoint_rejects_non_host():
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import issue_player_jwt
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": []})
    session_id = start.json()["session_id"]
    player_token = issue_player_jwt(session_id, "player")

    resp = client.post(
        f"/api/session/{session_id}/invite",
        json={"rating": "SFW"},
        headers={"Authorization": f"Bearer {player_token}"},
    )
    assert resp.status_code == 403


# ── join エンドポイント ──────────────────────────────────────────

def test_join_session_with_valid_code():
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)

    # セッション作成 → 招待コード発行
    start = client.post("/api/session/start", json={"character_ids": []})
    session_id = start.json()["session_id"]
    host_token = start.json()["host_token"]

    invite = client.post(
        f"/api/session/{session_id}/invite",
        json={"rating": "SFW"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    invite_code = invite.json()["invite_code"]

    # 参加
    resp = client.post("/api/session/join", json={"invite_code": invite_code})
    assert resp.status_code == 200
    data = resp.json()
    assert "player_token" in data
    assert data["session_id"] == session_id


def test_join_session_invalid_code():
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _invite_fail_rate, _invite_locked_until
    _invite_fail_rate.clear()
    _invite_locked_until.clear()
    client = TestClient(app)
    resp = client.post("/api/session/join", json={"invite_code": "SFW-XXX-000"})
    assert resp.status_code == 404
    _invite_fail_rate.clear()
    _invite_locked_until.clear()
