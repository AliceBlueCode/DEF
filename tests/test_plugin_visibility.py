"""見せてよいものの境界（visibility の口。差し込み口 5・6、要求仕様 S-801・S-803）。

手順6の4。架空のルールシステムのプラグインだけで確かめる（B-008）。プラグインはセッションの
`_grid_secret` を秘密として持ち、ホストにだけ見せる。秘密の値を変えても、ホスト以外が受け取るものが
変わらないこと（非干渉。S-803）を、WS の配信・接続のときの初期の配信・状態の取得・イベントのログで確かめる。
"""

import asyncio
import json
import shutil
import sys
from pathlib import Path

import pytest

from def_kari.api.routes import session_ws as ws_mod
from def_kari.api.routes import session_visibility as vis
from def_kari.api.routes.session_state import _sessions
from def_kari.trpg import plugins, registry

SAMPLE = Path(__file__).parent / "fixtures" / "plugins" / "sample_grid"

_VISIBILITY_INIT = '''
class S:
    id = "sample_grid"
    capabilities = frozenset({"visibility", "prompt_context", "image_prompt"})
    def validate_rulebook(self, d): return []
    def general_check(self, r, v, rb, **o): return {}
    def allowed_skills(self, rb): return frozenset()
    def dice_notation(self, rb): return "1d20"
    def build_rule_context(self, rb, sc, lang): return ""
    def session_view(self, session, audience):
        if session.get("_grid_break_view"):
            raise RuntimeError("broken plugin")
        if session.get("_grid_view_list"):
            return ["not", "a", "dict"]
        if session.get("_grid_leak_host_token"):
            return {"host": session["host_token"]}
        out = {"id": session["id"], "round": session.get("round", 1), "seen_as": audience["role"]}
        if audience["role"] == "host":
            out["secret"] = session.get("_grid_secret")
        return out
    def event_view(self, session, event, audience):
        if session.get("_grid_break"):
            raise RuntimeError("broken plugin")
        if session.get("_grid_bad_event") == "text":
            return "an event"
        if session.get("_grid_bad_event") == "no_type":
            return {"payload": {}}
        payload = event.get("payload") or {}
        if payload.get("host_only") and audience["role"] != "host":
            return None
        view = {"type": event["type"], "payload": {"text": payload.get("text", "")}}
        if audience["role"] == "host":
            view["payload"]["secret"] = session.get("_grid_secret")
        if audience["role"] == "player":
            view["payload"]["mine"] = audience["char_id"]
        return view
    def history_view(self, session, audience): return []
    def gm_context(self, session, lang): return ""
    def player_context(self, session, char_id, lang): return ""
    def image_prompt_source(self, session): return ""
def register(api):
    return S()
'''

HOST = "h" * 24
PLAYER = "p" * 24
OBSERVER = "o" * 24


@pytest.fixture
def table(monkeypatch, tmp_path):
    saved = dict(registry._REGISTRY)
    saved_loaded = registry._BUILTIN_LOADED
    registry._REGISTRY.clear()
    registry._BUILTIN_LOADED = False
    plugins._reset_for_tests()
    dst = tmp_path / "sample_grid"
    shutil.copytree(SAMPLE, dst)
    (dst / "sample_grid_plugin" / "__init__.py").write_text(_VISIBILITY_INIT, encoding="utf-8")
    monkeypatch.setenv("TRPG_PLUGIN_PATHS", str(dst))
    registry.load_all()
    assert registry.get("sample_grid") is not None
    sid = "_vis_table"
    sess = {"id": sid, "trpg_mode": True, "trpg_rulebook": "gb", "trpg_rule_system": "sample_grid",
            "trpg_plugin_version": "0.1.0", "host_token": HOST, "_grid_secret": "s-1", "round": 2,
            "players": {HOST: "", PLAYER: "char_a", OBSERVER: ""}, "history": [{"text": "gm note"}]}
    _sessions[sid] = sess
    yield sess
    _sessions.pop(sid, None)
    for t in (HOST, PLAYER, OBSERVER):
        ws_mod._ws_audiences.pop(t, None)
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)
    registry._BUILTIN_LOADED = saved_loaded
    plugins._reset_for_tests()
    for name in [m for m in sys.modules if m.startswith("def_trpg_plugin_")]:
        sys.modules.pop(name, None)


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_json(self, event):
        self.sent.append(json.loads(json.dumps(event)))


_AUDIENCES = {HOST: {"role": "host"}, PLAYER: {"role": "player", "char_id": "char_a"}, OBSERVER: {"role": "observer"}}


def _connect_all(sess):
    sockets = {}
    for token, payload in _AUDIENCES.items():
        sockets[token] = _FakeWS()
        ws_mod._register_ws_connection(sess, token, sockets[token], vis.audience_of(payload))
    return sockets


