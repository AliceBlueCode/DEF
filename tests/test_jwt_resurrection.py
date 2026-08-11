"""8.30対策: 退室・追放済みJWTがプロセス再起動後に復活しうる問題のテスト。

_revoked_jtisはプロセスメモリ上のみで、autosave/起動時復元（_AUTOSAVE_DIR走査）を
経ない。leave_sessionはplayersからのトークン削除とrevoke_token()は行うが、
以前はautosaveを呼んでいなかったため、退室直後にクラッシュ/再起動すると
古いautosaveから復元されたセッションのplayersに退室済みトークンが残ったまま、
_revoked_jtisは空に戻り、署名・exp・session_id・roleが正しい退室済みJWTが
再び認証を通ってしまい得た。

対応は二段構え:
(1) require_host/require_player/require_keeper/require_participant・WS認証に
    「トークンが現在session["players"]に登録されているか」を最終防波堤として追加。
(2) leave_sessionでのトークン除去を即座にautosaveへ反映する（データの鮮度自体を保つ）。
"""

from unittest.mock import patch

from fastapi.testclient import TestClient
from def_kari.api.main import app

client = TestClient(app)


def _start_session():
    resp = client.post("/api/session/start", json={"character_ids": []})
    assert resp.status_code == 200
    d = resp.json()
    return d["session_id"], d["host_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _restored_session_without_token(sid: str) -> dict:
    """autosave復元直後を模した、players が空のセッション辞書
    （非シリアライズキーも持たない、test_autosave_restored_session.pyと同じ流儀）。"""
    return {
        "id": sid,
        "initiative": [],
        "name_map": {},
        "players": {},
        "host_token": "",
        "token_to_participant": {},
        "joined_participants": [],
        "invite_codes": {},
        "counters": {},
        "history": [],
        "turn": 0,
        "round": 1,
        "lobby_active": False,
    }


def test_token_currently_active_true_when_session_missing():
    from def_kari.api.routes.session import _token_currently_active
    assert _token_currently_active("no-such-session-id", "any-token") is True


def test_token_currently_active_true_when_registered():
    from def_kari.api.routes.session import _token_currently_active, _sessions
    sid, host_token = _start_session()
    try:
        assert _token_currently_active(sid, host_token) is True
    finally:
        _sessions.pop(sid, None)


def test_token_currently_active_false_when_not_registered():
    from def_kari.api.routes.session import _token_currently_active, issue_player_jwt, _sessions
    sid, _host_token = _start_session()
    try:
        stale_token = issue_player_jwt(sid, "player", "char_a")  # playersには登録しない
        assert _token_currently_active(sid, stale_token) is False
    finally:
        _sessions.pop(sid, None)


def test_require_host_rejects_valid_but_unregistered_token():
    """署名・exp・session_id・roleが全て正しくても、playersに無ければ401。"""
    from def_kari.api.routes.session import issue_player_jwt, _sessions

    sid, _ = _start_session()
    try:
        _sessions[sid] = _restored_session_without_token(sid)
        stale_host_token = issue_player_jwt(sid, "host")  # 復元後のplayersには存在しない

        resp = client.post(f"/api/session/{sid}/invite", json={"rating": "SFW"}, headers=_auth(stale_host_token))
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Token is no longer active"
    finally:
        _sessions.pop(sid, None)


def test_require_player_rejects_valid_but_unregistered_token():
    from def_kari.api.routes.session import issue_player_jwt, _sessions

    sid, _ = _start_session()
    try:
        _sessions[sid] = _restored_session_without_token(sid)
        stale_player_token = issue_player_jwt(sid, "player", "char_a")

        resp = client.post(
            f"/api/session/{sid}/human_turn", json={"action": "skip"}, headers=_auth(stale_player_token),
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Token is no longer active"
    finally:
        _sessions.pop(sid, None)


def test_require_keeper_rejects_valid_but_unregistered_token():
    from def_kari.api.routes.session import issue_player_jwt, _sessions

    sid, _ = _start_session()
    try:
        _sessions[sid] = _restored_session_without_token(sid)
        stale_gm_token = issue_player_jwt(sid, "gm")

        resp = client.get(f"/api/session/{sid}/events", headers=_auth(stale_gm_token))
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Token is no longer active"
    finally:
        _sessions.pop(sid, None)


def test_require_participant_rejects_valid_but_unregistered_token():
    from def_kari.api.routes.session import issue_player_jwt, _sessions

    sid, _ = _start_session()
    try:
        _sessions[sid] = _restored_session_without_token(sid)
        stale_observer_token = issue_player_jwt(sid, "observer")

        resp = client.get(f"/api/session/{sid}", headers=_auth(stale_observer_token))
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Token is no longer active"
    finally:
        _sessions.pop(sid, None)


def test_require_participant_still_accepts_registered_token():
    """回帰確認: 過剰制限になっていないこと（正規のホストトークンは引き続き通る）。"""
    sid, host_token = _start_session()
    try:
        resp = client.get(f"/api/session/{sid}", headers=_auth(host_token))
        assert resp.status_code == 200
    finally:
        from def_kari.api.routes.session import _sessions
        _sessions.pop(sid, None)


def test_leave_triggers_autosave_removing_stale_token(tmp_path):
    """leave_session が players 除去を即座に autosave へ反映すること
    （以前はここでautosaveしておらず、直後にクラッシュ/再起動すると
    退室済みトークンがautosaveファイルに残ったままになっていた）。"""
    from def_kari.api.routes import session as session_module
    import json as _json

    with patch.object(session_module, "_AUTOSAVE_DIR", tmp_path):
        start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
        d = start.json()
        sid = d["session_id"]
        host_token = d["host_token"]

        inv = client.post(f"/api/session/{sid}/invite", json={"rating": "SFW"}, headers=_auth(host_token))
        invite_code = inv.json()["invite_code"]

        join = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": {"name": "Guest"}})
        assert join.status_code == 200
        player_token = join.json()["player_token"]

        # join自体はautosaveしない（guest_charsのみ_autosave_visitorsで永続化）ため、
        # セッション進行中の何らかの操作で後からautosaveされた状態を模して1回呼ぶ。
        session_module._autosave(sid)
        autosave_path = tmp_path / f"{sid}.json"
        assert autosave_path.exists()
        saved_before = _json.loads(autosave_path.read_text(encoding="utf-8"))
        assert player_token in saved_before.get("players", {})

        leave = client.post(f"/api/session/{sid}/leave", headers=_auth(player_token))
        assert leave.status_code == 200

        saved_after = _json.loads(autosave_path.read_text(encoding="utf-8"))
        assert player_token not in saved_after.get("players", {}), (
            "leave直後にautosaveが更新され、退室済みトークンが除去されているはず"
        )

        session_module._sessions.pop(sid, None)


def test_ws_rejects_valid_but_unregistered_token():
    """WS認証もplayers登録の有無を確認すること（close 4001）。"""
    from fastapi.testclient import TestClient as _TC
    from starlette.websockets import WebSocketDisconnect
    from def_kari.api.main import app as _app
    from def_kari.api.routes.session import issue_player_jwt, _sessions
    import pytest

    ws_client = _TC(_app)
    sid, _ = _start_session()
    try:
        _sessions[sid] = _restored_session_without_token(sid)
        stale_token = issue_player_jwt(sid, "host")

        with ws_client.websocket_connect(f"/api/session/{sid}/ws") as ws:
            ws.send_json({"type": "auth", "token": stale_token})
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
        assert exc.value.code == 4001
    finally:
        _sessions.pop(sid, None)
