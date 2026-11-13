"""C-001: `trpg/rule_engine.py` の今の挙動を固定する（ダイス、判定、対抗判定、ルールブックの検証）。

期待値は、2026-11-13（950134a）のコードを読んで、式どおりに書いたもの。
"""

import copy
import json

import pytest

from char_helpers import FIXTURE_ROOT
from def_kari.trpg.rule_engine import (
    _get_dice_sides,
    judge,
    opposed_check,
    roll_dice,
    validate_rulebook,
)


@pytest.fixture(scope="module")
def def_original():
    path = FIXTURE_ROOT / "public" / "trpg_rules" / "def_original.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def stat_x5(def_original):
    """能力値の生判定（`compute_dice_judgment` の is_stat と同じ差し替え）。"""
    rb = copy.deepcopy(def_original)
    rb["judgment"]["success_condition"] = "roll_lte_stat_x5"
    return rb


def _j(roll, skill, rb):
    r = judge(roll, skill, rb)
    return (r["success"], r["critical"], r["fumble"], r["judgment_value"])


# ── ダイス ──────────────────────────────────────────────────────

def test_roll_dice_result_shape(fixed_dice):
    with fixed_dice(3, 5):
        assert roll_dice("2d6") == {"notation": "2d6", "rolls": [3, 5], "total": 8, "modifier": 0}


@pytest.mark.parametrize("notation,faces,total,modifier", [
    ("1d6+3", (4,), 7, 3),
    ("1d6-2", (4,), 2, -2),
    ("1D20", (20,), 20, 0),
])
def test_roll_dice_modifier_and_case(fixed_dice, notation, faces, total, modifier):
    with fixed_dice(*faces):
        r = roll_dice(notation)
    assert (r["total"], r["modifier"], r["notation"]) == (total, modifier, notation)


def test_roll_dice_strips_spaces(fixed_dice):
    with fixed_dice(2):
        assert roll_dice("  1d6 ")["notation"] == "1d6"


@pytest.mark.parametrize("notation", ["d6", "0d6", "101d6", "1d1", "1d1001", "abc", "1d6+", ""])
def test_roll_dice_rejects(notation):
    with pytest.raises(ValueError):
        roll_dice(notation)


def test_dice_sides_default_is_100():
    assert _get_dice_sides({}) == 100
    assert _get_dice_sides({"dice_system": "bad"}) == 100
    assert _get_dice_sides({"dice_system": "2d6"}) == 6


# ── 判定: roll_lte_skill（def_original の既定） ──────────────────────

@pytest.mark.parametrize("roll,expected", [
    (5, (True, True, False, 50)),     # クリティカルは 50 // 10 = 5 以下
    (6, (True, False, False, 50)),
    (50, (True, False, False, 50)),
    (51, (False, False, False, 50)),
    (99, (False, False, False, 50)),
    (100, (False, False, True, 50)),  # fumble_threshold 100
])
def test_lte_skill_def_original(def_original, roll, expected):
    assert _j(roll, 50, def_original) == expected


def test_lte_skill_small_skill_critical_is_at_least_1(def_original):
    assert _j(1, 9, def_original)[1] is True
    assert _j(2, 9, def_original)[1] is False


def test_lte_skill_success_wins_over_fumble(def_original):
    """技能値100で出目100: 成功し、ファンブルにはならない（fumble は失敗のときだけ）。"""
    assert _j(100, 100, def_original) == (True, False, False, 100)


def test_judge_result_shape(def_original):
    assert judge(30, 50, def_original) == {
        "success": True, "critical": False, "fumble": False,
        "roll": 30, "skill_value": 50, "judgment_value": 50, "judgment_type": "roll_lte_skill",
    }


# ── 判定: roll_lte_stat_x5（能力値の生判定） ───────────────────────────

@pytest.mark.parametrize("roll,expected", [
    (4, (True, True, False, 40)),     # 8 × 5 = 40、クリティカルは 40 // 10 = 4 以下
    (5, (True, False, False, 40)),
    (40, (True, False, False, 40)),
    (41, (False, False, False, 40)),
    (100, (False, False, True, 40)),
])
def test_stat_x5(stat_x5, roll, expected):
    assert _j(roll, 8, stat_x5) == expected


