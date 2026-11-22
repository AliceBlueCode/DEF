"""画面部品に渡すデータと操作（ui の口。差し込み口 11、B-052、基本設計書 11.5）。

手順6の5。架空のルールシステムのプラグインだけで確かめる（B-008）。
- 形の確かめ: 正しくない部品・要素だけを除き、何を除いたかを返す。
- GET /rule_ui: 相手ごと（口が決める）。問題はホストにだけ。口の失敗・トークンは部品を描かない。
- POST /rule_ui/action: 形の確かめ、相手は JWT から、口の返り値の確かめ。手番の関所を通る。
"""

import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from def_kari.api.main import app
from def_kari.api.routes.session_auth import issue_player_jwt
from def_kari.api.routes.session_state import _sessions
from def_kari.trpg import plugins, registry
from def_kari.trpg.ui_schema import STYLES, validate_ui_action, validate_ui_state

SAMPLE = Path(__file__).parent / "fixtures" / "plugins" / "sample_grid"


def _board(**over):
    b = {"type": "grid_board", "id": "map", "cols": 3, "rows": 2, "col_labels": ["A", "B", "C"],
         "row_labels": ["1", "2"], "terrains": {"plain": {"label": "Plain", "color": "#88aa66", "height": 0}},
         "cells": [{"pos": [0, 0], "terrain": "plain"}],
         "tokens": [{"id": "t1", "pos": [1, 1], "label": "Unit A", "side": "pc", "marks": ["primary"]}],
         "overlays": [{"cells": [[0, 0], [2, 1]], "style": "info", "label": "move"}],
         "lines": [{"from": [0, 0], "to": [2, 1], "style": "ok"}],
         "selectable": {"cells": [[0, 1]], "tokens": ["t1"]}}
    b.update(over)
    return b


# ── 形の確かめ ───────────────────────────────────────────

def test_a_good_state_passes_unchanged_in_meaning():
    state = {"ui_schema": 1, "title": "Round 2", "components": [
        _board(),
        {"type": "status_panel", "id": "st", "order": [{"label": "Unit A", "value": 14}],
         "groups": [{"title": "PCs", "rows": [{"label": "A", "items": [{"label": "HP", "value": 10, "max": 12}]}]}]},
        {"type": "check_log", "id": "log", "entries": [{"id": "e1", "text": "hit", "tags": ["hit"]}]},
        {"type": "approval", "id": "ap", "summary": ["move to B2"], "choices": [{"id": "ok", "label": "OK"}],
         "inputs": [{"id": "target", "label": "Target", "value": "B2"}]},
        {"type": "question", "id": "q", "prompt": "Which?", "choices": [{"id": "a", "label": "A"}], "free_text": True},
    ]}
    ui, problems = validate_ui_state(state)
    assert problems == []
    assert [c["type"] for c in ui["components"]] == ["grid_board", "status_panel", "check_log", "approval", "question"]
    board = ui["components"][0]
    assert board["tokens"][0]["pos"] == [1, 1] and board["selectable"] == {"cells": [[0, 1]], "tokens": ["t1"]}


@pytest.mark.parametrize("state", [None, [], {"ui_schema": 2, "components": []}, {"components": []}])
def test_unsupported_schema_draws_nothing(state):
    ui, problems = validate_ui_state(state)
    assert ui["components"] == [] and problems


def test_bad_components_are_left_out_and_others_stay():
    ui, problems = validate_ui_state({"ui_schema": 1, "components": [
        {"type": "script", "id": "x"}, {"type": "check_log"}, _board(cols=0),
        {"type": "check_log", "id": "log", "entries": []}, {"type": "check_log", "id": "log", "entries": []},
        {"type": "question", "id": "q"},
    ]})
    assert [c["id"] for c in ui["components"]] == ["log"]
    assert len(problems) == 5


@pytest.mark.parametrize("over,field,count", [
    ({"tokens": [{"id": "t1", "pos": [3, 0], "label": "x"}]}, "tokens", 0),          # 範囲外
    ({"tokens": [{"id": "t1", "pos": [0, 0], "label": "x", "marks": ["red"]}]}, "tokens", 0),  # 知らない印
    ({"lines": [{"from": [0, 0], "to": [0, 5], "style": "ok"}]}, "lines", 0),
    ({"lines": [{"from": [0, 0], "to": [1, 1], "style": "#ff0000"}]}, "lines", 0),     # 色そのものは不可
    ({"overlays": [{"cells": [[0, 0]], "style": "glow"}]}, "overlays", 0),
    ({"cells": [{"pos": [0, 0], "terrain": "lava"}]}, "cells", 0),                   # 知らない地形
    ({"terrains": {"plain": {"label": "P", "color": "red"}}, "cells": []}, "terrains", 0),
])
def test_bad_elements_are_left_out(over, field, count):
    ui, problems = validate_ui_state({"ui_schema": 1, "components": [_board(**over)]})
    assert len(ui["components"][0][field]) == count and problems


def test_overlay_keeps_cells_on_the_board_only():
    ui, problems = validate_ui_state({"ui_schema": 1, "components": [
        _board(overlays=[{"cells": [[0, 0], [9, 9], "x"], "style": "info"}])]})
    assert ui["components"][0]["overlays"][0]["cells"] == [[0, 0]] and problems


def test_text_is_kept_as_text():
    ui, _ = validate_ui_state({"ui_schema": 1, "components": [
        {"type": "check_log", "id": "log", "entries": [{"id": "e1", "text": "<img src=x onerror=alert(1)>"}]}]})
    assert ui["components"][0]["entries"][0]["text"] == "<img src=x onerror=alert(1)>"  # 画面が文字として描く


