"""手番を自分で回すルールシステムの卓（turn_driver。差し込み口 1、基本設計書 11.4）。

手順6の5。架空のルールシステムのプラグインだけで確かめる（B-008）。
- セッションの状態を変える DEF の操作は、許可リストの外なら 409（ルーターのすべての操作を走査して確かめる。
  後から足された操作も、許可リストに入れない限り断られる）。
- 再開・人間の手番の入力・ホストから GM への指示は、口の handle_request に回る。
- DEF の AI の手番の処理（_run_ai_turns）は動かない。
"""

import re
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from def_kari.api.main import app
from def_kari.api.routes import session_state
from def_kari.api.routes.session_auth import issue_player_jwt
from def_kari.api.routes.session_state import _sessions
from def_kari.trpg import plugins, registry

SAMPLE = Path(__file__).parent / "fixtures" / "plugins" / "sample_grid"

_INIT = '''
class S:
    id = "sample_grid"
    capabilities = frozenset({"turn_driver", "persistence"})
    calls = []
    def validate_rulebook(self, d): return []
    def general_check(self, r, v, rb, **o): return {}
    def allowed_skills(self, rb): return frozenset()
    def dice_notation(self, rb): return "1d20"
    def build_rule_context(self, rb, sc, lang): return ""
    def check_create(self, req): return ""
    def uses_def_autosave(self, s): return False
    def list_campaigns(self, rb): return []
    def allows_vote(self, s, a, k): return False
    def handle_request(self, session_id, audience, request):
        S.calls.append((session_id, audience, request))
        if request["data"].get("text") == "boom":
            raise RuntimeError("broken plugin")
        if request["data"].get("text") == "no":
            return {"accepted": False, "reason": "not your turn"}
        if request["data"].get("text") == "odd":
            return "accepted"
        return {"accepted": True, "reason": "", "revision": 7}
def register(api):
    return S()
'''

SID = "_turn_table"


@pytest.fixture
def table(monkeypatch, tmp_path):
    saved = dict(registry._REGISTRY)
    saved_loaded = registry._BUILTIN_LOADED
    registry._REGISTRY.clear()
    registry._BUILTIN_LOADED = False
    plugins._reset_for_tests()
    dst = tmp_path / "sample_grid"
    shutil.copytree(SAMPLE, dst)
    (dst / "sample_grid_plugin" / "__init__.py").write_text(_INIT, encoding="utf-8")
    monkeypatch.setenv("TRPG_PLUGIN_PATHS", str(dst))
    registry.load_all()
    system = registry.get("sample_grid")
    assert system is not None
    system.calls.clear()
    host = issue_player_jwt(SID, "host")
    player = issue_player_jwt(SID, "player", "char_a")
    _sessions[SID] = {
        "id": SID, "trpg_mode": True, "trpg_rulebook": "gb", "trpg_rule_system": "sample_grid",
        "trpg_plugin_version": "0.1.0", "campaign_id": "c1", "host_token": host, "lobby_active": False,
        "players": {host: "", player: "char_a"}, "token_to_participant": {}, "history": [],
        "initiative": ["char_a"], "turn": 0, "round": 1, "name_map": {"char_a": "A"},
        "human_char_ids": ["char_a"], "ai_paused": True, "plugin_error": {"method": "x"},
    }
    yield {"system": system, "host": host, "player": player}
    _sessions.pop(SID, None)
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)
    registry._BUILTIN_LOADED = saved_loaded
    plugins._reset_for_tests()
    for name in [m for m in sys.modules if m.startswith("def_trpg_plugin_")]:
        sys.modules.pop(name, None)


def _session_routes():
    """/api/session/{session_id}... の HTTP の操作（WS を除く）。"""
    out = []
    # app.routes は include した router を遅延で包むので、セッションの router を直接走査する
    for router in (session_state.router, session_state.local_router):
        for r in router.routes:
            if isinstance(r, APIRoute) and r.path.startswith("/{session_id}"):
                for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                    out.append((m, "/api/session" + r.path, r.endpoint.__name__))
    assert len(out) > 30
    return out


