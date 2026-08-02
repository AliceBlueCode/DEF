"""TRPG API routes: rulebook management and dice rolling."""

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from def_kari.trpg.rule_engine import roll_dice, judge, opposed_check, validate_rulebook

router = APIRouter()

_BASE = Path(__file__).parent.parent.parent.parent
_RULEBOOK_DIRS = [
    _BASE / "data" / "public" / "trpg_rules",
    _BASE / "data" / "private" / "trpg_rules",
]
_SCENARIO_DIRS = [
    _BASE / "data" / "public" / "trpg_scenarios",
    _BASE / "data" / "private" / "trpg_scenarios",
]
_SAFE_ID_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


def _load_rulebooks() -> dict:
    books = {}
    for d in _RULEBOOK_DIRS:
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix == ".json" and f.name != ".gitkeep":
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        bid = data.get("id", f.stem)
                        books[bid] = data
                    except (json.JSONDecodeError, OSError):
                        pass
    return books


@router.get("/rulebooks")
def list_rulebooks():
    books = _load_rulebooks()
    return {
        "rulebooks": [
            {
                "id": bid,
                "label": b.get("label", bid),
                "rule_system_name": b.get("rule_system_name", ""),
                "dice_system": b.get("dice_system", "1d100"),
                "private": False,
            }
            for bid, b in books.items()
            if bid != "blank_template"
        ]
    }


@router.get("/rulebooks/{rulebook_id}")
def get_rulebook(rulebook_id: str):
    if not _SAFE_ID_RE.match(rulebook_id):
        return {"error": "Invalid rulebook ID"}
    for d in _RULEBOOK_DIRS:
        path = d / f"{rulebook_id}.json"
        if path.exists():
            try:
                return {"content": path.read_text(encoding="utf-8"), "id": rulebook_id}
            except OSError as e:
                return {"error": str(e)}
    return {"error": f"Rulebook '{rulebook_id}' not found"}


class SaveRulebookRequest(BaseModel):
    content: str


@router.put("/rulebooks/{rulebook_id}")
def save_rulebook(rulebook_id: str, req: SaveRulebookRequest):
    if not _SAFE_ID_RE.match(rulebook_id):
        return {"error": "Invalid rulebook ID"}
    try:
        data = json.loads(req.content)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}
    errors = validate_rulebook(data)
    if errors:
        return {"error": "Validation failed", "details": errors}

    target = None
    for d in _RULEBOOK_DIRS:
        path = d / f"{rulebook_id}.json"
        if path.exists():
            target = path
            break
    if target is None:
        _RULEBOOK_DIRS[0].mkdir(parents=True, exist_ok=True)
        target = _RULEBOOK_DIRS[0] / f"{rulebook_id}.json"

    tmp = str(target) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(target))
    return {"status": "ok", "id": rulebook_id}


# ── シナリオ ──────────────────────────────────────────────────────

def _load_scenarios() -> dict:
    scenarios = {}
    for d in _SCENARIO_DIRS:
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix == ".json" and f.name != ".gitkeep":
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        sid = data.get("id", f.stem)
                        scenarios[sid] = data
                    except (json.JSONDecodeError, OSError):
                        pass
    return scenarios


@router.get("/scenarios")
def list_scenarios():
    scenarios = _load_scenarios()
    return {
        "scenarios": [
            {
                "id": sid,
                "label": s.get("title", sid),
                "synopsis": s.get("synopsis", ""),
                "rulebook_id": s.get("rulebook_id", ""),
            }
            for sid, s in scenarios.items()
        ]
    }


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str):
    if not _SAFE_ID_RE.match(scenario_id):
        return {"error": "Invalid scenario ID"}
    for d in _SCENARIO_DIRS:
        path = d / f"{scenario_id}.json"
        if path.exists():
            try:
                return {"content": path.read_text(encoding="utf-8"), "id": scenario_id}
            except OSError as e:
                return {"error": str(e)}
    return {"error": f"Scenario '{scenario_id}' not found"}


# ── ダイス ────────────────────────────────────────────────────────

