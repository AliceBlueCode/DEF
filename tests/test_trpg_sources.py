"""ルールブックとシナリオの置き場所（B-011、B-029）と manifest・卓の許可（B-020）のテスト。

置き場所の順: プラグインのデータ → ルールブックのリポジトリ（単体型・集約型）→ data/public → data/private。
"""

import json
import logging
import shutil
import sys
from pathlib import Path

import pytest

from def_kari.api.routes import trpg as t
from def_kari.trpg import plugins, registry, resources

SAMPLE_PLUGIN = Path(__file__).parent / "fixtures" / "plugins" / "sample_grid"


def _w(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def local(monkeypatch, tmp_path):
    """data/public と data/private の代わり。外部の置き場所は、テストごとに環境変数で足す。"""
    pub, priv = tmp_path / "local" / "public", tmp_path / "local" / "private"
    for base in (pub, priv):
        (base / "trpg_rules").mkdir(parents=True)
        (base / "trpg_scenarios").mkdir(parents=True)
    monkeypatch.setattr(resources, "RULEBOOK_DIRS", [pub / "trpg_rules", priv / "trpg_rules"])
    monkeypatch.setattr(resources, "PUBLIC_RULEBOOK_DIRS", [pub / "trpg_rules"])
    monkeypatch.setattr(resources, "SCENARIO_DIRS", [pub / "trpg_scenarios", priv / "trpg_scenarios"])
    monkeypatch.setattr(resources, "PUBLIC_SCENARIO_DIRS", [pub / "trpg_scenarios"])
    monkeypatch.delenv("TRPG_RULEBOOK_REPO_PATHS", raising=False)
    return pub, priv


@pytest.fixture
def no_plugins(monkeypatch):
    monkeypatch.setattr(plugins, "loaded_plugins", lambda: [])


def _repos(monkeypatch, *paths):
    monkeypatch.setenv("TRPG_RULEBOOK_REPO_PATHS", ";".join(str(p) for p in paths))


# ── リポジトリの形と順番 ──────────────────────────────────────────

def test_single_repo(local, no_plugins, monkeypatch, tmp_path):
    repo = tmp_path / "single"
    _w(repo / "manifest.json", {"id": "single", "credit": "C"})
    _w(repo / "rulebooks" / "rb1.json", {"label": "from repo"})
    _w(repo / "scenarios" / "sc1.json", {"title": "repo scenario"})
    _repos(monkeypatch, repo)
    assert resources.load_rulebook("rb1") == {"label": "from repo"}
    assert resources.load_scenario("sc1") == {"title": "repo scenario"}
    assert [b["id"] for b in t.list_rulebooks()["rulebooks"]] == ["rb1"]
    assert resources.rulebook_source("rb1").manifest["credit"] == "C"


def test_aggregate_repo(local, no_plugins, monkeypatch, tmp_path):
    repo = tmp_path / "agg"
    _w(repo / "a" / "manifest.json", {"id": "a"})
    _w(repo / "a" / "rulebooks" / "rb_a.json", {"label": "A"})
    _w(repo / "b" / "rulebooks" / "rb_b.json", {"label": "B"})  # manifest の無いまとまり
    _w(repo / "bad name" / "rulebooks" / "rb_x.json", {"label": "X"})  # ID にならない名前は読まない
    _repos(monkeypatch, repo)
    assert sorted(b["id"] for b in t.list_rulebooks()["rulebooks"]) == ["rb_a", "rb_b"]
    assert resources.rulebook_source("rb_b").manifest is None


def test_order_and_duplicate_warning(local, no_plugins, monkeypatch, tmp_path, caplog):
    pub, priv = local
    repo = tmp_path / "single"
    _w(repo / "manifest.json", {})
    _w(repo / "rulebooks" / "dup.json", {"label": "repo"})
    _w(pub / "trpg_rules" / "dup.json", {"label": "public"})
    _w(priv / "trpg_rules" / "dup.json", {"label": "private"})
    _repos(monkeypatch, repo)
    with caplog.at_level(logging.WARNING, logger="def.trpg"):
        listed = t.list_rulebooks()["rulebooks"]
    assert [b["label"] for b in listed] == ["repo"]
    assert resources.load_rulebook("dup") == {"label": "repo"}
    assert sum("dup is also in" in r.message for r in caplog.records) == 2


def test_missing_repo_folder_is_ignored(local, no_plugins, monkeypatch, tmp_path):
    _repos(monkeypatch, tmp_path / "nowhere")
    assert t.list_rulebooks() == {"rulebooks": []}


def test_public_only_reads_only_external_sources_that_allow_online(local, no_plugins, monkeypatch, tmp_path):
    """オンラインの卓・公開のポートでは、manifest で online_sessions をはっきり許した外部のまとまりだけを
    読む（B-013）。manifest の無いまとまりは読まない。"""
    yes, no = tmp_path / "yes", tmp_path / "no"
    _w(yes / "manifest.json", {"online_sessions": True})
    _w(yes / "rulebooks" / "rb_yes.json", {"label": "yes"})
    _w(no / "rulebooks" / "rb_no.json", {"label": "no"})
    _repos(monkeypatch, yes, no)
    assert resources.load_rulebook("rb_yes", public_only=True) == {"label": "yes"}
    assert resources.load_rulebook("rb_no", public_only=True) == {}
    assert resources.load_rulebook("rb_no") == {"label": "no"}


def test_id_is_the_file_name(local, no_plugins, caplog):
    pub, _ = local
    _w(pub / "trpg_rules" / "foo.json", {"id": "bar"})
    with caplog.at_level(logging.WARNING, logger="def.trpg"):
        assert list(resources.all_rulebooks()) == ["foo"]
    assert any("differs from the file name" in r.message for r in caplog.records)


def test_external_rulebook_is_not_saved_here(local, no_plugins, monkeypatch, tmp_path):
    repo = tmp_path / "single"
    _w(repo / "manifest.json", {})
    _w(repo / "rulebooks" / "rb1.json", {"label": "from repo"})
    _repos(monkeypatch, repo)
    content = json.dumps({"rule_system_name": "x", "dice_system": "1d6",
                          "judgment": {"success_condition": "roll_lte_skill"}})
    out = t.save_rulebook("rb1", t.SaveRulebookRequest(content=content))
    assert "edit it there" in out["error"]
    assert json.loads((repo / "rulebooks" / "rb1.json").read_text(encoding="utf-8")) == {"label": "from repo"}


# ── manifest と卓の許可（B-020） ────────────────────────────────────

@pytest.mark.parametrize("manifest,expected", [
    (None, {"external_services_allowed": True, "online_sessions": True}),       # def_original で manifest なし
    ({"external_services_allowed": False}, {"external_services_allowed": False, "online_sessions": True}),
    ({"online_sessions": "yes"}, {"external_services_allowed": False, "online_sessions": False}),  # 型が違う＝壊れている
])
def test_def_original_permissions(local, no_plugins, monkeypatch, tmp_path, manifest, expected):
    repo = tmp_path / "single"
    (repo / "rulebooks").mkdir(parents=True)
    if manifest is not None:
        _w(repo / "manifest.json", manifest)
    _w(repo / "rulebooks" / "rb1.json", {"label": "x"})
    _repos(monkeypatch, repo)
    got = resources.table_permissions("rb1")
    assert {k: got[k] for k in expected} == expected


def test_every_part_must_allow(local, no_plugins, monkeypatch, tmp_path):
    """ルールブックが許しても、シナリオの manifest が許さなければ許さない。"""
    a, b = tmp_path / "a", tmp_path / "b"
    _w(a / "manifest.json", {"external_services_allowed": True, "credit": "Rulebook credit"})
    _w(a / "rulebooks" / "rb1.json", {"label": "x"})
    _w(b / "manifest.json", {"external_services_allowed": False, "credit": "Scenario credit"})
    _w(b / "scenarios" / "sc1.json", {"title": "y"})
    _repos(monkeypatch, a, b)
    got = resources.table_permissions("rb1", "sc1")
    assert got["external_services_allowed"] is False
    assert got["credits"] == ["Rulebook credit", "Scenario credit"]


@pytest.fixture
def grid_plugin(monkeypatch, tmp_path, local):
    """sample_grid のプラグインに、データ（ルールブック）と manifest を持たせて読み込む。"""
    saved = dict(registry._REGISTRY)
    saved_loaded = registry._BUILTIN_LOADED
    registry._REGISTRY.clear()
    registry._BUILTIN_LOADED = False
    plugins._reset_for_tests()
    dst = tmp_path / "grid_plugin"
    shutil.copytree(SAMPLE_PLUGIN, dst)
    _w(dst / "rulebooks" / "grid_book.json", {"rule_system": "sample_grid", "rule_system_name": "Grid"})
    monkeypatch.setenv("TRPG_PLUGIN_PATHS", str(dst))
    registry.load_all()
    yield dst
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)
    registry._BUILTIN_LOADED = saved_loaded
    plugins._reset_for_tests()
    for name in [m for m in sys.modules if m.startswith("def_trpg_plugin_")]:
        sys.modules.pop(name, None)


