"""架空のルールシステム `sample_grid` のテスト用プラグイン（マルチルールブック基盤 B-008）。

公開の DEF のテストで、プラグインの口（読み込み・登録・判定の切り替え・口のそろい方）を確かめる
ためだけのもの。実在のルールの中身は入れない。判定は「1d20 ＋ 値 ≧ 15 で成功」。
"""


class SampleGrid:
    id = "sample_grid"
    capabilities = frozenset()

    def __init__(self, api):
        self.api = api

    def validate_rulebook(self, data):
        return [] if data.get("rule_system_name") else ["sample_grid: rule_system_name is required"]

    def general_check(self, roll_total, value, rulebook, **options):
        total = roll_total + value
        return {"success": total >= 15, "roll": roll_total, "total": total, "judgment_type": "sample_grid_d20"}

    def allowed_skills(self, rulebook):
        return frozenset(rulebook.get("skills", []))

    def dice_notation(self, rulebook):
        return "1d20"

    def build_rule_context(self, rulebook, scenario, lang):
        return "[sample_grid] roll 1d20 + value, 15 or more succeeds"


def register(api):
    return SampleGrid(api)