class DiceRollRequest(BaseModel):
    notation: str
    session_id: str = ""
    skill_value: int = 0
    rulebook_id: str = ""
    character_id: str = ""
    stat_name: str = ""
    is_skill: bool = False  # True=技能値直接（×5しない）
    is_stat: bool = False   # True=能力値生判定（untrained_success_condition を使用）


def compute_dice_judgment(
    notation: str,
    skill_value: int = 0,
    rulebook_id: str = "",
    is_skill: bool = False,
    is_stat: bool = False,
) -> dict:
    """ダイスロール＋判定計算のみを行う純粋関数（セッション状態には一切触れない）。

    `session.py` の `/{session_id}/dice`（require_player）と、この後の無認証 `/dice`
    （セッション非依存の汎用計算用）の両方から呼ばれる。notation不正時は ValueError。
    """
    result = roll_dice(notation)

    judgment = None
    if skill_value > 0 and rulebook_id:
        books = _load_rulebooks()
        rulebook = books.get(rulebook_id, {})
        if rulebook:
            if is_skill:
                # 技能値配分済みの場合は roll_lte_skill として扱う
                from copy import deepcopy
                rb_override = deepcopy(rulebook)
                rb_override.setdefault("judgment", {})["success_condition"] = "roll_lte_skill"
                judgment = judge(result["total"], skill_value, rb_override)
            elif is_stat:
                # 能力値生判定: untrained_success_condition（例: roll_lte_stat_x5）を使用
                from copy import deepcopy
                rb_override = deepcopy(rulebook)
                uc = rulebook.get("judgment", {}).get("untrained_success_condition", "roll_lte_stat_x5")
                rb_override.setdefault("judgment", {})["success_condition"] = uc
                judgment = judge(result["total"], skill_value, rb_override)
            else:
                judgment = judge(result["total"], skill_value, rulebook)

    return {"result": result, "judgment": judgment}


@router.post("/dice")
def dice_roll(req: DiceRollRequest):
    """セッション非依存の汎用ダイス計算。session_id/character_idを渡してもセッション状態は変更しない
    （セッション連動のダイス判定は `POST /api/session/{session_id}/dice` を使うこと）。"""
    try:
        computed = compute_dice_judgment(req.notation, req.skill_value, req.rulebook_id, req.is_skill, req.is_stat)
    except ValueError as e:
        return {"error": str(e)}
    result = computed["result"]
    judgment = computed["judgment"]
    return {
        "notation": result["notation"],
        "rolls": result["rolls"],
        "total": result["total"],
        "modifier": result["modifier"],
        "judgment": judgment,
    }


class DamageRollRequest(BaseModel):
    session_id: str = ""
    character_id: str = ""
    rulebook_id: str = "def_original"


@router.post("/damage")
def damage_roll(req: DamageRollRequest):
    result = roll_dice("1d100")
    roll_val = result["total"]

    books = _load_rulebooks()
    rulebook = books.get(req.rulebook_id, {})
    entries = rulebook.get("damage_mechanics", {}).get("damage_table", {}).get("entries", [])

    entry = next((e for e in entries if e.get("roll") == roll_val), None)
    if not entry:
        return {"error": "Entry not found", "roll": roll_val}

    if entry.get("result") == "即死":
        return {
            "roll": roll_val,
            "result": "即死",
            "stat": None,
            "delta": None,
            "flavor": entry.get("flavor", ""),
        }

    return {
        "roll": roll_val,
        "result": "damage",
        "stat": entry["stat"],
        "delta": entry["delta"],
        "flavor": entry.get("flavor", ""),
    }


class OpposedCheckRequest(BaseModel):
    attacker_roll: int
    attacker_skill: int
    defender_roll: int
    defender_skill: int
    rulebook_id: str = "def_original"


@router.post("/opposed-check")
def opposed_check_endpoint(req: OpposedCheckRequest):
    books = _load_rulebooks()
    rulebook = books.get(req.rulebook_id, {})
    if not rulebook:
        return {"error": f"Rulebook '{req.rulebook_id}' not found"}
    result = opposed_check(
        req.attacker_roll, req.attacker_skill,
        req.defender_roll, req.defender_skill,
        rulebook,
    )
    return result
