"""C-001: `api/routes/trpg.py` の今の挙動を固定する（判定の計算、/dice、/damage、/opposed-check、
ルールブックの一覧と取得と保存）。

ルールブックは `tests/fixtures/trpg/` の固定の写しを読む（`use_fixture_rulebooks`）。
"""

import json

import pytest

from char_helpers import FIXTURE_ROOT, assert_snapshot
from def_kari.api.routes import trpg as t

DEF_ORIGINAL = json.loads((FIXTURE_ROOT / "public" / "trpg_rules" / "def_original.json").read_text(encoding="utf-8"))


# ── compute_dice_judgment ─────────────────────────────────────────

def test_no_skill_value_means_no_judgment(use_fixture_rulebooks, fixed_dice):
    with fixed_dice(30):
        assert t.compute_dice_judgment("1d100", 0, "def_original")["judgment"] is None


def test_no_or_unknown_rulebook_means_no_judgment(use_fixture_rulebooks, fixed_dice):
    with fixed_dice(30, 30):
        assert t.compute_dice_judgment("1d100", 50, "")["judgment"] is None
        assert t.compute_dice_judgment("1d100", 50, "no_such_book")["judgment"] is None


def test_plain_uses_rulebook_condition(use_fixture_rulebooks, fixed_dice):
    with fixed_dice(30):
        out = t.compute_dice_judgment("1d100", 50, "def_original")
    assert out["result"] == {"notation": "1d100", "rolls": [30], "total": 30, "modifier": 0}
    assert out["judgment"]["judgment_type"] == "roll_lte_skill"
    assert out["judgment"]["success"] is True


def test_is_stat_uses_untrained_condition(use_fixture_rulebooks, fixed_dice):
    with fixed_dice(4):
        j = t.compute_dice_judgment("1d100", 8, "def_original", is_stat=True)["judgment"]
    assert (j["judgment_type"], j["judgment_value"], j["critical"]) == ("roll_lte_stat_x5", 40, True)


def test_is_skill_wins_over_is_stat(use_fixture_rulebooks, fixed_dice):
    with fixed_dice(30):
        j = t.compute_dice_judgment("1d100", 50, "def_original", is_skill=True, is_stat=True)["judgment"]
    assert (j["judgment_type"], j["judgment_value"]) == ("roll_lte_skill", 50)


def test_untrained_condition_default_is_stat_x5(rulebook_dirs, fixed_dice):
    public, _ = rulebook_dirs
    rb = {"id": "plain", "rule_system_name": "x", "dice_system": "1d100",
          "judgment": {"success_condition": "roll_lte_skill"}}
    (public / "trpg_rules" / "plain.json").write_text(json.dumps(rb), encoding="utf-8")
    with fixed_dice(10):
        j = t.compute_dice_judgment("1d100", 8, "plain", is_stat=True)["judgment"]
    assert (j["judgment_type"], j["judgment_value"]) == ("roll_lte_stat_x5", 40)


def test_compute_does_not_change_the_loaded_rulebook(use_fixture_rulebooks, fixed_dice):
    """is_skill / is_stat の差し替えは写しに対して行い、読んだルールブックは変えない。"""
    with fixed_dice(30):
        t.compute_dice_judgment("1d100", 8, "def_original", is_stat=True)
    assert t._load_rulebooks()["def_original"]["judgment"]["success_condition"] == "roll_lte_skill"


def test_compute_raises_on_bad_notation(use_fixture_rulebooks):
    with pytest.raises(ValueError):
        t.compute_dice_judgment("x", 50, "def_original")


# ── POST /dice ───────────────────────────────────────────────────

def test_dice_endpoint_shape(use_fixture_rulebooks, fixed_dice):
    with fixed_dice(30):
        out = t.dice_roll(t.DiceRollRequest(notation="1d100", skill_value=50, rulebook_id="def_original"))
    assert set(out) == {"notation", "rolls", "total", "modifier", "judgment"}
    assert (out["total"], out["judgment"]["success"]) == (30, True)


def test_dice_endpoint_bad_notation(use_fixture_rulebooks):
    assert t.dice_roll(t.DiceRollRequest(notation="x")) == {"error": "Invalid dice notation: 'x'"}


# ── POST /damage ─────────────────────────────────────────────────

def test_damage_entry(use_fixture_rulebooks, fixed_dice):
    entry = DEF_ORIGINAL["damage_mechanics"]["damage_table"]["entries"][0]
    with fixed_dice(1):
        out = t.damage_roll(t.DamageRollRequest(rulebook_id="def_original"))
    assert out == {"roll": 1, "result": "damage", "stat": entry["stat"],
                   "delta": entry["delta"], "flavor": entry["flavor"]}


def test_damage_instant_death_is_roll_14(use_fixture_rulebooks, fixed_dice):
    entry = next(e for e in DEF_ORIGINAL["damage_mechanics"]["damage_table"]["entries"] if e["roll"] == 14)
    with fixed_dice(14):
        out = t.damage_roll(t.DamageRollRequest(rulebook_id="def_original"))
    assert out == {"roll": 14, "result": "即死", "stat": None, "delta": None, "flavor": entry["flavor"]}