def _fill(path):
    return re.sub(r"\{(\w+)\}", lambda m: SID if m.group(1) == "session_id" else "x1", path)


ALLOWED = session_state._TURN_DRIVER_PASS | session_state._TURN_DRIVER_HANDLE


def test_allowlist_names_are_real_endpoints():
    names = {name for _m, _p, name in _session_routes()}
    assert ALLOWED <= names, ALLOWED - names


@pytest.mark.parametrize("method,path,name", [r for r in _session_routes() if r[2] not in ALLOWED],
                         ids=lambda v: v if isinstance(v, str) and v.startswith("/") else None)
def test_every_other_operation_is_refused(table, method, path, name):
    with TestClient(app) as client:
        r = client.request(method, _fill(path), json={}, headers={"Authorization": f"Bearer {table['host']}"})
    assert r.status_code == 409, (name, r.status_code, r.text[:200])
    assert "runs its own turns" in r.text


def test_other_tables_are_not_gated(table):
    _sessions[SID]["trpg_rule_system"] = "def_original"
    _sessions[SID]["trpg_plugin_version"] = ""
    with TestClient(app) as client:
        r = client.post(f"/api/session/{SID}/designate", json={},
                        headers={"Authorization": f"Bearer {table['host']}"})
    assert "runs its own turns" not in r.text


def test_resume_goes_to_the_rule_system_and_clears_the_pause(table):
    with TestClient(app) as client:
        r = client.post(f"/api/session/{SID}/ai_resume", headers={"Authorization": f"Bearer {table['host']}"})
    assert r.status_code == 200 and r.json()["revision"] == 7
    sid, audience, request = table["system"].calls[-1]
    assert (sid, audience, request["kind"]) == (SID, {"role": "host", "char_id": ""}, "resume")
    assert _sessions[SID]["ai_paused"] is False and "plugin_error" not in _sessions[SID]
    assert _sessions[SID].get("ai_task") is None  # DEF の AI の手番の処理は動かない


def test_human_turn_and_keeper_go_to_the_rule_system(table):
    with TestClient(app) as client:
        r = client.post(f"/api/session/{SID}/human_turn", json={"action": "send", "text": "move"},
                        headers={"Authorization": f"Bearer {table['player']}"})
        assert r.status_code == 200, r.text
        r = client.post(f"/api/session/{SID}/keeper", json={"text": "be harsh"},
                        headers={"Authorization": f"Bearer {table['host']}"})
        assert r.status_code == 200, r.text
    kinds = [(c[1]["role"], c[1]["char_id"], c[2]["kind"]) for c in table["system"].calls]
    assert kinds == [("player", "char_a", "human_turn"), ("host", "", "keeper")]
    assert _sessions[SID]["history"] == []  # ホストの指示を共有の履歴に入れない


@pytest.mark.parametrize("text,paused", [("no", False), ("boom", True), ("odd", True)])
def test_refusals_and_failures_are_409(table, text, paused):
    _sessions[SID]["ai_paused"] = False
    _sessions[SID].pop("plugin_error", None)
    with TestClient(app) as client:
        r = client.post(f"/api/session/{SID}/keeper", json={"text": text},
                        headers={"Authorization": f"Bearer {table['host']}"})
    assert r.status_code == 409
    assert _sessions[SID]["ai_paused"] is paused


def test_def_ai_turns_never_start_on_these_tables(table):
    from def_kari.api.routes.session_turn_engine import _ensure_ai_turns_running
    _ensure_ai_turns_running(SID, _sessions[SID], unpause=True, restart=True)
    assert _sessions[SID].get("ai_task") is None
    assert _sessions[SID]["ai_paused"] is True  # 停止の解除もしない（口が決める）
