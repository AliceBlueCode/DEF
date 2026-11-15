"""クレジットの表示（マルチルールブック基盤 B-023）。

ルールブック・シナリオ・プラグインの manifest の `credit` を、ルールブックを選ぶ画面（`/api/trpg/rulebooks`・
`/api/trpg/scenarios`）とセッションの画面（`/api/session/{id}/credits`）に渡す。
"""

import json

import pytest

from def_kari.trpg import resources


@pytest.fixture
def repos(monkeypatch, tmp_path):
    """クレジットのあるルールブックのリポジトリと、シナリオのリポジトリ。"""
    rb = tmp_path / "rb_repo"
    (rb / "rulebooks").mkdir(parents=True)
    (rb / "manifest.json").write_text(json.dumps({"credit": "Rules (c) Sample Author"}), encoding="utf-8")
    (rb / "rulebooks" / "credited_book.json").write_text(json.dumps({"label": "Credited"}), encoding="utf-8")
    sc = tmp_path / "sc_repo"
    (sc / "scenarios").mkdir(parents=True)
    (sc / "manifest.json").write_text(json.dumps({"credit": "Scenario by Someone"}), encoding="utf-8")
    (sc / "scenarios" / "credited_sc.json").write_text(json.dumps({"title": "S"}), encoding="utf-8")
    monkeypatch.setenv("TRPG_RULEBOOK_REPO_PATHS", f"{rb};{sc}")
    monkeypatch.setattr("def_kari.trpg.plugins.loaded_plugins", lambda: [])


def test_table_credits_collects_each_source_once(repos):
    assert resources.table_credits("credited_book", "credited_sc") == ["Rules (c) Sample Author", "Scenario by Someone"]
    assert resources.table_credits("credited_book") == ["Rules (c) Sample Author"]
    assert resources.table_credits("", "") == []


def test_selection_lists_carry_credits(repos):
    from def_kari.api.routes import trpg as t
    books = {b["id"]: b for b in t.list_rulebooks()["rulebooks"]}
    assert books["credited_book"]["credits"] == ["Rules (c) Sample Author"]
    scs = {s["id"]: s for s in t.list_scenarios()["scenarios"]}
    assert scs["credited_sc"]["credits"] == ["Scenario by Someone"]


def test_selection_lists_say_whether_online_is_allowed(repos, monkeypatch, tmp_path):
    """B-022: 一覧に「オンラインの卓で使えるか」を出す（画面が「オンライン不可」と出し、作成を押せなくする）。"""
    from def_kari.api.routes import trpg as t
    closed = tmp_path / "closed_repo"
    (closed / "rulebooks").mkdir(parents=True)
    (closed / "scenarios").mkdir(parents=True)
    (closed / "manifest.json").write_text(json.dumps({"online_sessions": False}), encoding="utf-8")
    (closed / "rulebooks" / "closed_book.json").write_text(json.dumps({"label": "C"}), encoding="utf-8")
    (closed / "scenarios" / "closed_sc.json").write_text(json.dumps({"title": "C"}), encoding="utf-8")
    import os
    monkeypatch.setenv("TRPG_RULEBOOK_REPO_PATHS", os.environ["TRPG_RULEBOOK_REPO_PATHS"] + f";{closed}")
    books = {b["id"]: b for b in t.list_rulebooks()["rulebooks"]}
    assert books["closed_book"]["online_sessions"] is False
    assert books["credited_book"]["online_sessions"] is True  # 書いていなければ、def_original のルールブックは許す（B-020）
    scs = {s["id"]: s for s in t.list_scenarios()["scenarios"]}
    assert scs["closed_sc"]["online_sessions"] is False


def test_session_credits_endpoint(repos):
    from def_kari.api.routes.session_gameplay import get_session_credits
    from def_kari.api.routes.session_state import _sessions
    sid = "_credits"
    _sessions[sid] = {"id": sid, "trpg_mode": True, "trpg_rulebook": "credited_book", "trpg_scenario": "credited_sc",
                      "trpg_rule_system": "def_original", "trpg_plugin_version": ""}
    try:
        out = get_session_credits(sid, _auth={"role": "player"})
        assert out == {"credits": ["Rules (c) Sample Author", "Scenario by Someone"]}
        _sessions[sid].update(trpg_rulebook="", trpg_scenario="")
        assert get_session_credits(sid, _auth={"role": "player"}) == {"credits": []}
    finally:
        _sessions.pop(sid, None)
    assert get_session_credits("_no_such", _auth={}) == {"error": "Session not found"}
