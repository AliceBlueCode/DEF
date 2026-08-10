"""session.local_routerの固定パスがsession.routerの`GET /{session_id}`に
食われて到達不能になる回帰テスト。

main.pyでsession.routerをsession.local_routerより先にinclude_routerしていたため、
`GET /api/session/saved`・`GET /api/session/debug`が単一セグメントの`{session_id}`
パターンにマッチしてしまい、常に{"error": "Session not found"}を返していた
（2026-08-10、「過去のセッション一覧」機能が動いていないことから発覚）。
"""

from fastapi.testclient import TestClient


def test_saved_sessions_endpoint_is_not_shadowed_by_session_id_route():
    from def_kari.api.main import app
    client = TestClient(app)
    resp = client.get("/api/session/saved")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data
    assert data.get("error") != "Session not found"


def test_session_debug_endpoint_is_not_shadowed_by_session_id_route():
    from def_kari.api.main import app
    client = TestClient(app)
    resp = client.get("/api/session/debug")
    assert resp.status_code == 200
    assert resp.json().get("error") != "Session not found"


def test_unknown_session_id_still_returns_not_found():
    """局所修正の副作用確認: 本物のsession_idルックアップは引き続き機能すること。"""
    from def_kari.api.main import app
    client = TestClient(app)
    resp = client.get("/api/session/_definitely_not_a_real_session_id")
    assert resp.status_code == 200
    assert resp.json().get("error") == "Session not found"
