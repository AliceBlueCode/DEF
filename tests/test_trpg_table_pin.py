"""実装再開メモ（外部のレビュー、2026-11-16）の指摘の修正を固定する。

- 自動保存の復元も `/load` と同じに、卓のピン（ルールシステムとプラグインの版）を確かめる。版が違えば断り、
  ピンの無い古い卓は今の環境で固定する（移行の扱い）。
- ループバックの判定は IP アドレスを解析して行う（`127.example.com` を手元とみなさない）。
- JSON のいちばん外側が object でないルールブック・シナリオは読まない。
- 空のリポジトリはログで知らせる。
"""

import json
import logging
import time
from unittest.mock import patch

import pytest

from def_kari.trpg import registry, resources


def _autosave_file(tmp_path, sid, **state):
    f = tmp_path / f"{sid}.json"
    f.write_text(json.dumps({"id": sid, "trpg_mode": True, "history": [], **state}), encoding="utf-8")
    return f


# ── ピン ─────────────────────────────────────────────────────────

def test_autosave_with_a_changed_plugin_version_is_not_restored(tmp_path):
    """C-002: 版が変わった卓は、自動保存から戻さない（以前は戻し、遊び始めた最初の呼び出しで止まっていた）。"""
    from def_kari.api.routes import session_persistence as sp
    from def_kari.api.routes.session_state import _sessions
    f = _autosave_file(tmp_path, "_pin_changed", trpg_rulebook="def_original",
                       trpg_rule_system="def_original", trpg_plugin_version="9.9.9")
    sp._restore_one_autosave_file(f, time.time())
    assert "_pin_changed" not in _sessions
    assert f.exists()


def test_autosave_without_a_pin_is_migrated_and_saved(tmp_path):
    """v5.0.0 より前の卓（ピンが無い）は、今の環境で固定して戻し、すぐ保存し直す。"""
    from def_kari.api.routes import session_persistence as sp
    from def_kari.api.routes.session_state import _sessions
    f = _autosave_file(tmp_path, "_pin_old", trpg_rulebook="def_original")
    try:
        with patch.object(sp, "_autosave") as save:
            sp._restore_one_autosave_file(f, time.time())
        assert _sessions["_pin_old"]["trpg_rule_system"] == "def_original"
        assert _sessions["_pin_old"]["trpg_plugin_version"] == ""
        save.assert_called_once_with("_pin_old")
    finally:
        _sessions.pop("_pin_old", None)


def test_load_uses_the_same_check(monkeypatch, tmp_path):
    from def_kari.api.routes import session_persistence as sp
    monkeypatch.setattr(sp, "_SESSION_HISTORY_DIRS", [tmp_path])
    (tmp_path / "changed.json").write_text(json.dumps({"metadata": {
        "trpg_rulebook": "def_original", "trpg_rule_system": "def_original", "trpg_plugin_version": "9.9.9"},
        "history": []}), encoding="utf-8")
    assert "changed from 9.9.9" in sp.load_session(sp.SessionLoadRequest(filename="changed.json"))["error"]
    assert sp._table_pin({"trpg_rulebook": "def_original"})[:4] == ("def_original", "", None, True)
    assert sp._table_pin({}) == ("", "", None, False)


# ── ループバック ───────────────────────────────────────────────────

@pytest.mark.parametrize("host,local", [
    ("127.0.0.1", True), ("127.0.0.2", True), ("localhost", True), ("LOCALHOST", True), ("::1", True),
    ("[::1]", True),
    ("127.example.com", False), ("127.0.0.1.example.com", False), ("localhost.example.com", False),
    ("0.0.0.0", False), ("192.168.1.2", False), ("", False), ("not a host", False),
])
def test_loopback_is_parsed_not_prefix_matched(host, local):
    from def_kari.llm.backend_guard import _is_loopback_host
    assert _is_loopback_host(host) is local


def test_backend_pointing_to_a_127_hostname_is_external(monkeypatch):
    """C-002: 以前は `127.` で始まるホスト名を手元とみなし、外部への送信を禁じた卓の中身を外へ送りえた。"""
    from def_kari.llm import backend_guard as bg
    monkeypatch.setenv("TEXTGEN_WEBUI_URL", "http://127.example.com:5000/v1")
    with patch("def_kari.compatible_backends_store.has_backend", return_value=False):
        assert bg.is_local("llm", "textgen_webui") is False
    monkeypatch.setenv("TEXTGEN_WEBUI_URL", "http://127.0.0.1:5000/v1")
    with patch("def_kari.compatible_backends_store.has_backend", return_value=False):
        assert bg.is_local("llm", "textgen_webui") is True


# ── JSON の形 ────────────────────────────────────────────────────

def test_non_object_json_is_not_a_rulebook(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    (repo / "rulebooks").mkdir(parents=True)
    (repo / "scenarios").mkdir(parents=True)
    (repo / "manifest.json").write_text("{}", encoding="utf-8")
    (repo / "rulebooks" / "listy.json").write_text("[1, 2]", encoding="utf-8")
    (repo / "rulebooks" / "stringy.json").write_text('"text"', encoding="utf-8")
    (repo / "rulebooks" / "good.json").write_text(json.dumps({"label": "g"}), encoding="utf-8")
    (repo / "scenarios" / "listy_sc.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("TRPG_RULEBOOK_REPO_PATHS", str(repo))
    assert resources.load_rulebook("listy") == {} and resources.load_rulebook("stringy") == {}
    assert resources.load_rulebook("good") == {"label": "g"}
    ids = {rid for rid, _, _ in resources.rulebook_listing()}
    assert "good" in ids and not ids & {"listy", "stringy"}
    assert "listy_sc" not in {sid for sid, _, _ in resources.scenario_listing()}
    assert registry.is_known([]) is False and registry.is_known("x") is False and registry.is_known({}) is True


# ── 空のリポジトリ ─────────────────────────────────────────────────

def test_empty_repository_is_reported_once(monkeypatch, tmp_path, caplog):
    empty = tmp_path / "empty_repo"
    empty.mkdir()
    monkeypatch.setenv("TRPG_RULEBOOK_REPO_PATHS", str(empty))
    monkeypatch.setattr(resources, "_EMPTY_REPO_WARNED", set())
    with caplog.at_level(logging.WARNING, logger="def.trpg"):
        resources.sources()
        resources.sources()
    assert sum("no rulebook folders found" in r.message for r in caplog.records) == 1
