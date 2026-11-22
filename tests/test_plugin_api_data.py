"""プラグインのデータを読む口と書き込みの置き場（B-006・B-007）、外部への送信の役（B-021）。

手順6の1（第2部の設計レビュー 2026-11-21 を受けた順番）。架空のルールシステムだけで確かめる（B-008）。
"""

import json
from unittest.mock import patch

import pytest

from def_kari.trpg import resources
from def_kari.trpg.plugin_storage import PluginStorage, StorageError
from def_kari.trpg.plugins import PluginApi


def _w(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


@pytest.fixture
def repo(monkeypatch, tmp_path):
    """単体型のリポジトリ: ルールブック1冊と、裁定の組の版 r1 のデータ。"""
    root = tmp_path / "grid_repo"
    _w(root / "manifest.json", {})
    _w(root / "rulebooks" / "gridbook.json", {"label": "g"})
    _w(root / "data" / "rulesets" / "r1" / "machines" / "m1.json", {"move": 5})
    _w(root / "data" / "rulesets" / "r1" / "machines" / "listy.json", "[1, 2]")
    _w(root / "data" / "rulesets" / "r1" / "scenarios" / "s1.json", {"title": "t"})
    _w(tmp_path / "outside.json", {"secret": True})
    monkeypatch.setenv("TRPG_RULEBOOK_REPO_PATHS", str(root))
    monkeypatch.setattr("def_kari.trpg.plugins.loaded_plugins", lambda: [])
    return root


# ── 読む口 ─────────────────────────────────────────────────────────

def test_load_data_reads_the_ruleset_folder_of_the_rulebook(repo):
    assert resources.load_data("gridbook", "r1", "machines", "m1") == {"move": 5}
    assert resources.load_data("gridbook", "r1", "scenarios", "s1") == {"title": "t"}
    assert PluginApi("grid_plugin").load_data("gridbook", "r1", "machines", "m1") == {"move": 5}


@pytest.mark.parametrize("args", [
    ("gridbook", "r1", "machines", "../outside"), ("gridbook", "r1", "machines", "a/b"),
    ("gridbook", "..", "machines", "m1"), ("gridbook", "r1/x", "machines", "m1"),
    ("gridbook", "r1", "", "m1"), ("../gridbook", "r1", "machines", "m1"),
    # 根の外には出ないが `/` を含む ID（ほかの守りでは止まらない。引数の確かめだけが止める）
    ("gridbook", "r1/../r1", "machines", "m1"), ("gridbook", "r1", "machines/../machines", "m1"),
])
def test_load_data_checks_every_argument(repo, args):
    assert resources.load_data(*args) == {}


def test_load_data_missing_or_not_an_object(repo):
    assert resources.load_data("gridbook", "r1", "machines", "nope") == {}
    assert resources.load_data("gridbook", "r2", "machines", "m1") == {}
    assert resources.load_data("gridbook", "r1", "machines", "listy") == {}
    assert resources.load_data("no_such_book", "r1", "machines", "m1") == {}


def test_load_data_does_not_follow_a_link_outside_the_repository(repo, tmp_path):
    link = repo / "data" / "rulesets" / "r1" / "machines" / "leak.json"
    try:
        link.symlink_to(tmp_path / "outside.json")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available")
    assert resources.load_data("gridbook", "r1", "machines", "leak") == {}


def test_flat_local_folders_have_no_data(monkeypatch, tmp_path):
    local = tmp_path / "public" / "trpg_rules"
    _w(local / "flat.json", {"label": "f"})
    monkeypatch.setattr(resources, "RULEBOOK_DIRS", [local])
    monkeypatch.setattr(resources, "_external_sources", lambda: [])
    assert resources.load_rulebook("flat") == {"label": "f"}
    assert resources.load_data("flat", "r1", "machines", "m1") == {}


# ── 書き込みの置き場 ──────────────────────────────────────────────────

def test_storage_writes_reads_and_keeps_the_previous_version():
    st = PluginStorage("grid_plugin")
    st.write_json("campaigns", "c1", data={"revision": 1})
    st.write_json("campaigns", "c1", data={"revision": 2})
    assert st.read_json("campaigns", "c1") == {"revision": 2}
    assert st.read_prev_json("campaigns", "c1") == {"revision": 1}
    st.write_json("campaigns", "c1", "s1", "archive", data={"done": True})
    assert st.read_json("campaigns", "c1", "s1", "archive") == {"done": True}
    assert st.list_ids("campaigns") == ["c1", "c1.s1.archive"]
    assert st.exists("campaigns", "c1") and not st.exists("campaigns", "c9")
    leftovers = [p.name for p in st._root().joinpath("campaigns").iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_storage_is_under_the_writable_private_folder():
    from def_kari.runtime_paths import writable_data_dir
    st = PluginStorage("grid_plugin")
    st.write_json("campaigns", "c2", data={})
    path = st._path("campaigns", ("c2",), ".json")
    assert path.is_relative_to((writable_data_dir() / "private" / "plugin_data" / "grid_plugin").resolve())


@pytest.mark.parametrize("kind,ids", [
    ("campaigns", ("../x",)), ("campaigns", ("a/b",)), ("../up", ("c1",)), ("campaigns", ()),
    ("campaigns", ("",)), ("campaigns", ("c1", "..")),
])
def test_storage_refuses_bad_ids(kind, ids):
    st = PluginStorage("grid_plugin")
    with pytest.raises(StorageError):
        st.write_json(kind, *ids, data={})
    with pytest.raises(StorageError):
        PluginStorage("../evil")


def test_storage_refuses_non_objects():
    st = PluginStorage("grid_plugin")
    with pytest.raises(StorageError):
        st.write_json("campaigns", "c3", data=[1, 2])
    with pytest.raises(StorageError):
        st.append_line("logs", "c3", record="text")


def test_lines_are_appended_and_a_broken_last_line_is_skipped():
    st = PluginStorage("grid_plugin")
    st.append_line("logs", "c4", record={"seq": 1})
    st.append_line("logs", "c4", record={"seq": 2})
    path = st._path("logs", ("c4",), ".jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"seq": 3, "text": "cut in the mid')  # 追記の途中で落ちた
    assert [r["seq"] for r in st.read_lines("logs", "c4")] == [1, 2]
    st2 = PluginStorage("grid_plugin")
    assert st2.read_lines("logs", "nothing") == []


def test_broken_json_reads_as_none_and_the_previous_version_remains():
    st = PluginStorage("grid_plugin")
    st.write_json("campaigns", "c5", data={"revision": 1})
    st.write_json("campaigns", "c5", data={"revision": 2})
    st._path("campaigns", ("c5",), ".json").write_text("{broken", encoding="utf-8")
    assert st.read_json("campaigns", "c5") is None
    assert st.read_prev_json("campaigns", "c5") == {"revision": 1}


def test_plugin_api_has_its_own_storage():
    api = PluginApi("grid_plugin")
    assert api.storage.plugin_id == "grid_plugin"
    assert PluginApi("other_plugin").storage._root() != api.storage._root()


# ── 外部への送信の役（B-021） ─────────────────────────────────────────

def _perms(rule_system):
    return {"external_services_allowed": True, "online_sessions": True, "missing": [], "credits": [],
            "rule_system": rule_system}


@pytest.mark.parametrize("rule_system,role,refused", [
    ("grid_system", None, True), ("grid_system", "unknown", True), ("grid_system", "gm", False),
    ("grid_system", "pc", False), ("def_original", None, False),
])
def test_plugin_tables_refuse_external_calls_without_a_known_role(rule_system, role, refused):
    from def_kari.llm import backend_guard as bg
    session = {"id": "s1", "trpg_rulebook": "book", "trpg_rule_system": rule_system}
    with patch.object(bg, "is_local", return_value=False), \
            patch("def_kari.trpg.resources.table_permissions", return_value=_perms(rule_system)):
        reason = bg.refusal(session, "llm", "some_cloud", role=role)
    assert (reason is not None) is refused
    if refused:
        assert "role" in reason


# ── 版（保存するファイルに残すため。S-209） ─────────────────────────────

def test_plugin_api_tells_the_versions():
    from def_kari import __version__
    api = PluginApi("grid_plugin", "1.2.3", 1)
    assert (api.plugin_version, api.plugin_api, api.def_version) == ("1.2.3", 1, __version__)


def test_loaded_plugin_gets_its_declared_version(monkeypatch):
    from pathlib import Path
    from def_kari.trpg import plugins
    seen = {}
    monkeypatch.setattr(plugins, "PluginApi", lambda *a: seen.setdefault("args", a) and PluginApi(*a))
    sample = Path(__file__).parent / "fixtures" / "plugins" / "sample_grid"
    plugins._reset_for_tests()
    try:
        plugins.load_plugin(sample, lambda s: None, lambda i: False)
    finally:
        plugins._reset_for_tests()
        import sys
        sys.modules.pop("def_trpg_plugin_sample_grid", None)
    assert seen["args"] == ("sample_grid", "0.1.0", 1, ["sample_grid"])


def test_a_line_appended_after_a_broken_last_line_is_kept():
    """追記の途中で落ちた後の次の行が、壊れた行とつながって失われない（S-371）。"""
    st = PluginStorage("grid_plugin")
    st.append_line("logs", "c6", record={"seq": 1})
    path = st._path("logs", ("c6",), ".jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write('{"seq": 2, "text": "cut in the mid')
    st.append_line("logs", "c6", record={"seq": 3})
    assert [r["seq"] for r in st.read_lines("logs", "c6")] == [1, 3]