def test_plugin_data_comes_first_and_cannot_be_overridden(grid_plugin, monkeypatch, tmp_path):
    repo = tmp_path / "fan_repo"
    _w(repo / "manifest.json", {"external_services_allowed": True, "online_sessions": True})
    _w(repo / "rulebooks" / "grid_book.json", {"rule_system": "sample_grid", "rule_system_name": "Fake"})
    _repos(monkeypatch, repo)
    assert resources.load_rulebook("grid_book")["rule_system_name"] == "Grid"
    assert resources.rulebook_source("grid_book").kind == "plugin"


def test_plugin_rule_system_without_manifest_is_strict(grid_plugin):
    got = resources.table_permissions("grid_book")
    assert (got["external_services_allowed"], got["online_sessions"]) == (False, False)


def test_fan_rulebook_cannot_unlock_a_plugin_rule_system(grid_plugin, monkeypatch, tmp_path):
    """ほかの出どころのルールブックがプラグインのルールを名乗り、すべてを許す manifest を付けていても、
    プラグインの manifest が許さなければ許さない（基本設計書 11.2）。"""
    repo = tmp_path / "fan_repo"
    _w(repo / "manifest.json", {"external_services_allowed": True, "online_sessions": True})
    _w(repo / "rulebooks" / "fan_book.json", {"rule_system": "sample_grid", "rule_system_name": "Fan"})
    _repos(monkeypatch, repo)
    got = resources.table_permissions("fan_book")
    assert (got["external_services_allowed"], got["online_sessions"]) == (False, False)