def _broadcast(sess, event):
    async def run():
        ws_mod._ws_broadcast_handler(sess["id"], event)
        for _ in range(5):
            await asyncio.sleep(0)
    asyncio.run(run())


# ── 相手 ─────────────────────────────────────────────

@pytest.mark.parametrize("payload,expected", [
    ({"role": "host"}, {"role": "host", "char_id": ""}),
    ({"role": "player", "char_id": "c1"}, {"role": "player", "char_id": "c1"}),
    ({"role": "gm", "char_id": "c1"}, {"role": "gm", "char_id": ""}),
    ({"role": "admin"}, {"role": "observer", "char_id": ""}),
    (None, {"role": "observer", "char_id": ""}),
])
def test_audience_of(payload, expected):
    assert vis.audience_of(payload) == expected


# ── WS の配信（差し込み口 5） ───────────────────────────────

def test_each_connection_gets_its_own_view(table):
    sockets = _connect_all(table)
    _broadcast(table, {"type": "NARRATION", "payload": {"text": "hello", "raw": "unfiltered"}})
    host, player, observer = (sockets[t].sent for t in (HOST, PLAYER, OBSERVER))
    assert host == [{"type": "NARRATION", "payload": {"text": "hello", "secret": "s-1"}}]
    assert player == [{"type": "NARRATION", "payload": {"text": "hello", "mine": "char_a"}}]
    assert observer == [{"type": "NARRATION", "payload": {"text": "hello"}}]


def test_event_the_plugin_withholds_is_not_sent(table):
    sockets = _connect_all(table)
    _broadcast(table, {"type": "ENEMY_MOVED", "payload": {"host_only": True, "text": "x"}})
    assert len(sockets[HOST].sent) == 1
    assert sockets[PLAYER].sent == [] and sockets[OBSERVER].sent == []


def test_changing_the_secret_does_not_change_what_others_receive(table):
    """非干渉（S-803）: 秘密の値を変えても、ホスト以外が受け取るものは同じ。"""
    received = []
    for secret in ("s-1", "s-2-very-different"):
        table["_grid_secret"] = secret
        sockets = _connect_all(table)
        _broadcast(table, {"type": "NARRATION", "payload": {"text": "same"}})
        received.append({t: sockets[t].sent for t in (PLAYER, OBSERVER)})
        assert sockets[HOST].sent[0]["payload"]["secret"] == secret  # ホストには届く（陽性の対照）
    assert received[0] == received[1]


def test_a_view_with_a_session_token_is_dropped(table):
    sockets = _connect_all(table)
    table["_grid_secret"] = PLAYER  # 口が誤ってトークンを入れた
    _broadcast(table, {"type": "NARRATION", "payload": {"text": "t"}})
    assert sockets[HOST].sent == []
    assert len(sockets[PLAYER].sent) == 1 and len(sockets[OBSERVER].sent) == 1


def test_a_failing_view_sends_nothing_and_pauses(table):
    sockets = _connect_all(table)
    table["_grid_break"] = True
    _broadcast(table, {"type": "NARRATION", "payload": {"text": "t"}})
    assert all(s.sent == [] for s in sockets.values())
    assert table["ai_paused"] is True and table["plugin_error"]["method"] == "event_view"


def test_tables_without_the_hook_are_unchanged(table):
    table["trpg_rule_system"] = "def_original"
    table["trpg_plugin_version"] = ""
    sockets = _connect_all(table)
    event = {"type": "NARRATION", "payload": {"text": "hello", "raw": "unfiltered"}}
    _broadcast(table, event)
    assert all(s.sent == [event] for s in sockets.values())


def test_initial_send_goes_through_the_boundary(table):
    sockets = _connect_all(table)

    async def run():
        await ws_mod._send_through_boundary(table["id"], OBSERVER, sockets[OBSERVER],
                                            {"type": "WAITING_FOR_HUMAN", "payload": {"host_only": True}})
        await ws_mod._send_through_boundary(table["id"], OBSERVER, sockets[OBSERVER],
                                            {"type": "PARTICIPANTS_SNAPSHOT", "payload": {"text": "p"}})
    asyncio.run(run())
    assert sockets[OBSERVER].sent == [{"type": "PARTICIPANTS_SNAPSHOT", "payload": {"text": "p"}}]


def test_forgetting_a_connection_forgets_its_audience(table):
    sockets = _connect_all(table)
    ws_mod._forget_ws_connection(table, OBSERVER, sockets[OBSERVER])
    assert OBSERVER not in ws_mod._ws_audiences


# ── 状態の取得とイベントのログ（差し込み口 6） ────────────────────

