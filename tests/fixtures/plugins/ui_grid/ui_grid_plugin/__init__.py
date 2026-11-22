"""架空のルールシステム `ui_grid` のテスト用プラグイン（画面部品の口。差し込み口 11、B-008・B-052）。

画面の E2E（frontend/e2e/trpg_rule_ui.js）で、汎用の部品が描かれ、操作が口に届くことを確かめるためだけのもの。
実在のルールの中身は入れない。状態はプロセスの中だけに持つ（卓ごと）。

- 盤面 4×3（列 A〜D、行 1〜3）。コマ1つ。ホストは、コマの隣のマスを選んで動かせる。
- 承認はホストにだけ、質問はプレイヤーにだけ出す。ログは全員に出す（相手ごとに違うものを見せるのは口の側）。
- 形の正しくない部品を1つ混ぜる（ホストにだけ「表示していない」と知らせる確かめ用）。
- 操作のたびに `api.emit` でイベントを出す（ほかのタブが取り直す）。
"""

_STATE: dict[str, dict] = {}
COLS, ROWS = 4, 3


class UiGrid:
    id = "ui_grid"
    capabilities = frozenset({"ui"})

    def __init__(self, api):
        self.api = api

    # ── B-003 の5つ ──
    def validate_rulebook(self, data):
        return [] if data.get("rule_system_name") else ["ui_grid: rule_system_name is required"]

    def general_check(self, roll_total, value, rulebook, **options):
        total = roll_total + value
        return {"success": total >= 15, "roll": roll_total, "total": total, "judgment_type": "ui_grid_d20"}

    def allowed_skills(self, rulebook):
        return frozenset()

    def dice_notation(self, rulebook):
        return "1d20"

    def build_rule_context(self, rulebook, scenario, lang):
        return "[ui_grid] test rule system"

    # ── ui ──
    def _state(self, session_id):
        return _STATE.setdefault(session_id, {"token": [0, 0], "log": ["start <b>bold</b>"]})

    def ui_state(self, session, audience):
        st = self._state(session["id"])
        role = audience["role"]
        x, y = st["token"]
        near = [[c, r] for c, r in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)) if 0 <= c < COLS and 0 <= r < ROWS]
        board = {
            "type": "grid_board", "id": "map", "cols": COLS, "rows": ROWS,
            "col_labels": ["A", "B", "C", "D"], "row_labels": ["1", "2", "3"],
            "terrains": {"plain": {"label": "Plain", "color": "#88aa66", "height": 0},
                         "hill": {"label": "Hill", "color": "#aa8855", "height": 2}},
            "cells": [{"pos": [2, 1], "terrain": "hill"}] + [
                {"pos": [c, r], "terrain": "plain"} for c in range(COLS) for r in range(ROWS) if [c, r] != [2, 1]],
            "tokens": [{"id": "u1", "pos": [x, y], "label": "Unit One", "side": "pc", "marks": ["primary"]}],
            "overlays": [{"cells": near, "style": "info", "label": "Move"}],
            "lines": [{"from": [x, y], "to": [3, 2], "style": "ok", "label": "Sight"}],
            "selectable": {"cells": near if role == "host" else [], "tokens": []},
        }
        comps = [
            board,
            {"type": "status_panel", "id": "status", "order": [{"label": "Unit One", "value": 12}],
             "groups": [{"title": "Units", "rows": [{"label": "Unit One",
                                                     "items": [{"label": "HP", "value": 10, "max": 12}]}]}]},
            {"type": "check_log", "id": "log",
             "entries": [{"id": f"e{i}", "text": t} for i, t in enumerate(st["log"])]},
            {"type": "teleport", "id": "broken"},  # 形の正しくない部品（描かれない）
        ]
        if role == "host":
            comps.append({"type": "approval", "id": "ap", "summary": ["Approve the move?"],
                          "choices": [{"id": "ok", "label": "Approve"}, {"id": "no", "label": "Reject"}],
                          "inputs": [{"id": "note", "label": "Note", "value": ""}]})
        if role == "player":
            comps.append({"type": "question", "id": "q", "prompt": "Where should we go?",
                          "choices": [{"id": "north", "label": "North"}], "free_text": True})
        return {"ui_schema": 1, "title": f"seen by {role}", "revision": len(st["log"]), "components": comps}

    def ui_action(self, session, audience, action):
        st = self._state(session["id"])
        name, data = action["action"], action["data"]
        if action.get("base_revision") not in (None, len(st["log"])):
            return {"accepted": False, "reason": "stale"}
        if name == "select_cell":
            if audience["role"] != "host":
                return {"accepted": False, "reason": "host only"}
            st["token"] = list(data.get("pos", st["token"]))
            st["log"].append(f"moved to {'ABCD'[st['token'][0]]}{st['token'][1] + 1}")
        elif name == "choose":
            st["log"].append(f"approval: {data.get('choice')} ({(data.get('inputs') or {}).get('note', '')})")
        elif name == "answer":
            st["log"].append(f"answer from {audience['role']}: {data.get('text') or data.get('choice')}")
        else:
            return {"accepted": False, "reason": f"unknown action {name}"}
        self.api.emit(session["id"], "UI_GRID_CHANGED", {"revision": len(st["log"])})
        return {"accepted": True, "reason": ""}


def register(api):
    return UiGrid(api)
