"""保存と再開をルールシステムが受け持つ卓（persistence の口。差し込み口 F9・10、要求仕様 S-309〜S-312）。

手順6の3。架空のルールシステムのプラグインだけで確かめる（B-008）。
"""

import json
import shutil
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from def_kari.api.main import app
from def_kari.api.routes import session_persistence as sp
from def_kari.api.routes.session_state import _sessions
from def_kari.trpg import plugins, registry, resources

SAMPLE = Path(__file__).parent / "fixtures" / "plugins" / "sample_grid"


@pytest.fixture
def fresh_registry(monkeypatch):
    """レジストリとプラグインの状態を空にし、テストの後で元に戻す（test_trpg_plugins.py と同じ）。"""
    saved = dict(registry._REGISTRY)
    saved_loaded = registry._BUILTIN_LOADED
    registry._REGISTRY.clear()
    registry._BUILTIN_LOADED = False
    plugins._reset_for_tests()
    monkeypatch.delenv("TRPG_PLUGIN_PATHS", raising=False)
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)
    registry._BUILTIN_LOADED = saved_loaded
    plugins._reset_for_tests()
    for name in [m for m in sys.modules if m.startswith("def_trpg_plugin_")]:
        sys.modules.pop(name, None)


def _copy_plugin(tmp_path, init) -> Path:
    dst = tmp_path / "sample_grid"
    shutil.copytree(SAMPLE, dst)
    (dst / "sample_grid_plugin" / "__init__.py").write_text(init, encoding="utf-8")
    return dst


def _use(monkeypatch, path):
    monkeypatch.setenv("TRPG_PLUGIN_PATHS", str(path))
    registry.load_all()

_PERSISTENCE_INIT = '''
class S:
    id = "sample_grid"
    capabilities = frozenset({"persistence"})
    def validate_rulebook(self, d): return []
    def general_check(self, r, v, rb, **o): return {}
    def allowed_skills(self, rb): return frozenset()
    def dice_notation(self, rb): return "1d20"
    def build_rule_context(self, rb, sc, lang): return ""
    # 続きものが有る（c1・c2）ときだけ卓を作る
    def check_create(self, req):
        if req.get("campaign_id") in ("c1", "c2"):
            return ""
        if req.get("campaign_id") == "boom":
            raise RuntimeError("broken plugin")
        if req.get("campaign_id") == "falsy":
            return False
        if req.get("campaign_id") == "zero":
            return 0
        if not req.get("campaign_id") and req.get("trpg_scenario") == "free":
            return None  # キャンペーン無しで作れる場合（口の約束としてはありうる）
        return "choose a campaign"
    def uses_def_autosave(self, session): return False
    def list_campaigns(self, rulebook_id):
        return [{"id": "c1", "title": "First"}, {"id": "../x", "title": "bad"}, "not a dict", {"id": "c2"}]
def register(api):
    return S()
'''


@pytest.fixture
def books(fresh_registry, monkeypatch, tmp_path):
    _use(monkeypatch, _copy_plugin(tmp_path, _PERSISTENCE_INIT))
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "gb.json").write_text(json.dumps({"rule_system": "sample_grid"}), encoding="utf-8")
    (rules / "plain.json").write_text(json.dumps({"label": "plain"}), encoding="utf-8")
    monkeypatch.setattr(resources, "RULEBOOK_DIRS", [rules])
    monkeypatch.setattr(resources, "_external_sources", lambda: [])
    # ロビーはオンラインの卓にだけある。ここではオンラインの許可（B-022）は確かめない
    monkeypatch.setattr(resources, "online_refusal", lambda *a, **k: None)
    assert registry.get("sample_grid") is not None
    started = []
    yield started
    for sid in started:
        _sessions.pop(sid, None)


def _start(client, started, rulebook, campaign_id="", online=False):
    r = client.post("/api/session/start", json={
        "character_ids": [], "trpg_mode": True, "trpg_rulebook": rulebook,
        "campaign_id": campaign_id, "online_mode": online})
    if r.status_code == 200:
        started.append(r.json()["session_id"])
    return r


# ── 卓の作成（F9） ─────────────────────────────────────────────

def test_campaign_table_is_created_and_marked(books):
    with TestClient(app) as client:
        r = _start(client, books, "gb", "c1")
        assert r.status_code == 200, r.text
        assert _sessions[r.json()["session_id"]]["campaign_id"] == "c1"


def test_rule_system_decides_whether_a_table_can_be_created(books):
    with TestClient(app) as client:
        r = _start(client, books, "gb")
        assert r.status_code == 400 and "choose a campaign" in r.text
        assert _start(client, books, "gb", "c9").status_code == 400
    assert not books


