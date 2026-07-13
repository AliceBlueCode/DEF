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

    # セッション履歴注入（判定ロール自動化用）
    if req.session_id and req.character_id:
        from def_kari.api.routes.session import _sessions
        sess = _sessions.get(req.session_id)
        if sess:
            name_map = sess.get("name_map", {})
            cname = name_map.get(req.character_id, req.character_id)
            stat_part = f"【{req.stat_name}】" if req.stat_name else ""
            j = judgment or {}
            jv = j.get("judgment_value", req.skill_value)
            if j.get("critical"):
                outcome = "クリティカル！"
            elif j.get("fumble"):
                outcome = "ファンブル…"
            elif j.get("success"):
                outcome = "成功"
            elif j:
                outcome = "失敗"
            else:
                outcome = ""
            msg = f"🎲 {cname}{stat_part} {result['total']} / {jv}"
            if outcome:
                msg += f" → {outcome}"
            sess["history"].append({
                "role": "user",
                "content": msg,
                "character_id": "_dice",
            })

    # イベントバス通知（判定が行われたセッションに記録する）
    if judgment and req.session_id:
        from def_kari.gm.events import game_event_bus, JUDGMENT_RESOLVED
        game_event_bus.emit(req.session_id, JUDGMENT_RESOLVED, {
            "character_id": req.character_id,
            "stat_name": req.stat_name,
            "notation": result["notation"],
            "roll": result["total"],
            "judgment_value": judgment.get("judgment_value"),
            "success": judgment.get("success"),
            "critical": judgment.get("critical"),
            "fumble": judgment.get("fumble"),
        })

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
