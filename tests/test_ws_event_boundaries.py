"""WSで全タブに配るイベントの情報の境界（2026-11-08、全体レビューの第2回で指摘）。

1. ホストのトークン（JWT）が、WSの接続・切断の通知に入って全タブへ配られていた。
   participant_id を token_to_participant から引き、無ければトークンそのものを代わりに
   使っていたため（ホストは token_to_participant に無い）。招待コードで入れる Observer が
   ホストになりすませた。発生源を直し、全イベントの中継でもトークンを含むものを止める。
2. GM専用（gm_only）のイベント（NPC の知識の追加）が、プレイヤーと Observer にも届いていた。
   中継で、キーパーの接続にだけ送る。
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from fastapi.testclient import TestClient

from def_kari.api.main import app
from def_kari.api.routes import session_ws
from def_kari.api.routes.session_state import _sessions

SENTINEL_PREFIX = "E2E-SENTINEL-"


def _start_online(client: TestClient) -> tuple[str, str, str]:
    r = client.post("/api/session/start", json={"character_ids": [], "online_mode": True}).json()
    return r["session_id"], r["host_token"], r["invite_code"]


def _join_observer(client: TestClient, code: str) -> str:
    return client.post("/api/session/join", json={"invite_code": code}).json()["player_token"]


def _sentinel(client: TestClient, sid: str, host: str, n: int) -> str:
    """アプリの処理の中から区切りのイベントを出す（キーパーのメッセージ）。

    テストのスレッドから直接 emit すると、配信がアプリのイベントループに乗らず届かない。
    """
    label = f"{SENTINEL_PREFIX}{n}"
    r = client.post(f"/api/session/{sid}/keeper", json={"text": label},
                    headers={"Authorization": f"Bearer {host}"})
    assert r.status_code == 200
    return label


def _read_until(ws, label: str, limit: int = 50) -> list[dict]:
    got = []
    for _ in range(limit):
        m = ws.receive_json()
        if m.get("type") == "HUMAN_ACTION" and m.get("payload", {}).get("text") == label:
            return got
        got.append(m)
    raise AssertionError(f"sentinel {label} not received")


def test_host_token_is_not_broadcast_on_host_connect_or_disconnect():
    with TestClient(app) as client:
        sid, host, code = _start_online(client)
        obs = _join_observer(client, code)
        try:
            with client.websocket_connect(f"/api/session/{sid}/ws") as wo:
                wo.send_json({"type": "auth", "token": obs})
                received = []
                with client.websocket_connect(f"/api/session/{sid}/ws") as wh:
                    wh.send_json({"type": "auth", "token": host})
                    label = _sentinel(client, sid, host, 1)
                    _read_until(wh, label)  # ホストの接続の処理が終わった
                    received += _read_until(wo, label)
                # ホストの切断の後
                label = _sentinel(client, sid, host, 2)
                received += _read_until(wo, label)
                assert host not in str(received), "host JWT leaked to the observer"
        finally:
            _sessions.pop(sid, None)


def test_gm_only_event_reaches_keeper_but_not_observer():
    with TestClient(app) as client:
        sid, host, code = _start_online(client)
        obs = _join_observer(client, code)
        try:
            with client.websocket_connect(f"/api/session/{sid}/ws") as wh,                     client.websocket_connect(f"/api/session/{sid}/ws") as wo:
                wh.send_json({"type": "auth", "token": host})
                wo.send_json({"type": "auth", "token": obs})
                label = _sentinel(client, sid, host, 1)
                _read_until(wh, label)
                _read_until(wo, label)

                r = client.post(
                    f"/api/session/{sid}/npc/npc_1/knowledge",
                    json={"entry": "GMだけが知る秘密"},
                    headers={"Authorization": f"Bearer {host}"},
                )
                assert r.status_code == 200
                label = _sentinel(client, sid, host, 2)
                to_host = _read_until(wh, label)
                to_obs = _read_until(wo, label)
                assert any(m.get("type") == "FLAG_UPDATED" for m in to_host)
                assert not any(m.get("type") == "FLAG_UPDATED" for m in to_obs)
                assert "GMだけが知る秘密" not in str(to_obs)
        finally:
            _sessions.pop(sid, None)


def test_broadcast_drops_any_event_containing_a_session_token():
    """発生源を直しても、同じ型の漏れが再発したときに外へ出さない（中継の守り）。"""
    sent: list[tuple[str, dict]] = []

    async def fake_send(session_id, token, ws, event):
        sent.append((token, event))

    sess = {
        "players": {"t" * 40: "", "p" * 40: "char_p"},
        "host_token": "t" * 40,
        "token_to_participant": {"p" * 40: "char_p"},
        "ws_connections": {"t" * 40: object(), "p" * 40: object()},
    }

    async def run():
        with patch.dict(_sessions, {"_s": sess}), patch.object(session_ws, "_safe_send", fake_send):
            session_ws._ws_broadcast_handler("_s", {"type": "X", "payload": {"participant_id": "t" * 40}})
            session_ws._ws_broadcast_handler("_s", {"type": "OK", "payload": {"participant_id": "char_p"}})
            session_ws._ws_broadcast_handler("_s", {"type": "GM", "payload": {"gm_only": True}})
            await asyncio.sleep(0.05)

    asyncio.run(run())
    types = [(tok, ev["type"]) for tok, ev in sent]
    assert ("t" * 40, "X") not in types and ("p" * 40, "X") not in types
    assert ("t" * 40, "OK") in types and ("p" * 40, "OK") in types
    assert ("t" * 40, "GM") in types and ("p" * 40, "GM") not in types