def test_damage_always_rolls_1d100(use_fixture_rulebooks, fixed_dice):
    """ルールブックの dice_system に関係なく 1d100 を振る（randbelow に渡る面の数）。"""
    seen = []
    with fixed_dice(1) as m:
        t.damage_roll(t.DamageRollRequest(rulebook_id="def_original"))
        seen = [c.args[0] for c in m.call_args_list]
    assert seen == [100]


def test_damage_default_rulebook_is_def_original(use_fixture_rulebooks, fixed_dice):
    """C-002: A章でわざと変える挙動（B-030 で API の既定の rulebook_id を外す）。"""
    assert t.DamageRollRequest().rulebook_id == "def_original"
    with fixed_dice(1):
        assert t.damage_roll(t.DamageRollRequest())["result"] == "damage"


def test_damage_unknown_rulebook(use_fixture_rulebooks, fixed_dice):
    with fixed_dice(7):
        assert t.damage_roll(t.DamageRollRequest(rulebook_id="nope")) == {"error": "Entry not found", "roll": 7}


# ── POST /opposed-check ──────────────────────────────────────────

def test_opposed_endpoint(use_fixture_rulebooks):
    out = t.opposed_check_endpoint(t.OpposedCheckRequest(
        attacker_roll=20, attacker_skill=50, defender_roll=20, defender_skill=50, rulebook_id="def_original"))
    assert (out["winner"], out["reason"]) == ("defender", "tie_defense_wins")


def test_opposed_default_rulebook_is_def_original(use_fixture_rulebooks):
    """C-002: A章でわざと変える挙動（B-030 で API の既定の rulebook_id を外す）。"""
    req = t.OpposedCheckRequest(attacker_roll=20, attacker_skill=50, defender_roll=30, defender_skill=50)
    assert req.rulebook_id == "def_original"
    assert t.opposed_check_endpoint(req)["winner"] == "attacker"


def test_opposed_unknown_rulebook(use_fixture_rulebooks):
    out = t.opposed_check_endpoint(t.OpposedCheckRequest(
        attacker_roll=1, attacker_skill=1, defender_roll=1, defender_skill=1, rulebook_id="nope"))
    assert out == {"error": "Rulebook 'nope' not found"}


# ── ルールブックの一覧・取得・保存 ────────────────────────────────────

def test_list_rulebooks(use_fixture_rulebooks):
    """blank_template は一覧に出さない。"""
    assert_snapshot("list_rulebooks.json", json.dumps(t.list_rulebooks(), ensure_ascii=False, indent=2) + "\n")


def test_list_rulebooks_dice_default(rulebook_dirs):
    public, _ = rulebook_dirs
    (public / "trpg_rules" / "nodice.json").write_text(json.dumps({"id": "nodice"}), encoding="utf-8")
    assert t.list_rulebooks() == {"rulebooks": [
        {"id": "nodice", "label": "nodice", "rule_system_name": "", "dice_system": "1d100", "private": False}]}


def test_get_rulebook_returns_raw_text(use_fixture_rulebooks):
    raw = (FIXTURE_ROOT / "public" / "trpg_rules" / "def_original.json").read_text(encoding="utf-8")
    assert t.get_rulebook("def_original") == {"content": raw, "id": "def_original"}


@pytest.mark.parametrize("bad", ["../def_original", "a/b", "a.b", "C:x"])
def test_get_rulebook_rejects_bad_id(use_fixture_rulebooks, bad):
    assert t.get_rulebook(bad) == {"error": "Invalid rulebook ID"}


def test_get_rulebook_missing(use_fixture_rulebooks):
    assert t.get_rulebook("nope") == {"error": "Rulebook 'nope' not found"}


def test_save_new_rulebook_goes_to_public(rulebook_dirs):
    """新しいルールブックは、読み込み先の1つ目（public）に保存される。"""
    public, private = rulebook_dirs
    content = json.dumps({"rule_system_name": "x", "dice_system": "1d6",
                          "judgment": {"success_condition": "roll_lte_skill"}})
    assert t.save_rulebook("newbook", t.SaveRulebookRequest(content=content)) == {"status": "ok", "id": "newbook"}
    assert (public / "trpg_rules" / "newbook.json").exists()
    assert not (private / "trpg_rules" / "newbook.json").exists()


def test_save_existing_rulebook_stays_where_it_is(rulebook_dirs):
    public, private = rulebook_dirs
    (private / "trpg_rules" / "mine.json").write_text("{}", encoding="utf-8")
    content = json.dumps({"rule_system_name": "x", "dice_system": "1d6",
                          "judgment": {"success_condition": "roll_lte_skill"}})
    t.save_rulebook("mine", t.SaveRulebookRequest(content=content))
    assert json.loads((private / "trpg_rules" / "mine.json").read_text(encoding="utf-8"))["dice_system"] == "1d6"
    assert not (public / "trpg_rules" / "mine.json").exists()


def test_save_rejects_invalid(rulebook_dirs):
    assert t.save_rulebook("x", t.SaveRulebookRequest(content="{")) ["error"].startswith("Invalid JSON: ")
    out = t.save_rulebook("x", t.SaveRulebookRequest(content="{}"))
    assert out["error"] == "Validation failed" and len(out["details"]) == 3
    assert t.save_rulebook("../x", t.SaveRulebookRequest(content="{}")) == {"error": "Invalid rulebook ID"}
