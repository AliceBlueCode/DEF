"""C-001: ルールブックとシナリオの読み込みの今の挙動を固定する（public → private の順、
`public_only`、パストラバーサルの拒否、壊れたファイル、ファイル名と id の関係）。

今は読み込み先が `api/routes/trpg.py`（一覧・取得）と `gm/context_builder.py`（セッションで使う）の
2か所にあり、同じ ID が両方の置き場にあるときの勝ち方が違う。B-010・B-011 で1か所にまとめて
順番を変えるので、順番に関わるテストは C-002 の印を付けてある。
"""

import json

import pytest

from def_kari.api.routes import trpg as t
from def_kari.gm import context_builder as cb


def _write(dirpath, name, data):
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    (dirpath / f"{name}.json").write_text(text, encoding="utf-8")


def test_same_id_session_loader_prefers_public(rulebook_dirs):
    """C-002: A章でわざと変える挙動（B-011 で、外部のリポジトリ → public → private の順にする）。"""
    public, private = rulebook_dirs
    _write(public / "trpg_rules", "dup", {"label": "public"})
    _write(private / "trpg_rules", "dup", {"label": "private"})
    assert cb.load_trpg_rulebook("dup")["label"] == "public"
    assert t.get_rulebook("dup")["content"] == json.dumps({"label": "public"})


def test_same_id_list_prefers_private(rulebook_dirs):
    """C-002: A章でわざと変えた挙動（B-011、2026-11-14）。以前の一覧は、後から読んだ private で
    上書きしていて、ID を指定した読み込み（public が勝つ）と逆だった。今は一覧も先に見つかった
    public を使い、重なりを警告に残す。"""
    public, private = rulebook_dirs
    _write(public / "trpg_rules", "dup", {"label": "public"})
    _write(private / "trpg_rules", "dup", {"label": "private"})
    assert [b["label"] for b in t.list_rulebooks()["rulebooks"]] == ["public"]


def test_public_only_ignores_private(rulebook_dirs):
    public, private = rulebook_dirs
    _write(private / "trpg_rules", "secret", {"label": "p"})
    _write(private / "trpg_scenarios", "secret_s", {"title": "p"})
    assert cb.load_trpg_rulebook("secret") == {"label": "p"}
    assert cb.load_trpg_rulebook("secret", public_only=True) == {}
    assert cb.load_trpg_scenario("secret_s") == {"title": "p"}
    assert cb.load_trpg_scenario("secret_s", public_only=True) == {}


def test_broken_json_falls_through_to_next_dir(rulebook_dirs):
    public, private = rulebook_dirs
    _write(public / "trpg_rules", "bk", "{broken")
    _write(private / "trpg_rules", "bk", {"label": "private"})
    assert cb.load_trpg_rulebook("bk") == {"label": "private"}
    assert [b["id"] for b in t.list_rulebooks()["rulebooks"]] == ["bk"]


def test_list_and_session_loader_both_use_the_file_name(rulebook_dirs):
    """C-002: A章でわざと変えた挙動（B-029、2026-11-14）。以前の一覧は JSON の `id` を ID にしていて、
    一覧に出た ID では取得できなかった。今は一覧もファイル名を ID にし、食い違いは警告に残す。"""
    public, _ = rulebook_dirs
    _write(public / "trpg_rules", "foo", {"id": "bar"})
    assert cb.load_trpg_rulebook("foo") == {"id": "bar"}
    assert cb.load_trpg_rulebook("bar") == {}
    assert [b["id"] for b in t.list_rulebooks()["rulebooks"]] == ["foo"]


@pytest.mark.parametrize("bad", ["", "../x", "a/b", "a\\b", "C:/x", "/etc/passwd", "x.json", "a b"])
def test_session_loader_rejects_unsafe_ids(rulebook_dirs, bad):
    public, _ = rulebook_dirs
    _write(public / "trpg_rules", "x", {"label": "x"})
    assert cb.load_trpg_rulebook(bad) == {}
    assert cb.load_trpg_scenario(bad) == {}


def test_missing_returns_empty(rulebook_dirs):
    assert cb.load_trpg_rulebook("nope") == {}
    assert cb.load_trpg_scenario("nope") == {}


def test_scenario_list_and_get(rulebook_dirs):
    """C-002: A章でわざと変えた挙動（B-023、2026-11-14）。一覧の各項目に `credits`（manifest の `credit` の一覧）を足した。"""
    public, private = rulebook_dirs
    _write(public / "trpg_scenarios", "s1", {"title": "T1", "synopsis": "S", "rulebook_id": "def_original"})
    _write(private / "trpg_scenarios", "s2", {"id": "s2", "title": "T2"})
    assert t.list_scenarios() == {"scenarios": [
        {"id": "s1", "label": "T1", "synopsis": "S", "rulebook_id": "def_original", "credits": []},
        {"id": "s2", "label": "T2", "synopsis": "", "rulebook_id": "", "credits": []},
    ]}
    assert t.get_scenario("s2")["id"] == "s2"
    assert t.get_scenario("../s2") == {"error": "Invalid scenario ID"}
    assert t.get_scenario("nope") == {"error": "Scenario 'nope' not found"}
