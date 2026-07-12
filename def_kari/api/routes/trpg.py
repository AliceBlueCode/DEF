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


# ── ダイス ────────────────────────────────────────────────────────

class DiceRollRequest(BaseModel):
    notation: str
    session_id: str = ""
    skill_value: int = 0
    rulebook_id: str = ""


@router.post("/dice")
def dice_roll(req: DiceRollRequest):
    try:
        result = roll_dice(req.notation)
    except ValueError as e:
        return {"error": str(e)}

    judgment = None
    if req.skill_value > 0 and req.rulebook_id:
        books = _load_rulebooks()
        rulebook = books.get(req.rulebook_id, {})
        if rulebook:
            judgment = judge(result["total"], req.skill_value, rulebook)

    return {
        "notation": result["notation"],
        "rolls": result["rolls"],
        "total": result["total"],
        "modifier": result["modifier"],
        "judgment": judgment,
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