def test_failing_check_create_refuses_the_table(books):
    with TestClient(app) as client:
        r = _start(client, books, "gb", "boom")
        assert r.status_code == 400 and "plugin_error" in r.text
    assert not books


def test_campaign_id_needs_a_rule_system_that_keeps_campaigns(books):
    with TestClient(app) as client:
        assert _start(client, books, "plain", "c1").status_code == 400
        r = client.post("/api/session/start", json={"character_ids": [], "campaign_id": "c1"})
        assert r.status_code == 400
        assert _start(client, books, "plain").status_code == 200  # 口の無い卓は今までどおり


def test_campaign_id_is_checked(books):
    with TestClient(app) as client:
        assert _start(client, books, "gb", "../c1").status_code == 400


def test_one_table_per_campaign(books):
    with TestClient(app) as client:
        assert _start(client, books, "gb", "c1").status_code == 200
        assert _start(client, books, "gb", "c1").status_code == 409
        assert _start(client, books, "gb", "c2").status_code == 200


# ── ロビー（S-312） ─────────────────────────────────────────────

def _patch(client, body, sid, host):
    return client.patch(f"/api/session/{sid}/lobby/settings", json=body,
                        headers={"Authorization": f"Bearer {host}"})


def test_lobby_cannot_change_the_rulebook_or_scenario_of_a_campaign_table(books):
    with TestClient(app) as client:
        body = _start(client, books, "gb", "c1", online=True).json()
        sid, host = body["session_id"], body["host_token"]
        r = _patch(client, {"trpg_rulebook": "plain", "topic": "t"}, sid, host)
        assert r.status_code == 409
        assert _sessions[sid]["trpg_rulebook"] == "gb" and _sessions[sid].get("topic", "") != "t"
        assert _patch(client, {"trpg_scenario": "other"}, sid, host).status_code == 409
        assert _patch(client, {"trpg_rulebook": "gb", "topic": "t"}, sid, host).status_code == 200  # 同じ値は可


def test_lobby_cannot_switch_to_a_rulebook_that_keeps_campaigns(books):
    with TestClient(app) as client:
        body = _start(client, books, "plain", online=True).json()
        sid, host = body["session_id"], body["host_token"]
        assert _patch(client, {"trpg_rulebook": "gb"}, sid, host).status_code == 409
        assert _sessions[sid]["trpg_rulebook"] == "plain"


# ── 自動保存と /load（差し込み口 10、S-310） ─────────────────────────

def test_autosave_skips_campaign_tables_and_tables_the_rule_system_keeps(books, monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "_AUTOSAVE_DIR", tmp_path / "autosave")
    with TestClient(app) as client:
        camp = _start(client, books, "gb", "c1").json()["session_id"]
        plain = _start(client, books, "plain").json()["session_id"]
    sp._autosave(camp)
    sp._autosave(plain)
    assert not (tmp_path / "autosave" / f"{camp}.json").exists()
    assert (tmp_path / "autosave" / f"{plain}.json").exists()  # 口の無い卓は今までどおり
    # 口が「載せない」と決めた卓（campaign_id が無くても）
    assert sp._uses_def_autosave({"trpg_rulebook": "gb", "trpg_rule_system": "sample_grid",
                                  "trpg_plugin_version": "0.1.0"}) is False


def test_campaign_table_is_not_restored_from_autosave(books, tmp_path):
    f = tmp_path / "x.json"
    f.write_text(json.dumps({"id": "_camp_restore", "trpg_rulebook": "gb", "campaign_id": "c1", "history": []}),
                 encoding="utf-8")
    sp._restore_one_autosave_file(f, time.time())
    assert "_camp_restore" not in _sessions
    assert f.exists()


def test_load_refuses_a_campaign_table(books, monkeypatch, tmp_path):
    monkeypatch.setattr(sp, "_SESSION_HISTORY_DIRS", [tmp_path])
    (tmp_path / "camp.json").write_text(json.dumps({
        "metadata": {"trpg_mode": True, "trpg_rulebook": "gb", "campaign_id": "c1"}, "history": []}),
        encoding="utf-8")
    out = sp.load_session(sp.SessionLoadRequest(filename="camp.json"))
    assert "campaign" in out.get("error", "")


def test_save_records_the_campaign_id(books, monkeypatch):
    saved = {}
    monkeypatch.setattr(sp, "save_session_mode", lambda **kw: saved.update(kw))
    with TestClient(app) as client:
        body = _start(client, books, "gb", "c1").json()
        r = client.post(f"/api/session/{body['session_id']}/save", json={},
                        headers={"Authorization": f"Bearer {body['host_token']}"})
        assert r.status_code == 200, r.text
    assert saved["metadata"]["campaign_id"] == "c1"


