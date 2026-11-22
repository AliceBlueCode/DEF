"""プラグインが返す画面のデータ（def_kari/trpg/ui_schema.py）の、形の悪い所を除く確かめ。

プラグインは外の人も書くので、はじく側こそ確かめる。2026-11-23 にカバレッジを測ったら、状態の欄・確かめの
ログ・承認の部品の悪い要素を除く所と、上限で切る所が、一度も動いていなかった。どれも、悪い要素だけを除き、
同じ部品の正しい要素は残し、どこを除いたかを problems に書く。
"""
import pytest

from def_kari.trpg import ui_schema
from def_kari.trpg.ui_schema import validate_ui_state


def _one(comp):
    ui, problems = validate_ui_state({"ui_schema": 1, "components": [comp]})
    assert len(ui["components"]) == 1, problems
    return ui["components"][0], problems


GOOD_FIELD = {"label": "HP", "value": 10, "max": 12}
GOOD_ROW = {"label": "A", "items": [GOOD_FIELD]}


@pytest.mark.parametrize("comp,path,where", [
    # 状態の欄
    ({"type": "status_panel", "id": "st", "order": [{"label": "A", "value": 1}, {"value": 2}]},
     ("order",), "order[1]"),
    ({"type": "status_panel", "id": "st", "groups": [{"title": "PCs", "rows": [GOOD_ROW]}, {"rows": []}]},
     ("groups",), "groups[1]"),
    ({"type": "status_panel", "id": "st", "groups": [{"title": "PCs", "rows": [GOOD_ROW, {"items": []}]}]},
     ("groups", 0, "rows"), "rows[1]"),
    ({"type": "status_panel", "id": "st", "groups": [{"title": "PCs", "rows": [
        {"label": "A", "items": [GOOD_FIELD, {"label": "MP", "value": {"x": 1}}]}]}]},
     ("groups", 0, "rows", 0, "items"), "items[1]"),
    # 確かめのログ
    ({"type": "check_log", "id": "log", "entries": [{"id": "e1", "text": "hit"}, {"id": "e2", "text": 3}]},
     ("entries",), "entries[1]"),
    # 承認
    ({"type": "approval", "id": "ap", "summary": ["move", 5]}, ("summary",), "summary[1]"),
    ({"type": "approval", "id": "ap", "choices": [{"id": "ok", "label": "OK"}, {"id": "../x", "label": "X"}]},
     ("choices",), "choices[1]"),
    ({"type": "approval", "id": "ap", "inputs": [{"id": "t", "label": "T"}, {"label": "no id"}]},
     ("inputs",), "inputs[1]"),
    # 盤（オブジェクトでない駒）
    ({"type": "grid_board", "id": "map", "cols": 2, "rows": 2,
      "tokens": [{"id": "t1", "pos": [0, 0], "label": "A"}, "t2"]}, ("tokens",), "tokens[1]"),
])
def test_a_bad_element_is_left_out_and_the_good_one_stays(comp, path, where):
    got, problems = _one(comp)
    for key in path:
        got = got[key]
    assert len(got) == 1
    assert len(problems) == 1 and where in problems[0], problems


def test_missing_lists_are_empty_and_a_non_list_is_noted():
    got, problems = _one({"type": "status_panel", "id": "st"})
    assert got["order"] == [] and got["groups"] == [] and problems == []
    got, problems = _one({"type": "check_log", "id": "log", "entries": {"e1": "hit"}})
    assert got["entries"] == [] and problems == ["components[0](log).entries: must be a list"]


def test_board_labels_and_terrains_of_the_wrong_shape():
    got, problems = _one({"type": "grid_board", "id": "map", "cols": 3, "rows": 2})
    assert got["col_labels"] is None and got["row_labels"] is None and problems == []   # 無ければ、画面が決める
    got, problems = _one({"type": "grid_board", "id": "map", "cols": 3, "rows": 2,
                          "col_labels": ["A", "B"], "row_labels": ["1", "x" * 17], "terrains": ["plain"]})
    assert got["col_labels"] is None and got["row_labels"] is None and got["terrains"] == {}
    assert sorted(p.split(":")[0].rsplit(".", 1)[1] for p in problems) == ["col_labels", "row_labels", "terrains"]


def test_too_many_items_are_cut(monkeypatch):
    monkeypatch.setattr(ui_schema, "MAX_ITEMS", 3)
    got, problems = _one({"type": "check_log", "id": "log",
                          "entries": [{"id": f"e{i}", "text": "x"} for i in range(5)]})
    assert [e["id"] for e in got["entries"]] == ["e0", "e1", "e2"]
    assert problems == ["components[0](log).entries: only the first 3 items are shown"]


def test_problems_stop_at_a_hundred():
    """悪い要素が多くても、ホストへの知らせは100件で止める（画面と記録を埋めない）。"""
    got, problems = _one({"type": "check_log", "id": "log", "entries": [{"id": "e"}] * 150})
    assert got["entries"] == [] and len(problems) == 100