def test_get_session_returns_the_view_for_the_caller(table):
    from def_kari.api.routes.session_gameplay import get_session
    host = get_session(table["id"], {"role": "host"})["session"]
    observer = get_session(table["id"], {"role": "observer"})["session"]
    assert host == {"id": "_vis_table", "round": 2, "seen_as": "host", "secret": "s-1"}
    assert observer == {"id": "_vis_table", "round": 2, "seen_as": "observer"}
    assert "history" not in observer  # DEF の許可リスト（history を含む）は使わない


def test_get_session_does_not_change_with_the_secret(table):
    from def_kari.api.routes.session_gameplay import get_session
    views = []
    for secret in ("s-1", "s-2"):
        table["_grid_secret"] = secret
        views.append([get_session(table["id"], {"role": r, "char_id": "char_a"})["session"]
                      for r in ("player", "observer")])
    assert views[0] == views[1]


def test_event_log_goes_through_the_boundary(table):
    from def_kari.api.routes.session_gameplay import get_session_events
    from def_kari.gm.events import game_event_bus
    game_event_bus.emit(table["id"], "ENEMY_MOVED", {"host_only": True, "text": "x"})
    game_event_bus.emit(table["id"], "NARRATION", {"text": "y"})
    gm = get_session_events(table["id"], {"role": "gm"})["events"]
    host = get_session_events(table["id"], {"role": "host"})["events"]
    assert [e["type"] for e in gm][-1:] == ["NARRATION"] and all(e["type"] != "ENEMY_MOVED" for e in gm)
    assert [e["type"] for e in host][-2:] == ["ENEMY_MOVED", "NARRATION"]


# ── レビュー 2026-11-22 の🔴1・🟡5 ─────────────────────────────────

def test_session_view_with_a_session_token_is_refused_and_pauses(table):
    """🔴1: session_view にもトークンの守りを当てる（WS の SESSION_VIEW と GET の両方がここを通る）。"""
    table["host_token"] = HOST
    table["_grid_leak_host_token"] = True
    assert vis.session_view(table, {"role": "observer", "char_id": ""}) == {"plugin_error": True}
    assert table["ai_paused"] is True and "token" in table["plugin_error"]["error"]


@pytest.mark.parametrize("flag", ["_grid_break_view", "_grid_view_list"])
def test_get_session_falls_closed_when_the_view_fails(table, flag):
    from def_kari.api.routes.session_gameplay import get_session
    table[flag] = True
    assert get_session(table["id"], {"role": "observer"})["session"] == {"plugin_error": True}
    assert table["ai_paused"] is True


@pytest.mark.parametrize("bad", ["text", "no_type"])
def test_events_that_are_not_events_are_not_sent(table, bad):
    sockets = _connect_all(table)
    table["_grid_bad_event"] = bad
    _broadcast(table, {"type": "NARRATION", "payload": {"text": "t"}})
    assert all(s.sent == [] for s in sockets.values())
    assert table["ai_paused"] is True


def test_unresolvable_pinned_system_falls_closed_everywhere(table):
    from def_kari.api.routes.session_gameplay import get_session, get_session_events
    from def_kari.gm.events import game_event_bus
    table["trpg_plugin_version"] = "9.9.9"  # 版が変わった
    sockets = _connect_all(table)
    _broadcast(table, {"type": "NARRATION", "payload": {"text": "t"}})
    assert all(s.sent == [] for s in sockets.values())
    assert get_session(table["id"], {"role": "host"})["session"] == {"plugin_error": True}
    game_event_bus.emit(table["id"], "NARRATION", {"text": "y"})
    assert get_session_events(table["id"], {"role": "host"})["events"] == []


def test_gm_only_events_stay_with_keepers_even_through_the_boundary(table):
    sockets = _connect_all(table)
    _broadcast(table, {"type": "FLAG_UPDATED", "payload": {"gm_only": True, "text": "secret flag"}})
    assert len(sockets[HOST].sent) == 1
    assert sockets[PLAYER].sent == [] and sockets[OBSERVER].sent == []


def test_ws_endpoint_sends_the_initial_state_through_the_boundary(table):
    """🟡5 の1: 本物の ws_endpoint の配線（_send_through_boundary と SESSION_VIEW）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session_auth import issue_player_jwt
    token = issue_player_jwt(table["id"], "observer")
    table["players"][token] = ""
    table["lobby_active"] = True
    with TestClient(app) as client:
        with client.websocket_connect(f"/api/session/{table['id']}/ws") as ws:
            ws.send_json({"type": "auth", "token": token})
            first, second = ws.receive_json(), ws.receive_json()
    # 参加者の一覧は口が作り直したもの（口の event_view は payload を text だけにする）
    assert first == {"type": "PARTICIPANTS_SNAPSHOT", "payload": {"text": ""}}
    assert second["type"] == "SESSION_VIEW"
    assert second["payload"]["session"] == {"id": "_vis_table", "round": 2, "seen_as": "observer"}
    ws_mod._ws_audiences.pop(token, None)
