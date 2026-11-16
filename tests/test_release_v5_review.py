"""v5.0.0 のリリース前の全体レビュー（第3回、2026-11-17）の修正を固定する。"""

import json

import pytest

from def_kari.trpg import resources


def test_list_says_when_the_rulebook_repository_is_not_set(monkeypatch, tmp_path):
    """🔴2: 自分のルールブックだけがあって DEF-Rulebook を設定していない人にも、置き場所を知らせる。"""
    from def_kari.api.routes import trpg as t
    local = tmp_path / "public" / "trpg_rules"
    local.mkdir(parents=True)
    (local / "mine.json").write_text(json.dumps({"label": "mine"}), encoding="utf-8")
    monkeypatch.setattr(resources, "RULEBOOK_DIRS", [local])
    monkeypatch.setenv("TRPG_RULEBOOK_REPO_PATHS", "")
    out = t.list_rulebooks()
    assert [b["id"] for b in out["rulebooks"]] == ["mine"] and out["notice"] == "no_repo"
    monkeypatch.setenv("TRPG_RULEBOOK_REPO_PATHS", str(tmp_path / "somewhere"))
    assert "notice" not in t.list_rulebooks()


def test_trpg_table_without_a_rulebook_is_not_started():
    """🟡2: ルールブックの無い TRPG の卓は作らない（ルールの説明が空・判定なしで黙って進むため）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    client = TestClient(app)
    r = client.post("/api/session/start", json={"character_ids": [], "trpg_mode": True, "trpg_rulebook": ""})
    assert r.status_code == 400 and "TRPG_RULEBOOK_REPO_PATHS" in r.json()["detail"]
    r = client.post("/api/session/start", json={"character_ids": [], "trpg_mode": False})
    assert r.status_code == 200  # TRPG でない卓は今までどおり
    from def_kari.api.routes.session_state import _sessions
    _sessions.pop(r.json()["session_id"], None)


def test_old_ws_cleanup_does_not_drop_a_newer_connection():
    """🟢: 同じトークンで新しい接続が先に入っていたら、古い接続の後始末で新しい方を外さない。"""
    from def_kari.api.routes.session_ws import _forget_ws_connection
    old, new = object(), object()
    sess = {"ws_connections": {"tok": new}}
    assert _forget_ws_connection(sess, "tok", old) is None
    assert sess["ws_connections"]["tok"] is new
    assert _forget_ws_connection(sess, "tok", new) is new and "tok" not in sess["ws_connections"]
    sess["ws_connections"]["tok2"] = new
    assert _forget_ws_connection(sess, "tok2") is new  # ws を渡さなければ今までどおり外す


def test_settings_reads_an_env_file_with_a_bom(monkeypatch, tmp_path):
    """🟢: 設定の画面の `.env` の読み込みも、先頭の BOM を名前に含めない。"""
    from def_kari.api.routes import settings as st
    p = tmp_path / ".env"
    p.write_text("﻿FIRST_KEY=1\nSECOND=2\n", encoding="utf-8")
    monkeypatch.setattr(st, "_ENV_PATH", p)
    assert st._load_env_file() == {"FIRST_KEY": "1", "SECOND": "2"}


@pytest.mark.parametrize("path", ["/api/trpg/damage", "/api/trpg/opposed-check"])
def test_damage_and_opposed_read_only_one_rulebook(monkeypatch, path):
    """🟢: ダメージ・対抗判定も、全部のルールブックを読まない。"""
    from def_kari.api.routes import trpg as t

    def boom():
        raise AssertionError("all rulebooks were read")
    monkeypatch.setattr(t, "_load_rulebooks", boom)
    if path.endswith("damage"):
        assert t.damage_roll(t.DamageRollRequest(rulebook_id="nope")) == {"error": "Rulebook 'nope' not found"}
    else:
        req = t.OpposedCheckRequest(attacker_roll=1, attacker_skill=1, defender_roll=1, defender_skill=1,
                                    rulebook_id="nope")
        assert t.opposed_check_endpoint(req) == {"error": "Rulebook 'nope' not found"}


def test_public_source_has_no_private_rule_names():
    """🔴1: 公開の DEF のソースに、非公開のルールの名前を書かない（B-007）。"""
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    # 名前そのものをこのファイルにも書かないよう、符号で持つ
    words = [bytes.fromhex("6b697368696e").decode("ascii"), "\u6a5f\u795e"]
    out = subprocess.run(["git", "grep", "-nIi", "-e", words[0], "-e", words[1]], cwd=root,
                         capture_output=True, text=True, encoding="utf-8")
    assert out.stdout == "", out.stdout
