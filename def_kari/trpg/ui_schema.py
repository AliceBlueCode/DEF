"""画面部品に渡すデータ（`ui_state`）の形の確かめ（マルチルールブック基盤 B-052、基本設計書 11.5）。

プラグインが返した `ui_state` を、DEF が描く前に形に照らす。正しくない部品（またはその要素）だけを除き、
何を除いたかを `problems` に返す（ホストの画面に知らせる）。他の部品は描き続ける。

位置は `[列, 行]`（どちらも 0 から）。表示に出す座標の文字は `col_labels`・`row_labels` でプラグインが決める。
見た目の種類は `STYLES` の決まった名前だけ。色そのものを決められるのは地形の色（`#rrggbb`）だけ。
文字は、どの部品でも文字として描く（HTML として扱わない）。
"""

import re

UI_SCHEMA = 1
COMPONENT_TYPES = ("grid_board", "status_panel", "check_log", "approval", "question")
STYLES = frozenset({"primary", "secondary", "info", "ok", "blocked", "dimmed"})
MAX_GRID = 64
MAX_ITEMS = 2000
MAX_TEXT = 2000
_ID_RE = re.compile(r"^[A-Za-z0-9_\-:.]{1,64}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _is_text(v, limit=MAX_TEXT) -> bool:
    return isinstance(v, str) and len(v) <= limit


def _is_id(v) -> bool:
    return isinstance(v, str) and bool(_ID_RE.match(v))


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_value(v) -> bool:
    return _is_text(v, 200) or _is_int(v) or (isinstance(v, float) and v == v)


class _Check:
    def __init__(self):
        self.problems: list[str] = []

    def note(self, where: str, why: str) -> None:
        if len(self.problems) < 100:
            self.problems.append(f"{where}: {why}")

    def items(self, value, where: str, keep) -> list:
        """リストの要素のうち `keep(要素, 場所)` が返したもの（None は除く）だけを残す。"""
        if value is None:
            return []
        if not isinstance(value, list):
            self.note(where, "must be a list")
            return []
        out = []
        for i, item in enumerate(value[:MAX_ITEMS]):
            kept = keep(item, f"{where}[{i}]")
            if kept is not None:
                out.append(kept)
        if len(value) > MAX_ITEMS:
            self.note(where, f"only the first {MAX_ITEMS} items are shown")
        return out


def _choices(c: _Check, value, where: str) -> list:
    def keep(item, w):
        if isinstance(item, dict) and _is_id(item.get("id")) and _is_text(item.get("label"), 200):
            return {"id": item["id"], "label": item["label"]}
        c.note(w, "a choice needs id and label")
        return None
    return c.items(value, where, keep)


def _grid_board(c: _Check, comp: dict, where: str) -> dict | None:
    cols, rows = comp.get("cols"), comp.get("rows")
    if not (_is_int(cols) and _is_int(rows) and 1 <= cols <= MAX_GRID and 1 <= rows <= MAX_GRID):
        c.note(where, f"cols and rows must be 1-{MAX_GRID}")
        return None

    def pos(p) -> list | None:
        if (isinstance(p, list) and len(p) == 2 and _is_int(p[0]) and _is_int(p[1])
                and 0 <= p[0] < cols and 0 <= p[1] < rows):
            return [p[0], p[1]]
        return None

    def labels(value, n, w):
        if value is None:
            return None
        if isinstance(value, list) and len(value) == n and all(_is_text(x, 16) for x in value):
            return list(value)
        c.note(w, f"must be a list of {n} short texts")
        return None

    terrains = {}
    raw_terrains = comp.get("terrains") or {}
    if not isinstance(raw_terrains, dict):
        c.note(f"{where}.terrains", "must be an object")
        raw_terrains = {}
    for key, t in list(raw_terrains.items())[:100]:
        if (_is_id(key) and isinstance(t, dict) and _is_text(t.get("label"), 100)
                and isinstance(t.get("color"), str) and _COLOR_RE.match(t["color"])
                and (t.get("height") is None or _is_int(t.get("height")))):
            terrains[key] = {"label": t["label"], "color": t["color"], "height": t.get("height")}
        else:
            c.note(f"{where}.terrains.{key}", "needs label, color (#rrggbb) and an optional integer height")

    def cell(item, w):
        p = pos(item.get("pos")) if isinstance(item, dict) else None
        if p is not None and item.get("terrain") in terrains:
            return {"pos": p, "terrain": item["terrain"]}
        c.note(w, "a cell needs a position on the board and a known terrain")
        return None

    def token(item, w):
        if not isinstance(item, dict):
            c.note(w, "a token must be an object")
            return None
        p = pos(item.get("pos"))
        marks = item.get("marks") or []
        if (_is_id(item.get("id")) and p is not None and _is_text(item.get("label"), 100)
                and (item.get("side") is None or _is_id(item.get("side")))
                and isinstance(marks, list) and all(m in STYLES for m in marks)):
            return {"id": item["id"], "pos": p, "label": item["label"], "side": item.get("side"),
                    "marks": list(marks)}
        c.note(w, "a token needs id, a position on the board, label, and known marks")
        return None

    def overlay(item, w):
        if not isinstance(item, dict) or item.get("style") not in STYLES:
            c.note(w, "an overlay needs a known style")
            return None
        cells = item.get("cells") if isinstance(item.get("cells"), list) else []
        kept = [p for p in (pos(x) for x in cells[:MAX_ITEMS]) if p is not None]
        if len(kept) != len(cells):
            c.note(w, "cells outside the board were left out")
        label = item.get("label")
        return {"cells": kept, "style": item["style"], "label": label if _is_text(label, 100) else None}

    def line(item, w):
        if isinstance(item, dict) and item.get("style") in STYLES:
            a, b = pos(item.get("from")), pos(item.get("to"))
            if a is not None and b is not None:
                label = item.get("label")
                return {"from": a, "to": b, "style": item["style"], "label": label if _is_text(label, 100) else None}
        c.note(w, "a line needs two positions on the board and a known style")
        return None

    sel = comp.get("selectable") if isinstance(comp.get("selectable"), dict) else {}
    token_list = c.items(comp.get("tokens"), f"{where}.tokens", token)
    token_ids = {t["id"] for t in token_list}
    return {
        "type": "grid_board", "id": comp["id"], "cols": cols, "rows": rows,
        "col_labels": labels(comp.get("col_labels"), cols, f"{where}.col_labels"),
        "row_labels": labels(comp.get("row_labels"), rows, f"{where}.row_labels"),
        "terrains": terrains,
        "cells": c.items(comp.get("cells"), f"{where}.cells", cell),
        "tokens": token_list,
        "overlays": c.items(comp.get("overlays"), f"{where}.overlays", overlay),
        "lines": c.items(comp.get("lines"), f"{where}.lines", line),
        "selectable": {
            "cells": [p for p in (pos(x) for x in (sel.get("cells") or [])[:MAX_ITEMS]) if p is not None]
            if isinstance(sel.get("cells") or [], list) else [],
            "tokens": [t for t in (sel.get("tokens") or []) if t in token_ids]
            if isinstance(sel.get("tokens") or [], list) else [],
        },
    }


def _status_panel(c: _Check, comp: dict, where: str) -> dict:
    def order_item(item, w):
        if isinstance(item, dict) and _is_text(item.get("label"), 100) and (
                item.get("value") is None or _is_value(item.get("value"))):
            return {"label": item["label"], "value": item.get("value")}
        c.note(w, "an order item needs label and an optional value")
        return None

    def field(item, w):
        if isinstance(item, dict) and _is_text(item.get("label"), 100) and _is_value(item.get("value")) and (
                item.get("max") is None or _is_value(item.get("max"))):
            return {"label": item["label"], "value": item["value"], "max": item.get("max")}
        c.note(w, "an item needs label and value")
        return None

    def row(item, w):
        if isinstance(item, dict) and _is_text(item.get("label"), 100):
            return {"label": item["label"], "items": c.items(item.get("items"), f"{w}.items", field)}
        c.note(w, "a row needs label")
        return None

    def group(item, w):
        if isinstance(item, dict) and _is_text(item.get("title"), 100):
            return {"title": item["title"], "rows": c.items(item.get("rows"), f"{w}.rows", row)}
        c.note(w, "a group needs title")
        return None

    return {"type": "status_panel", "id": comp["id"],
            "order": c.items(comp.get("order"), f"{where}.order", order_item),
            "groups": c.items(comp.get("groups"), f"{where}.groups", group)}


def _check_log(c: _Check, comp: dict, where: str) -> dict:
    def entry(item, w):
        if isinstance(item, dict) and _is_id(item.get("id")) and _is_text(item.get("text")):
            tags = item.get("tags") or []
            return {"id": item["id"], "text": item["text"],
                    "tags": [t for t in tags if _is_text(t, 40)] if isinstance(tags, list) else [],
                    "cancelled": item.get("cancelled") is True}
        c.note(w, "an entry needs id and text")
        return None
    return {"type": "check_log", "id": comp["id"], "entries": c.items(comp.get("entries"), f"{where}.entries", entry)}


def _approval(c: _Check, comp: dict, where: str) -> dict:
    def text(item, w):
        if _is_text(item):
            return item
        c.note(w, "must be text")
        return None

    def an_input(item, w):
        if isinstance(item, dict) and _is_id(item.get("id")) and _is_text(item.get("label"), 100) and (
                item.get("value") is None or _is_value(item.get("value"))):
            return {"id": item["id"], "label": item["label"], "value": item.get("value")}
        c.note(w, "an input needs id and label")
        return None
    return {"type": "approval", "id": comp["id"],
            "summary": c.items(comp.get("summary"), f"{where}.summary", text),
            "choices": _choices(c, comp.get("choices"), f"{where}.choices"),
            "inputs": c.items(comp.get("inputs"), f"{where}.inputs", an_input)}


def _question(c: _Check, comp: dict, where: str) -> dict | None:
    if not _is_text(comp.get("prompt")):
        c.note(where, "a question needs prompt")
        return None
    return {"type": "question", "id": comp["id"], "prompt": comp["prompt"],
            "choices": _choices(c, comp.get("choices"), f"{where}.choices"),
            "free_text": comp.get("free_text") is True}


_BUILDERS = {"grid_board": _grid_board, "status_panel": _status_panel, "check_log": _check_log,
             "approval": _approval, "question": _question}


def validate_ui_state(state) -> tuple[dict, list[str]]:
    """(描いてよい ui_state, 除いたものの説明)。"""
    c = _Check()
    if not isinstance(state, dict) or state.get("ui_schema") != UI_SCHEMA:
        c.note("ui_state", f"ui_schema must be {UI_SCHEMA}")
        return {"ui_schema": UI_SCHEMA, "title": "", "revision": None, "components": []}, c.problems
    title = state.get("title") if _is_text(state.get("title"), 200) else ""
    # 世代番号（画面は操作の base_revision に、これをそのまま返す）
    revision = state.get("revision") if _is_int(state.get("revision")) else None
    seen: set[str] = set()

    def component(comp, w):
        if not isinstance(comp, dict) or comp.get("type") not in _BUILDERS or not _is_id(comp.get("id")):
            c.note(w, "unknown component type or missing id")
            return None
        if comp["id"] in seen:
            c.note(w, f"duplicate id {comp['id']!r}")
            return None
        seen.add(comp["id"])
        return _BUILDERS[comp["type"]](c, comp, f"{w}({comp['id']})")
    comps = c.items(state.get("components"), "components", component)
    return {"ui_schema": UI_SCHEMA, "title": title, "revision": revision, "components": comps}, c.problems


def validate_ui_action(action) -> dict | None:
    """画面からの操作の形 `{"component", "action", "data", "base_revision"}`。正しくなければ None。"""
    if not isinstance(action, dict):
        return None
    if not (_is_id(action.get("component")) and _is_id(action.get("action"))):
        return None
    data = action.get("data", {})
    base = action.get("base_revision")
    if not isinstance(data, dict) or not (base is None or _is_int(base)):
        return None
    return {"component": action["component"], "action": action["action"], "data": data, "base_revision": base}