def test_styles_are_the_fixed_names():
    assert STYLES == {"primary", "secondary", "info", "ok", "blocked", "dimmed"}


@pytest.mark.parametrize("action,ok", [
    ({"component": "map", "action": "select", "data": {"pos": [0, 0]}, "base_revision": 3}, True),
    ({"component": "map", "action": "select"}, True),
    ({"component": "map", "action": "select", "data": [], "base_revision": 3}, False),
    ({"component": "map", "action": "select", "base_revision": "3"}, False),
    ({"component": "../x", "action": "select"}, False),
    ({"action": "select"}, False), ("text", False),
])
def test_action_shape(action, ok):
    assert (validate_ui_action(action) is not None) is ok


# ── API ─────────────────────────────────────────────────

_INIT = '''
class S:
    id = "sample_grid"
    capabilities = frozenset({"ui"})
    actions = []
    def validate_rulebook(self, d): return []
    def general_check(self, r, v, rb, **o): return {}
    def allowed_skills(self, rb): return frozenset()
    def dice_notation(self, rb): return "1d20"
    def build_rule_context(self, rb, sc, lang): return ""
    def ui_state(self, session, audience):
        mode = session.get("_ui")
        if mode == "boom":
            raise RuntimeError("broken plugin")
        if mode == "leak":
            return {"ui_schema": 1, "title": "T", "components": [
                {"type": "check_log", "id": "log", "entries": [{"id": "e1", "text": session["host_token"]}]}]}
        comps = [{"type": "check_log", "id": "log", "entries": [{"id": "e1", "text": "seen by " + audience["role"]}]},
                 {"type": "teleport", "id": "bad"}]
        return {"ui_schema": 1, "title": "T", "components": comps}
    def ui_action(self, session, audience, action):
        S.actions.append((audience, action))
        if action["action"] == "odd":
            return "yes"
        if action["action"] == "no":
            return {"accepted": False, "reason": "not now"}
        return {"accepted": True, "reason": ""}
def register(api):
    return S()
'''

SID = "_ui_table"


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
    system.actions.clear()
    host = issue_player_jwt(SID, "host")
    observer = issue_player_jwt(SID, "observer")
    _sessions[SID] = {"id": SID, "trpg_mode": True, "trpg_rulebook": "gb", "trpg_rule_system": "sample_grid",
                      "trpg_plugin_version": "0.1.0", "host_token": host, "players": {host: "", observer: ""},
                      "token_to_participant": {}, "history": []}
    yield {"system": system, "host": host, "observer": observer}
    _sessions.pop(SID, None)
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)
    registry._BUILTIN_LOADED = saved_loaded
    plugins._reset_for_tests()
    for name in [m for m in sys.modules if m.startswith("def_trpg_plugin_")]:
        sys.modules.pop(name, None)


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_get_rule_ui_is_per_audience_and_problems_go_to_the_host(table):
    with TestClient(app) as client:
        host = client.get(f"/api/session/{SID}/rule_ui", headers=_h(table["host"])).json()
        obs = client.get(f"/api/session/{SID}/rule_ui", headers=_h(table["observer"])).json()
        assert client.get(f"/api/session/{SID}", headers=_h(table["observer"])).json()["rule_ui"] is True
    assert host["ui"]["components"][0]["entries"][0]["text"] == "seen by host"
    assert obs["ui"]["components"][0]["entries"][0]["text"] == "seen by observer"
    assert len(host["problems"]) == 1 and obs["problems"] == []


@pytest.mark.parametrize("mode", ["boom", "leak"])
def test_get_rule_ui_falls_closed(table, mode):
    _sessions[SID]["_ui"] = mode
    with TestClient(app) as client:
        out = client.get(f"/api/session/{SID}/rule_ui", headers=_h(table["host"])).json()
    assert out["ui"]["components"] == [] and out["ui"]["title"] == ""
    assert _sessions[SID]["ai_paused"] is True


def test_tables_without_the_hook_have_no_rule_ui(table):
    _sessions[SID]["trpg_rule_system"] = "def_original"
    _sessions[SID]["trpg_plugin_version"] = ""
    with TestClient(app) as client:
        assert client.get(f"/api/session/{SID}/rule_ui", headers=_h(table["host"])).json() == {"ui": None, "problems": []}
        assert client.get(f"/api/session/{SID}", headers=_h(table["host"])).json()["rule_ui"] is False
        r = client.post(f"/api/session/{SID}/rule_ui/action", json={"component": "log", "action": "x"},
                        headers=_h(table["host"]))
        assert r.status_code == 409


def test_action_goes_to_the_hook_with_the_jwt_audience(table):
    with TestClient(app) as client:
        r = client.post(f"/api/session/{SID}/rule_ui/action",
                        json={"component": "ap", "action": "approve", "data": {"role": "host"}, "base_revision": 4},
                        headers=_h(table["observer"]))
    assert r.status_code == 200 and r.json() == {"accepted": True, "reason": ""}
    audience, action = table["system"].actions[-1]
    assert audience == {"role": "observer", "char_id": ""}  # 本文の role は使わない
    assert action == {"component": "ap", "action": "approve", "data": {"role": "host"}, "base_revision": 4}


@pytest.mark.parametrize("body,status", [
    ({"component": "ap", "action": "no"}, 409), ({"component": "ap", "action": "odd"}, 409),
    ({"component": "ap", "action": "x", "data": "text"}, 400), ({"action": "x"}, 400),
])
def test_action_refusals(table, body, status):
    with TestClient(app) as client:
        r = client.post(f"/api/session/{SID}/rule_ui/action", json=body, headers=_h(table["host"]))
    assert r.status_code == status