def test_plugin_manifest_can_allow(grid_plugin):
    _w(grid_plugin / "manifest.json", {"external_services_allowed": True, "online_sessions": False})
    got = resources.table_permissions("grid_book")
    assert (got["external_services_allowed"], got["online_sessions"]) == (True, False)


# ── オンラインの卓（B-022）: 作成・ロビーの設定・参加で確かめる ───────────────

from fastapi.testclient import TestClient  # noqa: E402

from def_kari.api.main import app  # noqa: E402
from def_kari.api.routes.session_state import _sessions  # noqa: E402


@pytest.fixture
def online_books(local, no_plugins, monkeypatch, tmp_path):
    """オンラインを許すルールブック（ok_book）と、許さないルールブック（closed_book）。"""
    ok, closed = tmp_path / "ok", tmp_path / "closed"
    _w(ok / "manifest.json", {"online_sessions": True})
    _w(ok / "rulebooks" / "ok_book.json", {"rule_system_name": "x", "dice_system": "1d100",
                                            "judgment": {"success_condition": "roll_lte_skill"}})
    _w(closed / "manifest.json", {"online_sessions": False})
    _w(closed / "rulebooks" / "closed_book.json", {"rule_system_name": "y", "dice_system": "1d100",
                                                    "judgment": {"success_condition": "roll_lte_skill"}})
    _repos(monkeypatch, ok, closed)


def test_online_refusal(online_books):
    assert resources.online_refusal("ok_book") is None
    assert "cannot be used in online sessions" in resources.online_refusal("closed_book")
    assert resources.online_refusal("", "") is None


def _start(client, rulebook):
    return client.post("/api/session/start", json={
        "character_ids": [], "online_mode": True, "trpg_mode": True, "trpg_rulebook": rulebook})


def test_online_start_is_refused_for_a_closed_rulebook(online_books):
    with TestClient(app) as client:
        r = _start(client, "closed_book")
        assert r.status_code == 403
        ok = _start(client, "ok_book")
        assert ok.status_code == 200
        _sessions.pop(ok.json()["session_id"], None)


def test_lobby_settings_cannot_switch_to_a_closed_rulebook(online_books):
    with TestClient(app) as client:
        body = _start(client, "ok_book").json()
        sid, host = body["session_id"], body["host_token"]
        try:
            r = client.patch(f"/api/session/{sid}/lobby/settings", json={"trpg_rulebook": "closed_book", "topic": "t"},
                             headers={"Authorization": f"Bearer {host}"})
            assert r.status_code == 403
            assert _sessions[sid]["trpg_rulebook"] == "ok_book"
            assert _sessions[sid].get("topic", "") != "t"  # 途中まで変わった状態を残さない
        finally:
            _sessions.pop(sid, None)


