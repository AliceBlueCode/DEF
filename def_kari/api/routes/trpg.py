"""TRPG API routes: rulebook management and dice rolling."""

import json
import os

from fastapi import APIRouter
from pydantic import BaseModel

from def_kari.trpg import registry, resources
from def_kari.trpg.rule_engine import roll_dice, opposed_check

router = APIRouter()

# ルールブックとシナリオの置き場所と読み込みは def_kari/trpg/resources.py にまとめた（B-010）。


def _load_rulebooks() -> dict:
    return resources.all_rulebooks()


@router.get("/rulebooks")
def list_rulebooks():
    books = _load_rulebooks()
    return {
        "rulebooks": [
            {
                "id": bid,
                "label": b.get("label", bid),
                "rule_system_name": b.get("rule_system_name", ""),
                "dice_system": registry.for_rulebook(b).dice_notation(b),
                "private": False,
            }
            for bid, b in books.items()
            if bid != "blank_template"
        ]
    }


@router.get("/rulebooks/{rulebook_id}")
def get_rulebook(rulebook_id: str):
    if not resources.is_safe_id(rulebook_id):
        return {"error": "Invalid rulebook ID"}
    path = resources.find_rulebook_file(rulebook_id)
    if path is not None:
        try:
            return {"content": path.read_text(encoding="utf-8"), "id": rulebook_id}
        except OSError as e:
            return {"error": str(e)}
    return {"error": f"Rulebook '{rulebook_id}' not found"}


class SaveRulebookRequest(BaseModel):
    content: str


@router.put("/rulebooks/{rulebook_id}")
def save_rulebook(rulebook_id: str, req: SaveRulebookRequest):
    if not resources.is_safe_id(rulebook_id):
        return {"error": "Invalid rulebook ID"}
    try:
        data = json.loads(req.content)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}
    # 検証はルールブックのルールシステムに任せる（B-003）。知らないルールシステムは保存しない（B-002）。
    system = registry.for_rulebook(data) if isinstance(data, dict) else registry.get(registry.DEFAULT_RULE_SYSTEM)
    if system is None:
        return {"error": "Validation failed", "details": [f"unknown rule_system: {registry.rule_system_of(data)!r}"]}
    errors = system.validate_rulebook(data)
    if errors:
        return {"error": "Validation failed", "details": errors}

    target = resources.find_rulebook_file(rulebook_id)
    if target is None:
        target = resources.new_rulebook_file(rulebook_id)

    tmp = str(target) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(target))
    return {"status": "ok", "id": rulebook_id}


# ── シナリオ ──────────────────────────────────────────────────────

def _load_scenarios() -> dict:
    return resources.all_scenarios()


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
    if not resources.is_safe_id(scenario_id):
        return {"error": "Invalid scenario ID"}
    path = resources.find_scenario_file(scenario_id)
    if path is not None:
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
        system = registry.for_rulebook(rulebook) if rulebook else None
        if system is not None:
            # 判定はルールブックのルールシステムに任せる（B-003）。def_original は、技能値を直接
            # 使う判定（is_skill）と能力値の生の判定（is_stat）で、判定の型を差し替える。
            judgment = system.general_check(result["total"], skill_value, rulebook,
                                            is_skill=is_skill, is_stat=is_stat)

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
    # 必須（B-030）。以前は既定が "def_original" だった。どのルールブックを使うかは呼ぶ側が決める。
    rulebook_id: str


_RULEBOOK_ID_REQUIRED = {"error": "rulebook_id is required"}


@router.post("/damage")
def damage_roll(req: DamageRollRequest):
    """ダメージ表を振る。ダメージ表はルールシステムの側の仕組みで、持たないルールシステムでは使えない
    （B-004・B-030。def_original の実装は `DefOriginal.damage_roll`）。"""
    if not req.rulebook_id:
        return dict(_RULEBOOK_ID_REQUIRED)
    rulebook = _load_rulebooks().get(req.rulebook_id, {})
    system = registry.for_rulebook(rulebook)
    roll_table = getattr(system, "damage_roll", None) if system is not None else None
    if not callable(roll_table):
        return {"error": "This rule system has no damage table"}
    return roll_table(rulebook)


class OpposedCheckRequest(BaseModel):
    attacker_roll: int
    attacker_skill: int
    defender_roll: int
    defender_skill: int
    # 必須（B-030）。以前は既定が "def_original" だった。
    rulebook_id: str


@router.post("/opposed-check")
def opposed_check_endpoint(req: OpposedCheckRequest):
    if not req.rulebook_id:
        return dict(_RULEBOOK_ID_REQUIRED)
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