# ── 判定: roll_gte_skill（1d20 の架空のルールブック） ──────────────────

_GTE = {"dice_system": "1d20", "judgment": {"success_condition": "roll_gte_skill"}}


@pytest.mark.parametrize("roll,expected", [
    (19, (True, True, False, 12)),    # クリティカルは 20 - max(1, 12 // 5) + 1 = 19 以上
    (18, (True, False, False, 12)),
    (12, (True, False, False, 12)),
    (11, (False, False, False, 12)),
    (1, (False, False, False, 12)),   # 既定のファンブルは 16 - 20 + 1 = -3 以下で、起きない
])
def test_gte_skill(roll, expected):
    assert _j(roll, 12, _GTE) == expected


# ── 判定: roll_lte_target と、判定の定義が無いとき ─────────────────────

def test_lte_target_falls_back_to_plain_lte():
    """`validate_rulebook` は許すが、`judge()` に分岐が無く、既定の処理に落ちる。"""
    rb = {"judgment": {"success_condition": "roll_lte_target"}}
    assert judge(1, 10, rb) == {
        "success": True, "critical": False, "fumble": False,
        "roll": 1, "skill_value": 10, "judgment_value": 10, "judgment_type": "roll_lte_target",
    }
    assert _j(11, 10, rb) == (False, False, False, 10)


def test_missing_judgment_defaults():
    """判定の定義が無ければ roll_lte_skill。1d100 の既定のファンブルは 96。"""
    assert judge(50, 50, {})["judgment_type"] == "roll_lte_skill"
    assert _j(96, 50, {}) == (False, False, True, 50)
    assert _j(95, 50, {}) == (False, False, False, 50)


# ── 対抗判定 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("atk,dfn,winner,reason,achs", [
    ((1, 50), (2, 50), "defender", "dual_critical_defense_wins", (49, 48)),
    ((3, 50), (30, 50), "attacker", "attacker_critical", (47, 20)),
    ((30, 50), (3, 50), "defender", "defender_critical", (20, 47)),
    ((20, 50), (30, 50), "attacker", "higher_achievement", (30, 20)),
    ((30, 50), (20, 50), "defender", "higher_achievement", (20, 30)),
    ((20, 50), (20, 50), "defender", "tie_defense_wins", (30, 30)),
    ((70, 50), (60, 50), "defender", "higher_achievement", (-20, -10)),
])
def test_opposed_check(def_original, atk, dfn, winner, reason, achs):
    r = opposed_check(atk[0], atk[1], dfn[0], dfn[1], def_original)
    assert (r["winner"], r["reason"]) == (winner, reason)
    assert (r["attacker_achievement"], r["defender_achievement"]) == achs
    assert set(r) == {"attacker_achievement", "defender_achievement",
                      "attacker_critical", "defender_critical", "winner", "reason"}


# ── ルールブックの検証 ─────────────────────────────────────────────

def test_validate_def_original_is_valid(def_original):
    assert validate_rulebook(def_original) == []


def test_validate_not_a_dict():
    assert validate_rulebook([]) == ["rulebook must be a JSON object"]


def test_validate_missing_fields():
    assert set(validate_rulebook({})) == {
        "missing required field: 'rule_system_name'",
        "missing required field: 'dice_system'",
        "missing required field: 'judgment'",
    }


def test_validate_bad_dice_and_condition():
    errs = validate_rulebook({"rule_system_name": "x", "dice_system": "d6",
                              "judgment": {"success_condition": "nope"}})
    assert errs == ["invalid dice_system: 'd6' (expected e.g. '1d100')",
                    "unknown success_condition: 'nope'"]


def test_validate_empty_condition_is_unknown():
    errs = validate_rulebook({"rule_system_name": "x", "dice_system": "1d6", "judgment": {}})
    assert errs == ["unknown success_condition: ''"]


def test_validate_accepts_roll_lte_target():
    """C-002: A章でわざと変える挙動（B-032 で許す一覧から外す）。"""
    assert validate_rulebook({"rule_system_name": "x", "dice_system": "1d20",
                              "judgment": {"success_condition": "roll_lte_target"}}) == []
