"""POST /{session_id}/ai_keeper の同一ラウンドキャッシュ・全タブ配信のテスト。

キーパーの発火はクライアント駆動（各タブがラウンド完了を検知して自律的にこの
エンドポイントを叩く）ため、同じラウンドで複数タブがほぼ同時に呼びうる。以前は
(1) 呼び出したタブへの同期レスポンスのみでKEEPER_NARRATEDのようなブロードキャストが
一切無く、他タブには何も届かなかった、(2) 二重生成の防止も無かった。両方を修正した
（2026-09-06、実機でユーザーが「TRPGモードなのにGMがしゃべってない」と発見）。
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from def_kari.api.main import app
from def_kari.api.routes.session import _sessions, issue_player_jwt
from def_kari.api.routes import session_gameplay
from def_kari.gm.events import game_event_bus

client = TestClient(app)


def _start_trpg_session():
    resp = client.post(
        "/api/session/start",
        json={"character_ids": [], "online_mode": True, "trpg_mode": True},
    )
    d = resp.json()
    sid = d["session_id"]
    sess = _sessions[sid]
    sess["trpg_mode"] = True
    sess["human_keeper"] = False
    sess["initiative"] = ["char_a"]
    sess["human_char_ids"] = ["char_a"]
    sess["name_map"]["char_a"] = "Alice"
    token = issue_player_jwt(sid, "player", "char_a")
    sess["players"][token] = "char_a"
    return sid, token


def _fake_narrate(*args, **kwargs):
    return {"text": "扉の向こうから物音が聞こえる。", "judgments": [], "advance_scene": False, "propose_end": False, "error": None}


def test_second_call_in_same_round_returns_cache_without_regenerating():
    sid, token = _start_trpg_session()
    try:
        with patch.object(session_gameplay._gm_agent, "narrate", side_effect=_fake_narrate) as mock_narrate:
            r1 = client.post(f"/api/session/{sid}/ai_keeper", json={}, headers={"Authorization": f"Bearer {token}"})
            r2 = client.post(f"/api/session/{sid}/ai_keeper", json={}, headers={"Authorization": f"Bearer {token}"})
        assert mock_narrate.call_count == 1
        assert r1.json()["text"] == r2.json()["text"] == "扉の向こうから物音が聞こえる。"
    finally:
        _sessions.pop(sid, None)


def test_new_round_after_round_seq_bump_regenerates():
    sid, token = _start_trpg_session()
    try:
        with patch.object(session_gameplay._gm_agent, "narrate", side_effect=_fake_narrate) as mock_narrate:
            client.post(f"/api/session/{sid}/ai_keeper", json={}, headers={"Authorization": f"Bearer {token}"})
            _sessions[sid]["_round_seq"] = _sessions[sid].get("_round_seq", 0) + 1
            client.post(f"/api/session/{sid}/ai_keeper", json={}, headers={"Authorization": f"Bearer {token}"})
        assert mock_narrate.call_count == 2
    finally:
        _sessions.pop(sid, None)


def test_ai_keeper_broadcasts_keeper_narrated_to_all_tabs():
    sid, token = _start_trpg_session()
    received = []
    game_event_bus.subscribe("KEEPER_NARRATED", lambda s, ev: received.append(ev))
    try:
        with patch.object(session_gameplay._gm_agent, "narrate", side_effect=_fake_narrate):
            resp = client.post(f"/api/session/{sid}/ai_keeper", json={}, headers={"Authorization": f"Bearer {token}"})
        matching = [ev for ev in received if ev["session_id"] == sid]
        assert len(matching) == 1
        assert matching[0]["payload"]["text"] == resp.json()["text"]
        assert matching[0]["payload"]["round_seq"] == resp.json()["round_seq"]
    finally:
        _sessions.pop(sid, None)
