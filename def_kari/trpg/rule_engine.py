"""Rule Engine: deterministic rule interpretation for TRPG sessions.

All judgment (success/fail, critical, fumble) is handled here — never by LLM.
"""

import secrets
import re
from typing import Any


# ── ダイス ──────────────────────────────────────────────────────

_DICE_RE = re.compile(r'^(\d+)d(\d+)([+-]\d+)?$', re.IGNORECASE)


def roll_dice(notation: str) -> dict:
    """Parse and roll a dice notation like '1d100', '2d6', '1d6+3'.

    Returns:
        {
            "notation": "2d6",
            "rolls": [3, 5],
            "total": 8,
            "modifier": 0,
        }
    Raises:
        ValueError: if notation is invalid or out of range.
    """
    m = _DICE_RE.match(notation.strip())
    if not m:
        raise ValueError(f"Invalid dice notation: {notation!r}")

    count = int(m.group(1))
    sides = int(m.group(2))
    modifier = int(m.group(3)) if m.group(3) else 0

    if count < 1 or count > 100:
        raise ValueError(f"Dice count must be 1-100, got {count}")
    if sides < 2 or sides > 1000:
        raise ValueError(f"Dice sides must be 2-1000, got {sides}")

    rolls = [secrets.randbelow(sides) + 1 for _ in range(count)]
    total = sum(rolls) + modifier

    return {
        "notation": notation.strip(),
        "rolls": rolls,
        "total": total,
        "modifier": modifier,
    }


# ── 成否判定 ─────────────────────────────────────────────────────

def judge(roll_total: int, skill_value: int, rulebook: dict) -> dict:
    """Determine success/failure based on rulebook judgment rules.

    Supported judgment types:
        "roll_lte_skill"  : roll <= skill → success  (CoC, DEF original)
        "roll_gte_skill"  : roll >= skill → success  (some systems)
        "roll_lte_target" : roll <= target (fixed value in rulebook)

    Returns:
        {
            "success": bool,
            "critical": bool,
            "fumble": bool,
            "roll": int,
            "skill_value": int,
            "judgment_type": str,
        }
    """
    judgment = rulebook.get("judgment", {})
    jtype = judgment.get("success_condition", "roll_lte_skill")

    dice_sides = _get_dice_sides(rulebook)
    critical_threshold = judgment.get("critical_threshold", max(1, skill_value // 5))
    fumble_threshold = judgment.get("fumble_threshold", min(dice_sides, 96 if dice_sides == 100 else dice_sides - 4))

    if jtype == "roll_lte_skill":
        success = roll_total <= skill_value
        critical = roll_total <= critical_threshold
        fumble = roll_total >= fumble_threshold
    elif jtype == "roll_gte_skill":
        success = roll_total >= skill_value
        critical = roll_total >= (dice_sides - critical_threshold + 1)
        fumble = roll_total <= (fumble_threshold - dice_sides + 1)
    else:
        success = roll_total <= skill_value
        critical = False
        fumble = False

    return {
        "success": success,
        "critical": critical and success,
        "fumble": fumble and not success,
        "roll": roll_total,
        "skill_value": skill_value,
        "judgment_type": jtype,
    }


def _get_dice_sides(rulebook: dict) -> int:
    notation = rulebook.get("dice_system", "1d100")
    m = _DICE_RE.match(notation)
    return int(m.group(2)) if m else 100


# ── 対抗判定 ─────────────────────────────────────────────────────

def opposed_check(
    attacker_roll: int,
    attacker_skill: int,
    defender_roll: int,
    defender_skill: int,
    rulebook: dict,
) -> dict:
    """Opposed check: achievement value = skill - roll. Higher wins.

    Dual critical → defender wins (per DEF original rules).

    Returns:
        {
            "attacker_achievement": int,
            "defender_achievement": int,
            "attacker_critical": bool,
            "defender_critical": bool,
            "winner": "attacker" | "defender",
            "reason": str,
        }
    """
    atk_result = judge(attacker_roll, attacker_skill, rulebook)
    def_result = judge(defender_roll, defender_skill, rulebook)

    atk_ach = attacker_skill - attacker_roll
    def_ach = defender_skill - defender_roll

    atk_crit = atk_result["critical"]
    def_crit = def_result["critical"]

    if atk_crit and def_crit:
        winner = "defender"
        reason = "dual_critical_defense_wins"
    elif atk_crit and not def_crit:
        winner = "attacker"
        reason = "attacker_critical"
    elif def_crit and not atk_crit:
        winner = "defender"
        reason = "defender_critical"
    elif atk_ach > def_ach:
        winner = "attacker"
        reason = "higher_achievement"
    elif def_ach > atk_ach:
        winner = "defender"
        reason = "higher_achievement"
    else:
        winner = "defender"
        reason = "tie_defense_wins"

    return {
        "attacker_achievement": atk_ach,
        "defender_achievement": def_ach,
        "attacker_critical": atk_crit,
        "defender_critical": def_crit,
        "winner": winner,
        "reason": reason,
    }


# ── ルールブック検証 ──────────────────────────────────────────────

RULEBOOK_REQUIRED_FIELDS = {"rule_system_name", "dice_system", "judgment"}

def validate_rulebook(data: Any) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors = []
    if not isinstance(data, dict):
        return ["rulebook must be a JSON object"]
    for f in RULEBOOK_REQUIRED_FIELDS:
        if f not in data:
            errors.append(f"missing required field: {f!r}")
    if "dice_system" in data:
        if not _DICE_RE.match(str(data["dice_system"])):
            errors.append(f"invalid dice_system: {data['dice_system']!r} (expected e.g. '1d100')")
    if "judgment" in data and isinstance(data["judgment"], dict):
        sc = data["judgment"].get("success_condition", "")
        valid_conditions = {"roll_lte_skill", "roll_gte_skill", "roll_lte_target"}
        if sc not in valid_conditions:
            errors.append(f"unknown success_condition: {sc!r}")
    return errors