def test_join_is_refused_when_the_rulebook_no_longer_allows_online(online_books, tmp_path):
    with TestClient(app) as client:
        body = _start(client, "ok_book").json()
        sid, code = body["session_id"], body["invite_code"]
        try:
            _w(tmp_path / "ok" / "manifest.json", {"online_sessions": False})  # 作った後に manifest が変わった
            r = client.post("/api/session/join", json={"invite_code": code})
            assert r.status_code == 403
        finally:
            _sessions.pop(sid, None)


# ── フォルダのリンクで、まとまりの外を読まない（B-012。実装レビューの🔴1） ──────────
# `rulebooks/` そのものが外を指すリンクだと、以前は外のフォルダ全体が「内側」になっていた。
# Windows のジャンクションは権限なしで作れるので、Windows ではジャンクション、ほかではシンボリックリンクで確かめる。

import os  # noqa: E402
import subprocess  # noqa: E402


def _dir_link(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        if r.returncode == 0:
            return
    pytest.skip("directory links are not available here")


@pytest.fixture
def secret_outside(tmp_path):
    secret = tmp_path / "outside_private"
    _w(secret / "secret.json", {"label": "SECRET"})
    return secret


def _assert_not_readable(rid="secret"):
    assert resources.load_rulebook(rid) == {}
    assert resources.load_rulebook(rid, public_only=True) == {}
    assert rid not in resources.all_rulebooks()
    assert resources.find_rulebook_file(rid) is None
    assert resources.rulebook_source(rid) is None


def test_single_repo_rulebooks_folder_link_is_not_followed(local, no_plugins, monkeypatch, tmp_path, secret_outside):
    repo = tmp_path / "evil_repo"
    _w(repo / "manifest.json", {"online_sessions": True, "external_services_allowed": True})
    _dir_link(repo / "rulebooks", secret_outside)
    _repos(monkeypatch, repo)
    _assert_not_readable()


def test_aggregate_subfolder_rulebooks_link_is_not_followed(local, no_plugins, monkeypatch, tmp_path, secret_outside):
    repo = tmp_path / "agg"
    _w(repo / "pack" / "manifest.json", {"online_sessions": True})
    _dir_link(repo / "pack" / "rulebooks", secret_outside)
    _repos(monkeypatch, repo)
    _assert_not_readable()


def test_plugin_rulebooks_link_is_not_followed(grid_plugin, secret_outside):
    shutil.rmtree(grid_plugin / "rulebooks")  # 普通のフォルダを消してから、同じ名前のリンクにする
    _dir_link(grid_plugin / "rulebooks", secret_outside)
    _assert_not_readable()
    assert (secret_outside / "secret.json").exists()  # 外のファイルは残っている（読めなかっただけ）


def test_invite_on_an_offline_table_is_refused_for_a_closed_rulebook(online_books):
    """オフラインの卓でも、招待で人を入れるならオンラインの卓として確かめる（B-013・B-022。実装レビューの🔴2）。"""
    with TestClient(app) as client:
        r = client.post("/api/session/start", json={
            "character_ids": [], "online_mode": False, "trpg_mode": True, "trpg_rulebook": "closed_book"})
        assert r.status_code == 200  # オフラインの卓は作れる
        sid, host = r.json()["session_id"], r.json()["host_token"]
        try:
            inv = client.post(f"/api/session/{sid}/invite", json={"rating": "SFW"},
                              headers={"Authorization": f"Bearer {host}"})
            assert inv.status_code == 403
        finally:
            _sessions.pop(sid, None)


def test_join_an_offline_table_with_an_old_invite_is_refused(online_books, tmp_path):
    with TestClient(app) as client:
        r = client.post("/api/session/start", json={
            "character_ids": [], "online_mode": False, "trpg_mode": True, "trpg_rulebook": "ok_book"})
        sid, host = r.json()["session_id"], r.json()["host_token"]
        try:
            code = client.post(f"/api/session/{sid}/invite", json={"rating": "SFW"},
                               headers={"Authorization": f"Bearer {host}"}).json()["invite_code"]
            _w(tmp_path / "ok" / "manifest.json", {"online_sessions": False})
            assert client.post("/api/session/join", json={"invite_code": code}).status_code == 403
        finally:
            _sessions.pop(sid, None)
