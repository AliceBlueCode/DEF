"""main.py に追加したセキュリティミドルウェア（セキュリティヘッダー・/api/session ボディサイズ上限）、
および session.py のクライアントIP解決（S-1）のテスト。"""

from starlette.requests import Request


def _make_request(client_host: str | None, headers: dict[str, str] | None = None) -> Request:
    """`_is_trusted_proxy_hop` / `_resolve_client_ip` の単体テスト用に最小限の Request を組み立てる。"""
    scope = {
        "type": "http",
        "client": (client_host, 12345) if client_host is not None else None,
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    return Request(scope)


def test_csp_header_present_on_response():
    """全レスポンスにセキュリティヘッダー一式が付与されること（S-8）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)

    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.headers.get("content-security-policy") == "default-src 'self'; frame-ancestors 'none'"
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert resp.headers.get("referrer-policy") == "same-origin"


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


def test_session_body_size_limit_rejects_oversized_request_without_content_length():
    """8.15対策: Content-Lengthヘッダーが無い（chunked transfer相当）リクエストでも、
    ストリームの累積サイズが512KBを超えれば413になること。以前はContent-Lengthヘッダー
    のみを見ており、詐称・省略されると上限チェックを素通りできていた。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)

    def _oversized_stream():
        yield b'{"character_ids": []' + b" " * (512 * 1024 + 1) + b"}"

    resp = client.post("/api/session/start", content=_oversized_stream())
    assert resp.status_code == 413


def test_session_body_size_limit_allows_normal_request_without_content_length():
    """8.15対策: Content-Lengthが無くても、上限内のリクエストは通常どおり処理されること
    （ストリーム再構築後、後続のハンドラが正しくボディを読めることの確認）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)

    def _small_stream():
        yield b'{"character_ids": [], "online_mode": true}'

    resp = client.post("/api/session/start", content=_small_stream())
    assert resp.status_code == 200
    assert "session_id" in resp.json()


# ── S-1: クライアントIP解決（_is_trusted_proxy_hop / _resolve_client_ip）────────


def test_cf_header_alone_is_not_trusted(monkeypatch):
    """(a) 環境変数OFFの場合、CF-Connecting-IP ヘッダーだけでは信頼されない。"""
    monkeypatch.delenv("DEF_BEHIND_CLOUDFLARE_TUNNEL", raising=False)
    from def_kari.api.routes.session import _resolve_client_ip

    req = _make_request("127.0.0.1", {"CF-Connecting-IP": "203.0.113.9"})
    assert _resolve_client_ip(req) == "127.0.0.1"


def test_cf_header_trusted_only_with_flag_and_loopback_peer(monkeypatch):
    """(b) 環境変数ON かつ TCPピアがループバックの場合のみヘッダーを信頼する。"""
    monkeypatch.setenv("DEF_BEHIND_CLOUDFLARE_TUNNEL", "1")
    from def_kari.api.routes.session import _resolve_client_ip

    trusted = _make_request("127.0.0.1", {"CF-Connecting-IP": "203.0.113.9"})
    assert _resolve_client_ip(trusted) == "203.0.113.9"

    # TCPピアがループバックでなければ、フラグがONでもヘッダーは信頼しない
    # （直接公開構成でのヘッダー詐称対策）。
    untrusted_peer = _make_request("198.51.100.5", {"CF-Connecting-IP": "203.0.113.9"})
    assert _resolve_client_ip(untrusted_peer) == "198.51.100.5"


def test_cf_header_ignored_when_flag_disabled(monkeypatch):
    """(c) 環境変数OFF時は、TCPピアがループバックでもヘッダーは無視される。"""
    monkeypatch.delenv("DEF_BEHIND_CLOUDFLARE_TUNNEL", raising=False)
    from def_kari.api.routes.session import _resolve_client_ip

    req = _make_request("::1", {"CF-Connecting-IP": "203.0.113.9"})
    assert _resolve_client_ip(req) == "::1"


def test_resolve_client_ip_falls_back_when_no_client():
    """request.client が None の場合は "unknown" を返す（詐称の温床にしない）。"""
    from def_kari.api.routes.session import _resolve_client_ip

    req = _make_request(None)
    assert _resolve_client_ip(req) == "unknown"


def test_test_backend_rejects_non_json_content_type():
    """8.16対策: test-backendはContent-Typeがapplication/json以外だと415で拒否すること。
    text/plainのform enctype等を使ったsimple requestはCORSのプリフライトを回避できる
    ため、これを塞ぐことでCSRF経由のブラインドSSRFの糸口を無くす。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)

    resp = client.post(
        "/api/settings/test-backend",
        content='{"url": "http://127.0.0.1:9/"}',
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 415


def test_test_backend_allows_json_content_type():
    """回帰確認: 正規のapplication/jsonリクエストは引き続き処理されること
    （疎通先が存在しないため実際の接続は失敗するが、Content-Type検証自体は通過する）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)

    resp = client.post("/api/settings/test-backend", json={"url": "http://127.0.0.1:1/"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False  # 接続自体は失敗するはず（何も listen していないポート）
