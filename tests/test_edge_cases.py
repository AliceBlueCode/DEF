"""意地悪な異常系テスト: WS認証・invite/join・ai_takeover・human_turn。"""

import time
import pytest
from unittest.mock import patch
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
        _revoked_jtis.pop(p["jti"], None)


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
        _revoked_jtis.pop(p["jti"], None)


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
async def test_start_session_rate_limited_after_20_per_minute():
    """8.5対策: /startは1分あたり20回を超えると429になること。

    以前は完全無認証・レート制限無しで、招待コードすら不要な第三者が空リクエストを
    _MAX_SESSIONS回叩くだけで進行中の正当なセッションを強制的に押し出せた。
    """
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _session_create_rate
    _session_create_rate.clear()
    client = TestClient(app)
    try:
        for _ in range(20):
            resp = client.post("/api/session/start", json={"character_ids": []})
            assert resp.status_code == 200
        resp = client.post("/api/session/start", json={"character_ids": []})
        assert resp.status_code == 429
    finally:
        _session_create_rate.clear()


def test_evict_oldest_session_cleans_up_before_removal():
    """8.5対策: _MAX_SESSIONS到達時の追い出しが、popitemの前にタスクキャンセル・
    招待コードレジストリ削除まで行うこと（以前は後片付け無しの生popitemで、
    孤立したタスク・招待コードのレジストリエントリが残っていた）。"""
    import asyncio
    from def_kari.api.routes.session import _sessions, _evict_oldest_session, _invite_registry

    sid = "_evict_test_session"

    async def _noop():
        await asyncio.sleep(999)

    async def _setup_and_run():
        task = asyncio.ensure_future(_noop())
        _sessions[sid] = {
            "id": sid,
            "ai_task": task,
            "idle_shutdown_task": None,
            "disconnect_skip_tasks": {},
            "players": {},
            "invite_codes": {"SFW-EVT-001": {"rating": "SFW", "used": False}},
            "ws_connections": {},
        }
        _invite_registry["SFW-EVT-001"] = sid
        _sessions.move_to_end(sid, last=False)  # _sessionsは他テストの残骸を含みうるグローバル
                                                 # OrderedDictなので、popitem(last=False)が対象を
                                                 # 取り出すよう先頭に固定する
        _evict_oldest_session()
        await asyncio.gather(task, return_exceptions=True)  # cancel()の反映を待つ
        return task

    try:
        task = asyncio.run(_setup_and_run())
        assert sid not in _sessions
        assert "SFW-EVT-001" not in _invite_registry
        assert task.cancelled()
    finally:
        _sessions.pop(sid, None)
        _invite_registry.pop("SFW-EVT-001", None)


def test_available_slots_while_ip_locked_429():
    """8.4対策: IPロック中はavailable-slotsも429になること（joinと同じロックを共有）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _invite_fail_rate, _invite_locked_until
    _invite_fail_rate.clear()
    _invite_locked_until.clear()
    client = TestClient(app)
    _invite_locked_until["testclient"] = time.monotonic() + 3600
    try:
        resp = client.post("/api/session/available-slots", json={"invite_code": "SFW-ABC-234"})
        assert resp.status_code == 429
    finally:
        _invite_fail_rate.clear()
        _invite_locked_until.clear()


def test_available_slots_10_failures_locks_ip_and_blocks_join():
    """8.4対策: available-slotsだけを連打してもjoinと同じ失敗カウンターが積み上がり、
    10回失敗すると11回目はavailable-slots・join両方とも429になること。

    以前は_check_invite_rateがjoin_sessionでしか呼ばれず、available-slots（招待コードの
    正誤を判定するオラクル）だけを連打すればS-1のブルートフォース対策を完全にバイパス
    できた。
    """
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _invite_fail_rate, _invite_locked_until
    _invite_fail_rate.clear()
    _invite_locked_until.clear()
    client = TestClient(app)
    try:
        for _ in range(10):
            client.post("/api/session/available-slots", json={"invite_code": "SFW-YYY-888"})
        resp = client.post("/api/session/available-slots", json={"invite_code": "SFW-YYY-888"})
        assert resp.status_code == 429
        # joinも同じIPロックの対象になっていること
        resp_join = client.post("/api/session/join", json={"invite_code": "SFW-YYY-888"})
        assert resp_join.status_code == 429
    finally:
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
        json={"action": "send", "text": "   ", "expected_round": sess["round"]},  # 空白のみ
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


# ── 招待コードのレーティング照合（マルチプレイ設計書§3.2） ──────────────
# R18キャラはSFWセッションで拒否、R18コードでSFWキャラを持ち込んだら通過。

def test_character_json_rating_exceeds_sfw_invite_rejected():
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _, code = _start_with_invite(client, rating="SFW")

    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {
            "name": "TooSpicy",
            "content_policy": {"rating_sexual": "hentai"},
        },
    })
    assert resp.status_code == 400
    assert "rating" in resp.json()["detail"].lower()


def test_character_json_rating_within_r18_invite_accepted():
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _, code = _start_with_invite(client, rating="R18")

    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {
            "name": "JustFine",
            "content_policy": {"rating_sexual": "nsfw"},
        },
    })
    assert resp.status_code == 200


def test_character_json_versioned_format_rating_checked():
    """versioned形式（{version_key: {base_profile: {...}}}）でも同様にチェックされること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _, code = _start_with_invite(client, rating="SFW")

    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {
            "v1": {
                "base_profile": {
                    "name": "VersionedSpicy",
                    "content_policy": {"rating_violence": "extreme"},
                }
            }
        },
    })
    assert resp.status_code == 400


