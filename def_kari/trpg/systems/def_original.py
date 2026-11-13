"""DEF(仮)TRPGシステム（def_original）の実装（マルチルールブック基盤 B-003、基本設計書 11.3）。

def_original は、プラグインとしては読み込まず、DEF の本体の中で同じ `RuleSystem` の形で実装する。
口（プラグインの口）は1つも持たないので、卓の進行などは DEF の今の処理がそのまま動く（11.4）。

今のところは、もとからある関数（`rule_engine.judge` など）を呼ぶだけで、挙動は変えていない。
def_original に固有の直書き（技能の一覧、1d100 など）をここへ移すのは B-030（手順3）。
"""

from copy import deepcopy

from def_kari.trpg import rule_engine


class DefOriginal:
    id = "def_original"
    capabilities: frozenset[str] = frozenset()

    def validate_rulebook(self, data: dict) -> list[str]:
        return rule_engine.validate_rulebook(data)

    def general_check(self, roll_total: int, value: int, rulebook: dict, **options) -> dict:
        """一般の判定。`is_skill`（技能値を直接使う）と `is_stat`（能力値の生の判定）を受ける。

        以前は `api/routes/trpg.py` の `compute_dice_judgment` の中にあった判定の型の差し替え。
        両方が真なら `is_skill` が優先する（挙動は tests/characterization が固定している）。
        """
        if options.get("is_skill"):
            rb = deepcopy(rulebook)
            rb.setdefault("judgment", {})["success_condition"] = "roll_lte_skill"
            return rule_engine.judge(roll_total, value, rb)
        if options.get("is_stat"):
            rb = deepcopy(rulebook)
            uc = rulebook.get("judgment", {}).get("untrained_success_condition", "roll_lte_stat_x5")
            rb.setdefault("judgment", {})["success_condition"] = uc
            return rule_engine.judge(roll_total, value, rb)
        return rule_engine.judge(roll_total, value, rulebook)

    def allowed_skills(self, rulebook: dict) -> frozenset[str]:
        from def_kari.gm.judgment_planner import _DEF_ALLOWED_SKILLS
        return _DEF_ALLOWED_SKILLS

    def dice_notation(self, rulebook: dict) -> str:
        return rulebook.get("dice_system", "1d100")

    def build_rule_context(self, rulebook: dict, scenario: dict | None, lang: str) -> str:
        from def_kari.gm.context_builder import build_trpg_context
        return build_trpg_context(rulebook, scenario, lang)
