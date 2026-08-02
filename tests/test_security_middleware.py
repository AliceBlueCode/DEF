"""main.py に追加したセキュリティミドルウェア（CSPヘッダー・/api/session ボディサイズ上限）のテスト。"""


def test_csp_header_present_on_response():
    """全レスポンスに Content-Security-Policy ヘッダーが付与されること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)

    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers.get("content-security-policy") == "default-src 'self'"


def test_session_body_size_limit_rejects_oversized_request():
    """/api/session 配下は 512KB を超える Content-Length で 413 を返すこと。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)

    oversized_payload = "x" * (512 * 1024 + 1)
    resp = client.post(
        "/api/session/start",
        content=oversized_payload,
        headers={"Content-Type": "application/json", "Content-Length": str(len(oversized_payload))},
    )
    assert resp.status_code == 413


def test_session_body_size_limit_allows_normal_request():
    """通常サイズのリクエストは 413 にならないこと（他のエンドポイント挙動を壊していない確認）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)

    resp = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    assert resp.status_code == 200


def test_body_size_limit_does_not_apply_outside_session_routes():
    """/api/session 以外のパスは 512KB を超えても本ミドルウェアでは弾かれないこと（スコープ確認）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)

    oversized_payload = "x" * (512 * 1024 + 1)
    resp = client.post(
        "/api/characters/nonexistent/raw-profile",
        content=oversized_payload,
        headers={"Content-Type": "application/json", "Content-Length": str(len(oversized_payload))},
    )
    assert resp.status_code != 413
