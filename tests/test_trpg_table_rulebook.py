"""レビュー（2026-11-15。7b3e394..5664bfb）の🟡の修正を固定する。

- 🟡1: 卓のルールブックが見つからないとき、戻さない・読み込まない・遊んでいる途中なら止める（B-019・B-027）。
- 🟡2: ルールブック・シナリオの一覧は、出どころを1回だけ走査する（項目ごとに探し直さない）。
- 🟡3: 判定するかどうかはルールシステムが決める（値 0 も渡す）。合計を返すルールシステムは、文に合計を書く。
"""

import json
import time
from unittest.mock import patch

import pytest

from def_kari.trpg import registry, resources


# ── 🟡1 ──────────────────────────────────────────────────────────

def test_autosave_with_missing_rulebook_is_not_restored(tmp_path):
    """C-002: 見つからないルールブックの卓は、自動保存から戻さない。ファイルは残す（以前は戻して黙って進んだ）。"""
    from def_kari.api.routes import session_persistence as sp
    from def_kari.api.routes.session_state import _sessions
    f = tmp_path / "autosave.json"
    f.write_text(json.dumps({"id": "_gone_book", "trpg_mode": True, "trpg_rulebook": "vanished_book",
                             "trpg_rule_system": "def_original", "history": []}), encoding="utf-8")
    sp._restore_one_autosave_file(f, time.time())
    assert "_gone_book" not in _sessions
    assert f.exists()


def test_load_with_missing_rulebook_is_refused(monkeypatch, tmp_path):
    from def_kari.api.routes import session_persistence as sp
    monkeypatch.setattr(sp, "_SESSION_HISTORY_DIRS", [tmp_path])
    (tmp_path / "saved_gone.json").write_text(json.dumps({
        "metadata": {"trpg_rulebook": "vanished_book", "trpg_rule_system": "def_original"}, "history": []}),
        encoding="utf-8")
    out = sp.load_session(sp.SessionLoadRequest(filename="saved_gone.json"))
    assert "cannot be found" in out["error"] and "TRPG_RULEBOOK_REPO_PATHS" in out["error"]


@pytest.mark.parametrize("builder", ["build_for_gm", "build_for_player"])
def test_context_for_a_table_whose_rulebook_is_gone_raises(builder):
    """GM の語り・AI の手番の文脈を作るとき、卓のルールブックが読めなければ RuleSystemError（呼ぶ側が止める）。"""
    from def_kari.gm import context_builder as cb
    session = {"trpg_rulebook": "vanished_book", "history": [], "name_map": {}}
    with pytest.raises(registry.RuleSystemError, match="cannot be found"):
        if builder == "build_for_gm":
            cb.build_for_gm({}, None, session, "ja")
        else:
            cb.build_for_player("c1", {}, {}, None, session, "ja")
    # ルールブックの無い卓（trpg_rulebook が空）は、今までどおり
    assert isinstance(cb.build_for_gm({}, None, {"trpg_rulebook": ""}, "ja"), str)


# ── 🟡2 ──────────────────────────────────────────────────────────

def test_listing_scans_sources_once_and_matches_table_permissions(monkeypatch, tmp_path):
    repos = []
    for n in range(3):
        r = tmp_path / f"repo{n}"
        (r / "rulebooks").mkdir(parents=True)
        (r / "scenarios").mkdir(parents=True)
        (r / "manifest.json").write_text(json.dumps({"online_sessions": n != 1, "credit": f"c{n}"}), encoding="utf-8")
        for k in range(4):
            (r / "rulebooks" / f"rb{n}_{k}.json").write_text(json.dumps({"label": "x"}), encoding="utf-8")
            (r / "scenarios" / f"sc{n}_{k}.json").write_text(json.dumps({"title": "x"}), encoding="utf-8")
        repos.append(str(r))
    monkeypatch.setenv("TRPG_RULEBOOK_REPO_PATHS", ";".join(repos))
    calls = {"n": 0}
    real = resources._external_sources

    def counting():
        calls["n"] += 1
        return real()
    monkeypatch.setattr(resources, "_external_sources", counting)
    books = resources.rulebook_listing()
    scenarios = resources.scenario_listing()
    assert calls["n"] == 2  # 一覧ごとに1回だけ（以前は項目ごとに探し直していた）
    monkeypatch.setattr(resources, "_external_sources", real)
    for rid, _, perms in books:  # 計算の結果は、1件ずつ確かめたときと同じ
        assert perms == resources.table_permissions(rid)
    for sid, _, perms in scenarios:
        assert perms == resources.table_permissions("", sid)
    assert {rid for rid, _, _ in books} >= {f"rb{n}_{k}" for n in range(3) for k in range(4)}


# ── 🟡3 ──────────────────────────────────────────────────────────

class _Sum:
    """出目＋値 ≧ 10 で成功し、合計を返す、テスト用のルールシステム。"""
    id = "_sum"
    capabilities = frozenset()

    def general_check(self, roll_total, value, rulebook, **options):
        total = roll_total + value
        return {"success": total >= 10, "critical": False, "fumble": False, "roll": roll_total,
                "total": total, "judgment_value": 10, "judgment_type": "_sum"}


def test_value_zero_is_judged_when_the_rule_system_wants(monkeypatch):
    """C-002: 判定するかどうかはルールシステムが決める。以前は「値が 0 より大きいとき」が本体に直書きされていた。"""
    from def_kari.api.routes import trpg as t
    monkeypatch.setattr(t, "_load_rulebooks", lambda: {"rb": {"rule_system": "_sum"}})
    out = t.compute_dice_judgment("1d20", 0, "rb", system=_Sum())
    assert out["judgment"] is not None and out["judgment"]["total"] == out["result"]["total"]
    # def_original は、値が 0 以下なら今までどおり判定しない
    assert t.compute_dice_judgment("1d100", 0, "rb", system=registry.get("def_original"))["judgment"] is None


def test_history_and_event_show_the_total(monkeypatch):
    from def_kari.api.routes.session_gameplay import SessionDiceRollRequest, session_dice_roll
    from def_kari.api.routes.session_state import _sessions
    sid = "_sum_dice"
    _sessions[sid] = {"id": sid, "trpg_rulebook": "rb", "trpg_rule_system": "_sum", "trpg_plugin_version": "",
                      "history": [], "name_map": {"c": "C"}, "human_char_ids": [], "players": {}}
    monkeypatch.setattr("def_kari.trpg.plugin_hooks.resolve_for_session", lambda s: (_Sum(), None))
    monkeypatch.setattr(resources, "load_rulebook", lambda rid, public_only=False: {"rule_system": "_sum", "dice_system": "1d20"})
    monkeypatch.setattr("def_kari.api.routes.trpg._load_rulebooks", lambda: {"rb": {"rule_system": "_sum"}})
    monkeypatch.setattr(registry, "call_rule", lambda system, m, *a, **k: "1d20" if m == "dice_notation" else getattr(system, m)(*a, **k))
    monkeypatch.setattr("def_kari.trpg.rule_engine.secrets.randbelow", lambda n: 7)  # 出目 8
    try:
        with patch("def_kari.api.routes.session_gameplay._game_event_bus") as bus, \
                patch("def_kari.api.routes.session_gameplay._autosave"):
            session_dice_roll(sid, SessionDiceRollRequest(character_id="c", stat_name="知覚", skill_value=3),
                              _auth={"jti": "h", "role": "host"})
        assert _sessions[sid]["history"][-1]["content"].endswith("8+3=11 / 10 → 成功")
        assert bus.emit.call_args[0][2]["total"] == 11
    finally:
        _sessions.pop(sid, None)
