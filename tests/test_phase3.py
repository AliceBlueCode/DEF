"""Phase 3: human_char_ids複数対応のテスト。"""

import pytest
from fastapi.testclient import TestClient


def _make_client():
    from def_kari.api.main import app
    return TestClient(app)


def _start_session(**kwargs):
    client = _make_client()
    body = {"character_ids": [], **kwargs}
    resp = client.post("/api/session/start", json=body)
    assert resp.status_code == 200
    return client, resp.json()


# ── _is_human_char ────────────────────────────────────────────────────

def test_is_human_char_in_human_char_ids():
    """human_char_ids に含まれていれば True。"""
    from def_kari.api.routes.session import _is_human_char
    sess = {"human_char_ids": ["char_alice"], "guest_chars": {}}
    assert _is_human_char(sess, "char_alice") is True


def test_is_human_char_not_in_list():
    """human_char_ids にも guest_chars にも profiles にも該当なければ False。"""
    from def_kari.api.routes.session import _is_human_char
    sess = {"human_char_ids": [], "guest_chars": {}}
    assert _is_human_char(sess, "char_ai_npc", profiles={}) is False


def test_is_human_char_guest_chars():
    """guest_chars に含まれていれば人間扱い。"""
    from def_kari.api.routes.session import _is_human_char
    sess = {"human_char_ids": [], "guest_chars": {"guest_abc12345": {"id": "guest_abc12345"}}}
    assert _is_human_char(sess, "guest_abc12345") is True


# ── start_session に human_char_ids が含まれること ────────────────────

def test_start_session_has_human_char_ids():
    """start_session のセッションデータに human_char_ids フィールドがあること。"""
    from def_kari.api.routes.session import _sessions
    client, data = _start_session()
    sess = _sessions.get(data["session_id"])
    assert sess is not None
    assert "human_char_ids" in sess
    assert isinstance(sess["human_char_ids"], list)


# ── join → human_char_ids 更新 ────────────────────────────────────────

def test_join_adds_to_human_char_ids():
    """join_session 後に human_char_ids にキャラIDが追加されること。"""
    from def_kari.api.routes.session import _sessions, _invite_registry
    client, start_data = _start_session()
    session_id = start_data["session_id"]
    host_token = start_data["host_token"]

    invite = client.post(
        f"/api/session/{session_id}/invite",
        json={"rating": "SFW"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    invite_code = invite.json()["invite_code"]

    join = client.post("/api/session/join", json={
        "invite_code": invite_code,
        "character_json": {"name": "TestPlayer"},
    })
    assert join.status_code == 200
    char_id = join.json()["character_id"]

    sess = _sessions[session_id]
    assert char_id in sess["human_char_ids"]

    # クリーンアップ
    _invite_registry.pop(invite_code, None)


# ── ai_takeover エンドポイント ────────────────────────────────────────

def test_ai_takeover_removes_from_human_char_ids():
    """ai_takeover でキャラIDが human_char_ids から除去されること。"""
    from def_kari.api.routes.session import _sessions, _invite_registry
    client, start_data = _start_session()
    session_id = start_data["session_id"]
    host_token = start_data["host_token"]

    # セッションに手動でキャラを追加して initiative に入れる
    sess = _sessions[session_id]
    sess["initiative"].append("char_test_human")
    sess["human_char_ids"].append("char_test_human")
    sess["name_map"]["char_test_human"] = "TestHuman"

    resp = client.post(
        f"/api/session/{session_id}/ai_takeover",
        json={"character_id": "char_test_human"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 200
    assert "char_test_human" not in resp.json()["human_char_ids"]
    assert "char_test_human" not in sess["human_char_ids"]


def test_ai_takeover_rejects_non_human():
    """すでにAI制御のキャラに ai_takeover すると 409。"""
    from def_kari.api.routes.session import _sessions
    client, start_data = _start_session()
    session_id = start_data["session_id"]
    host_token = start_data["host_token"]

    sess = _sessions[session_id]
    sess["initiative"].append("char_ai")
    # human_char_ids には含めない

    resp = client.post(
        f"/api/session/{session_id}/ai_takeover",
        json={"character_id": "char_ai"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 409


def test_ai_takeover_rejects_non_host():
    """player ロールでは ai_takeover は 403。"""
    from def_kari.api.routes.session import issue_player_jwt
    client, start_data = _start_session()
    session_id = start_data["session_id"]
    player_token = issue_player_jwt(session_id, "player")

    resp = client.post(
        f"/api/session/{session_id}/ai_takeover",
        json={"character_id": "char_x"},
        headers={"Authorization": f"Bearer {player_token}"},
    )
    assert resp.status_code == 403
