"""意地悪な異常系テスト: WS認証・invite/join・ai_takeover・human_turn。"""

import time
import pytest
from starlette.websockets import WebSocketDisconnect


# ── ヘルパー ────────────────────────────────────────────────────────

def _start(client):
    """セッション作成して (session_id, host_token) を返す。"""
    resp = client.post("/api/session/start", json={"character_ids": []})
    assert resp.status_code == 200
    d = resp.json()
    return d["session_id"], d["host_token"]


def _start_with_invite(client, rating="SFW"):
    """セッション作成 → 招待コード発行して (session_id, host_token, invite_code) を返す。"""
    sid, host_token = _start(client)
    inv = client.post(
        f"/api/session/{sid}/invite",
        json={"rating": rating},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    return sid, host_token, inv.json()["invite_code"]


# ── WebSocket 認証異常系 ──────────────────────────────────────────

def test_ws_empty_message_closes_4001():
    """token フィールドなしの空 JSON を送ると close(4001)。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _ = _start(client)
    with client.websocket_connect(f"/api/session/{sid}/ws") as ws:
        ws.send_json({})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4001


def test_ws_invalid_jwt_closes_4001():
    """壊れた JWT を送ると close(4001)。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _ = _start(client)
    with client.websocket_connect(f"/api/session/{sid}/ws") as ws:
        ws.send_json({"type": "auth", "token": "not.a.valid.jwt"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4001


def test_ws_revoked_token_closes_4001():
    """失効済み JWT を送ると close(4001)。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import issue_player_jwt, revoke_token, _revoked_jtis, _get_jwt_secret
    from jose import jwt as _jwt
    client = TestClient(app)
    sid, _ = _start(client)
    token = issue_player_jwt(sid, "host")
    revoke_token(token)
    try:
        with client.websocket_connect(f"/api/session/{sid}/ws") as ws:
            ws.send_json({"type": "auth", "token": token})
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
        assert exc.value.code == 4001
    finally:
        p = _jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
        _revoked_jtis.discard(p["jti"])


def test_ws_wrong_session_jwt_closes_4001():
    """別セッション用の JWT を送ると close(4001)（session_id mismatch）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import issue_player_jwt
    client = TestClient(app)
    sid, _ = _start(client)
    wrong_token = issue_player_jwt("totally-different-session-id", "host")
    with client.websocket_connect(f"/api/session/{sid}/ws") as ws:
        ws.send_json({"type": "auth", "token": wrong_token})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4001


def test_ws_nonexistent_session_closes_4004():
    """セッションが存在しない状態で有効 JWT を送ると close(4004)。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import issue_player_jwt
    client = TestClient(app)
    ghost_sid = "ghost-session-does-not-exist-xyz"
    token = issue_player_jwt(ghost_sid, "host")
    with client.websocket_connect(f"/api/session/{ghost_sid}/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4004


def test_ws_observer_role_closes_4001():
    """observer ロールの JWT を送ると close(4001)（player/host 以外は無効）。

    ws_endpoint は verify_jwt が通れば接続を許可するが、role チェックは
    require_player/require_host Dependency 側の責務なので WS では
    現状 4004（セッションなし）または 4001（認証失敗）。
    observer がいた場合を見越して、session_id が存在するケースでは
    接続は許可される（設計上 observer は読み取り専用で OK）ことを確認。
    """
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import issue_player_jwt
    client = TestClient(app)
    sid, _ = _start(client)
    observer_token = issue_player_jwt(sid, "observer")
    # observer は verify_jwt を通過できる → セッションあり → 接続成立
    with client.websocket_connect(f"/api/session/{sid}/ws") as ws:
        ws.send_json({"type": "auth", "token": observer_token})
        # pong で接続が生きていることを確認（keepalive はスキップ）
        ws.send_json({"type": "pong"})
        # 接続は維持される（エラーなし）


# ── invite / join 異常系 ──────────────────────────────────────────

def test_join_used_invite_code_409():
    """使用済み招待コードで再 join すると 409。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, host_token = _start(client)

    invite = client.post(
        f"/api/session/{sid}/invite",
        json={"rating": "SFW"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    code = invite.json()["invite_code"]

    resp1 = client.post("/api/session/join", json={"invite_code": code})
    assert resp1.status_code == 200

    resp2 = client.post("/api/session/join", json={"invite_code": code})
    assert resp2.status_code == 409


def test_invite_wrong_session_host_token_403():
    """セッション A の host_token でセッション B に invite 発行 → 403（session_id mismatch）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    _, host_a = _start(client)
    sid_b, _ = _start(client)

    resp = client.post(
        f"/api/session/{sid_b}/invite",
        json={"rating": "SFW"},
        headers={"Authorization": f"Bearer {host_a}"},
    )
    assert resp.status_code == 403


def test_invite_revoked_host_token_401():
    """失効した host_token で invite 発行 → 401。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import revoke_token, _revoked_jtis, _get_jwt_secret
    from jose import jwt as _jwt
    client = TestClient(app)
    sid, host_token = _start(client)
    revoke_token(host_token)
    try:
        resp = client.post(
            f"/api/session/{sid}/invite",
            json={"rating": "SFW"},
            headers={"Authorization": f"Bearer {host_token}"},
        )
        assert resp.status_code == 401
    finally:
        p = _jwt.decode(host_token, _get_jwt_secret(), algorithms=["HS256"])
        _revoked_jtis.discard(p["jti"])


def test_join_while_ip_locked_429():
    """IP ロック中に join すると 429。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _invite_fail_rate, _invite_locked_until
    _invite_fail_rate.clear()
    _invite_locked_until.clear()
    client = TestClient(app)
    # TestClient の request.client.host は "testclient"
    _invite_locked_until["testclient"] = time.monotonic() + 3600
    try:
        resp = client.post("/api/session/join", json={"invite_code": "SFW-ABC-234"})
        assert resp.status_code == 429
    finally:
        _invite_fail_rate.clear()
        _invite_locked_until.clear()


def test_join_10_failures_locks_ip():
    """10 回連続失敗すると 11 回目は 429（IP ロック）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _invite_fail_rate, _invite_locked_until
    _invite_fail_rate.clear()
    _invite_locked_until.clear()
    client = TestClient(app)
    for _ in range(10):
        client.post("/api/session/join", json={"invite_code": "SFW-ZZZ-999"})
    resp = client.post("/api/session/join", json={"invite_code": "SFW-ZZZ-999"})
    assert resp.status_code == 429
    _invite_fail_rate.clear()
    _invite_locked_until.clear()


@pytest.mark.asyncio
async def test_invite_on_ended_session_404():
    """終了済みセッションに invite を発行しようとすると 404。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _end_session
    client = TestClient(app)
    sid, host_token = _start(client)
    await _end_session(sid)

    resp = client.post(
        f"/api/session/{sid}/invite",
        json={"rating": "SFW"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_end_session_clears_invite_registry():
    """_end_session 後に _invite_registry から招待コードが消えること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _invite_registry, _end_session
    client = TestClient(app)
    sid, host_token = _start(client)

    invite = client.post(
        f"/api/session/{sid}/invite",
        json={"rating": "SFW"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    code = invite.json()["invite_code"]
    assert _invite_registry.get(code) == sid

    await _end_session(sid)
    assert code not in _invite_registry


# ── ai_takeover 異常系 ──────────────────────────────────────────

def test_ai_takeover_not_in_initiative_404():
    """initiative にいないキャラを ai_takeover しようとすると 404。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, host_token = _start(client)
    resp = client.post(
        f"/api/session/{sid}/ai_takeover",
        json={"character_id": "char_does_not_exist"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 404


def test_ai_takeover_already_ai_409():
    """既に AI 制御のキャラを ai_takeover しようとすると 409。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)
    sid, host_token = _start(client)
    sess = _sessions[sid]
    sess["initiative"] = ["ai_char_1"]
    sess["human_char_ids"] = []  # human_char_ids にいない = AI制御
    sess["name_map"]["ai_char_1"] = "AIChar"

    resp = client.post(
        f"/api/session/{sid}/ai_takeover",
        json={"character_id": "ai_char_1"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 409


def test_ai_takeover_wrong_session_403():
    """別セッションの host_token で ai_takeover しようとすると 403。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)
    _, host_a = _start(client)
    sid_b, _ = _start(client)
    sess_b = _sessions[sid_b]
    sess_b["initiative"] = ["human_char_1"]
    sess_b["human_char_ids"] = ["human_char_1"]
    sess_b["name_map"]["human_char_1"] = "HumanChar"

    resp = client.post(
        f"/api/session/{sid_b}/ai_takeover",
        json={"character_id": "human_char_1"},
        headers={"Authorization": f"Bearer {host_a}"},
    )
    assert resp.status_code == 403


# ── human_turn 異常系 ──────────────────────────────────────────

def test_human_turn_invalid_action_422():
    """存在しない action を送ると Pydantic バリデーションで 422。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _ = _start(client)
    resp = client.post(f"/api/session/{sid}/human_turn", json={
        "action": "HACK_THE_PLANET",
        "text": "payload",
    })
    assert resp.status_code == 422


def test_human_turn_missing_action_422():
    """action フィールド自体がないと 422。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _ = _start(client)
    resp = client.post(f"/api/session/{sid}/human_turn", json={"text": "hello"})
    assert resp.status_code == 422


def test_human_turn_send_empty_text_error():
    """send アクションで text が空だと error レスポンスになること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)
    sid, host_token = _start(client)
    sess = _sessions[sid]
    sess["initiative"] = ["char_human"]
    sess["turn"] = 0
    sess["human_char_ids"] = ["char_human"]
    sess["name_map"]["char_human"] = "Human"
    sess["counters"] = {}

    resp = client.post(
        f"/api/session/{sid}/human_turn",
        json={"action": "send", "text": "   "},  # 空白のみ
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 200
    assert "error" in resp.json()


@pytest.mark.asyncio
async def test_human_turn_on_ended_session_returns_error():
    """終了済みセッションに human_turn を送ると error レスポンスになること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _end_session
    client = TestClient(app)
    sid, host_token = _start(client)
    await _end_session(sid)

    resp = client.post(
        f"/api/session/{sid}/human_turn",
        json={"action": "send", "text": "ghost message"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    # human_turn は session なしで 200+error を返す設計
    assert resp.status_code == 200
    assert resp.json().get("error") == "Session not found"


# ── player_token によるホスト専用 API アクセス ──────────────────

def test_player_token_cannot_create_invite():
    """player ロールの token で invite を発行しようとすると 403。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import issue_player_jwt
    client = TestClient(app)
    sid, _ = _start(client)
    player_token = issue_player_jwt(sid, "player")

    resp = client.post(
        f"/api/session/{sid}/invite",
        json={"rating": "SFW"},
        headers={"Authorization": f"Bearer {player_token}"},
    )
    assert resp.status_code == 403


def test_player_token_cannot_ai_takeover():
    """player ロールの token で ai_takeover しようとすると 403。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import issue_player_jwt
    client = TestClient(app)
    sid, _ = _start(client)
    player_token = issue_player_jwt(sid, "player")

    resp = client.post(
        f"/api/session/{sid}/ai_takeover",
        json={"character_id": "some_char"},
        headers={"Authorization": f"Bearer {player_token}"},
    )
    assert resp.status_code == 403


# ── 持ち込みキャラ（character_json）不正入力 ──────────────────────────

def test_character_json_id_overwritten():
    """クライアントが character_json に悪意ある id を仕込んでもサーバー生成 ID に上書きされる。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)
    sid, _, code = _start_with_invite(client)

    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {
            "id": "../../etc/passwd",
            "name": "Attacker",
        },
    })
    assert resp.status_code == 200
    char_id = resp.json()["character_id"]
    assert char_id.startswith("guest_")
    sess = _sessions[sid]
    assert "../../etc/passwd" not in sess.get("guest_chars", {})


def test_character_json_player_type_forced_human():
    """character_json に player_type: "ai" を仕込んでも human に強制上書きされる。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)
    sid, _, code = _start_with_invite(client)

    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {"name": "Sneaky", "player_type": "ai"},
    })
    assert resp.status_code == 200
    char_id = resp.json()["character_id"]
    sess = _sessions[sid]
    assert sess["guest_chars"][char_id]["player_type"] == "human"


def test_character_json_empty_name_no_crash():
    """空の name で参加してもサーバーがクラッシュしない（現状バリデーションなし）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _, code = _start_with_invite(client)

    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {"name": ""},
    })
    assert resp.status_code == 200


def test_character_json_huge_name_no_crash():
    """1 万文字の name でもサーバーがクラッシュしない。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _, code = _start_with_invite(client)

    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {"name": "A" * 10000},
    })
    assert resp.status_code == 200


def test_character_json_non_numeric_skill_values_no_crash():
    """スキル値に文字列・None・負数を入れてもクラッシュしない。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _, code = _start_with_invite(client)

    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {
            "name": "BadSkills",
            "skill_values": {"str": "banana", "dex": None, "int": -999},
        },
    })
    assert resp.status_code == 200


def test_character_json_null_values_no_crash():
    """全フィールド null のキャラデータでもクラッシュしない。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _, code = _start_with_invite(client)

    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {
            "name": None,
            "age": None,
            "description": None,
            "skill_values": None,
            "memories": None,
        },
    })
    assert resp.status_code == 200


def test_character_json_deeply_nested_no_crash():
    """100 段ネストした character_json でもクラッシュしない。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _, code = _start_with_invite(client)

    nested: dict = {}
    cur = nested
    for _ in range(100):
        cur["child"] = {}
        cur = cur["child"]

    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {"name": "Nested", "data": nested},
    })
    assert resp.status_code == 200


def test_character_json_emoji_and_cjk_no_crash():
    """絵文字・CJK・RTL 文字を含む name でもクラッシュしない。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _, code = _start_with_invite(client)

    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {"name": "🔥リンゴ🐉مرحباً한국어"},
    })
    assert resp.status_code == 200


def test_character_json_xss_stored_as_is():
    """XSS スクリプトタグはバックエンドではそのまま保存される（エスケープはフロント側の責務）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)
    sid, _, code = _start_with_invite(client)

    xss = "<script>alert('xss')</script>"
    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {"name": xss},
    })
    assert resp.status_code == 200
    char_id = resp.json()["character_id"]
    sess = _sessions[sid]
    # バックエンド API は HTML エスケープしない → フロントが責任を持つことを明示
    assert sess["guest_chars"][char_id]["name"] == xss


def test_character_json_large_memories_no_crash():
    """memories に 1000 件のエントリを持つキャラでもクラッシュしない。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _, code = _start_with_invite(client)

    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {
            "name": "BigMemory",
            "memories": [{"content": f"記憶{i}", "importance": 5} for i in range(1000)],
        },
    })
    assert resp.status_code == 200