# ── 再開できるキャンペーンの一覧 ────────────────────────────────────

def test_campaign_listing_comes_from_the_rule_system(books):
    with TestClient(app) as client:
        assert client.get("/api/trpg/rulebooks/gb/campaigns").json() == {
            "campaigns": [{"id": "c1", "title": "First"}, {"id": "c2", "title": "c2"}], "uses_campaigns": True}
        assert client.get("/api/trpg/rulebooks/plain/campaigns").json() == {"campaigns": [], "uses_campaigns": False}
        assert client.get("/api/trpg/rulebooks/no_such/campaigns").json() == {"campaigns": [], "uses_campaigns": False}


# ── レビュー 2026-11-22 の🟡1〜🟡4 ─────────────────────────────────

@pytest.mark.parametrize("cid", ["falsy", "zero"])
def test_check_create_values_outside_the_contract_refuse(books, cid):
    """🟡3: 作ってよいのは None と空文字だけ。False や 0 は作らない側。"""
    with TestClient(app) as client:
        r = _start(client, books, "gb", cid)
        assert r.status_code == 400 and "plugin_error" in r.text


def test_two_starts_at_once_open_one_table(books):
    """🟡1: 確かめと入れるの間に check_create が挟まっても、同じキャンペーンの卓は1つ。"""
    import threading
    system = registry.get("sample_grid")
    original = system.check_create
    both_inside = threading.Barrier(2, timeout=5)

    def slow_check(req):
        try:
            both_inside.wait()  # 2本とも口の中にいる状態を作る
        except threading.BrokenBarrierError:
            pass
        return original(req)
    system.check_create = slow_check
    codes = []
    try:
        with TestClient(app) as client:
            def run():
                codes.append(_start(client, books, "gb", "c1").status_code)
            threads = [threading.Thread(target=run) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)
    finally:
        del system.check_create
    assert sorted(codes) == [200, 409]
    assert sum(1 for s in _sessions.values() if s.get("campaign_id") == "c1") == 1
    from def_kari.api.routes import session_lobby
    assert session_lobby._opening_campaigns == set()


def test_a_refused_start_does_not_evict_another_table(books, monkeypatch):
    """🟡2: 卓の数が上限のときに断られる /start は、ほかの卓を追い出さない。"""
    from def_kari.api.routes import session_lobby
    evicted = []
    monkeypatch.setattr(session_lobby, "_MAX_SESSIONS", 0)
    monkeypatch.setattr(session_lobby, "_evict_oldest_session", lambda: evicted.append(1))
    with TestClient(app) as client:
        assert _start(client, books, "gb", "c9").status_code == 400
        assert _start(client, books, "gb", "../x").status_code == 400
        assert evicted == []
        assert _start(client, books, "gb", "c1").status_code == 200
        assert evicted == [1]
    assert session_lobby._opening_campaigns == set()


def test_lobby_cannot_change_the_scenario_of_a_persistence_table_without_a_campaign(books):
    """🟡4: campaign_id の無い persistence の卓でも、シナリオを変えて check_create を避けられない。"""
    with TestClient(app) as client:
        r = client.post("/api/session/start", json={
            "character_ids": [], "trpg_mode": True, "trpg_rulebook": "gb", "trpg_scenario": "free",
            "online_mode": True})
        assert r.status_code == 200, r.text
        body = r.json()
        books.append(body["session_id"])
        assert _patch(client, {"trpg_scenario": "other"}, body["session_id"], body["host_token"]).status_code == 409
        assert _sessions[body["session_id"]]["trpg_scenario"] == "free"


def test_load_refuses_tables_whose_rule_system_keeps_its_saves(books, monkeypatch, tmp_path):
    """🟡4: campaign_id の印が無くても、persistence の卓の手動の保存は /load で戻さない。"""
    monkeypatch.setattr(sp, "_SESSION_HISTORY_DIRS", [tmp_path])
    (tmp_path / "p.json").write_text(json.dumps({
        "metadata": {"trpg_mode": True, "trpg_rulebook": "gb", "trpg_rule_system": "sample_grid",
                     "trpg_plugin_version": "0.1.0"}, "history": []}), encoding="utf-8")
    out = sp.load_session(sp.SessionLoadRequest(filename="p.json"))
    assert "keeps its own saves" in out.get("error", "")
    (tmp_path / "plain.json").write_text(json.dumps({
        "metadata": {"trpg_mode": True, "trpg_rulebook": "plain"}, "history": []}), encoding="utf-8")
    out = sp.load_session(sp.SessionLoadRequest(filename="plain.json"))
    assert "session_id" in out, out  # 口の無い卓は今までどおり
    _sessions.pop(out["session_id"], None)