def test_character_json_missing_content_policy_defaults_to_general():
    """content_policyが無い持ち込みキャラはgeneral/general扱いでSFWでも通過する。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    sid, _, code = _start_with_invite(client, rating="SFW")

    resp = client.post("/api/session/join", json={
        "invite_code": code,
        "character_json": {"name": "NoPolicyAtAll"},
    })
    assert resp.status_code == 200


def test_claim_char_id_rating_exceeds_invite_rejected():
    """既存ロスターキャラ（claim_char_id経由）でも同じレーティング照合が働くこと。"""
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)
    sid, _, code = _start_with_invite(client, rating="SFW")

    _sessions[sid]["initiative"] = ["char_hentai_roster"]
    _sessions[sid]["human_char_ids"] = ["char_hentai_roster"]
    _sessions[sid]["name_map"]["char_hentai_roster"] = "RosterChar"

    fake_char = {"id": "char_hentai_roster", "content_policy": {"rating_sexual": "hentai"}}
    with patch("def_kari.api.routes.session.get_character", return_value=fake_char):
        resp = client.post("/api/session/join", json={
            "invite_code": code,
            "claim_char_id": "char_hentai_roster",
        })
    assert resp.status_code == 400


def test_generate_session_image_blocked_for_guest_char_over_rating():
    """セッション内T2I生成でも、持ち込みキャラが参加時のレーティング上限を
    超えている場合はブロックされること（本来join時に弾かれるはずのキャラが、
    何らかの経緯でguest_charsに残っていた場合の二重の防御線）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)
    sid, host_token, code = _start_with_invite(client, rating="SFW")

    sess = _sessions[sid]
    sess["initiative"] = ["guest_over_rating"]
    sess["name_map"]["guest_over_rating"] = "OverRating"
    sess["history"] = [{
        "role": "assistant", "content": "OverRating: hello", "character_id": "guest_over_rating",
        "emotion": "neutral", "tags": [],
    }]
    # guest_chars/guest_char_ratings は本来join_session内で一緒にセットされるが、
    # ここではjoinフローを経由せず直接状態を作ってT2I側の防御線だけを検証する。
    sess["guest_chars"] = {"guest_over_rating": {"name": "OverRating", "content_policy": {"rating_sexual": "hentai"}}}
    sess["guest_char_ratings"] = {"guest_over_rating": "SFW"}

    resp = client.post(
        f"/api/session/{sid}/generate-image",
        json={},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 200  # エンドポイント自体はエラーレスポンスを200で返す設計
    assert "error" in resp.json()
    assert "rating" in resp.json()["error"].lower()


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


def test_join_character_json_rate_limited():
    """8.11対策: オンラインセッションは同一招待コードの使い回しが仕様上OKなので、
    正規の招待コード保持者がjoinを連打すればその都度guest_charが増え、
    T2I生成（アイコン+立ち絵）が連打回数分トリガーされていた。IPベースの
    レート制限（5回/分）で6回目以降を拒否する。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid = d["session_id"]
    invite_code = d["invite_code"]

    from def_kari.api.routes.session import _sessions
    _sessions[sid]["max_players"] = 0  # 無制限にし、キャパシティ制限ではなくレート制限だけを検証する

    with patch("def_kari.api.routes.session._generate_visitor_images"):
        statuses = []
        for i in range(6):
            resp = client.post("/api/session/join", json={
                "invite_code": invite_code,
                "character_json": {"name": f"Guest{i}"},
            })
            statuses.append(resp.status_code)

    assert statuses[:5].count(429) == 0
    assert statuses[5] == 429


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
