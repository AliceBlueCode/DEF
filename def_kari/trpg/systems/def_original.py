"""DEF(仮)TRPGシステム（def_original）の実装（マルチルールブック基盤 B-003、基本設計書 11.3）。

def_original は、プラグインとしては読み込まず、DEF の本体の中で同じ `RuleSystem` の形で実装する。
口（プラグインの口）は1つも持たないので、卓の進行などは DEF の今の処理がそのまま動く（11.4）。

今のところは、もとからある関数（`rule_engine.judge` など）を呼ぶだけで、挙動は変えていない。
def_original に固有の直書き（技能の一覧、1d100 など）をここへ移すのは B-030（手順3）。
"""

from copy import deepcopy

from def_kari.trpg import rule_engine

# ── def_original の技能と能力値（以前は gm/judgment_planner.py に直書き。B-030 で移した） ──
# DEF 定義スキルのホワイトリスト
ALLOWED_SKILLS: frozenset[str] = frozenset({
    "察知", "調査", "医学", "博学", "推理", "解読", "記憶", "操縦",
    "説得", "欺瞞", "威圧", "魅了", "意志力", "共感", "煽動", "危機察知",
    "回避", "格闘", "射撃", "隠密", "運動", "耐久", "治療", "運転",
    "社交", "情報収集", "調達", "偽装", "生存", "追跡", "潜入", "製作",
    "思考", "情動", "身体", "環境",
})

# CoC / 他システム由来の誤りを DEF スキルに補正するマップ
SKILL_CORRECTION_MAP: dict[str, str] = {
    "目星": "察知", "聞き耳": "察知", "斥候": "察知", "観察": "察知",
    "心理学": "共感", "精神分析": "共感",
    "説得力": "説得", "交渉": "説得", "弁論": "説得",
    "機械修理": "製作", "機械工作": "製作", "電気修理": "製作",
    "製造": "製作", "工作": "製作",
    "忍び歩き": "隠密", "潜伏": "隠密",
    "水泳": "運動", "跳躍": "運動", "登攀": "運動", "登山": "運動",
    "図書館": "調査", "図書館使用": "調査", "文献調査": "調査",
    "応急手当": "治療", "医療": "医学", "外科": "医学",
    "ナビゲート": "操縦", "操縦技術": "操縦", "航法": "操縦",
    "追跡術": "追跡", "尾行": "追跡",
    "変装": "偽装",
    "天文学": "博学", "歴史": "博学", "地質学": "博学", "考古学": "博学",
    "射撃技術": "射撃", "狙撃": "射撃",
    "格闘技": "格闘", "武道": "格闘", "近接": "格闘",
    "ハッキング": "解読", "コンピュータ": "解読", "電子機器": "解読",
    "回避技術": "回避",
    "サバイバル": "生存",
    "隠蔽": "隠密",
    "威圧力": "威圧",
}


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

    # 他のシステムの技能名を def_original の技能へ直す表（judgment_planner が使う）
    skill_corrections = SKILL_CORRECTION_MAP

    def allowed_skills(self, rulebook: dict) -> frozenset[str]:
        return ALLOWED_SKILLS

    def judgment_system_prompt(self, route: str, is_ja: bool, char_names_str: str) -> str:
        """判定の要否を LLM に決めさせるときのシステムプロンプト（`gm/judgment_planner.py`）。

        判定の要否を LLM が決めるのは def_original の仕組みで、このメソッドを持つルールシステムの
        卓でだけ使う（B-031）。文は、以前 judgment_planner に直書きされていたものと一字一句同じ
        （tests/characterization のプロンプトの写しで確かめている）。`route` は "tools" か "json"。
        """
        if route == "tools":
            return (
                "あなたはTRPGの判定要否決定システムです。直近の会話を読み、"
                "探索者がスキルを使った・使うべき場面があればpropose_checksを呼び出してください。"
                f"\n探索者（このリストの名前のみ使用）：{char_names_str}"
                "\n使用できるスキル名（これ以外は絶対禁止）："
                "察知・調査・医学・博学・推理・解読・記憶・操縦・説得・欺瞞・威圧・魅了・意志力・共感・煽動・危機察知・"
                "回避・格闘・射撃・隠密・運動・耐久・治療・運転・社交・情報収集・調達・偽装・生存・追跡・潜入・製作、"
                "またはステータス名（思考・情動・身体・環境）"
            ) if is_ja else (
                "You are a TRPG judgment-necessity decider. Read the recent conversation and call "
                "propose_checks if any investigator's action calls for a skill check right now."
                f"\nInvestigators (use only these names): {char_names_str}"
                "\nOnly these exact skill names allowed: "
                "察知,調査,医学,博学,推理,解読,記憶,操縦,説得,欺瞞,威圧,魅了,意志力,共感,煽動,危機察知,"
                "回避,格闘,射撃,隠密,運動,耐久,治療,運転,社交,情報収集,調達,偽装,生存,追跡,潜入,製作,"
                "or stat names: 思考,情動,身体,環境"
            )
        return (
            "あなたはTRPGの判定要否決定システムです。直近の会話を読み、"
            "探索者がスキルを使った・使うべき場面があれば対象キャラ名とスキル名をJSONで返してください。"
            "「探索者たち」のようにまとめて書かれている場合は、場面に最も関わっているキャラを1〜2名選んでください。"
            f"\n探索者（このリストの名前のみ使用）：{char_names_str}"
            "\n使用できるスキル名（これ以外は絶対禁止・機械工作などCoCの技能名も禁止）："
            "察知・調査・医学・博学・推理・解読・記憶・操縦・説得・欺瞞・威圧・魅了・意志力・共感・煽動・危機察知・"
            "回避・格闘・射撃・隠密・運動・耐久・治療・運転・社交・情報収集・調達・偽装・生存・追跡・潜入・製作、"
            "またはステータス名（思考・情動・身体・環境）"
            "\nスキル目安：人の言動・感情を読む→共感、物や場所を観察する→察知、危険や気配を感じる→危機察知、説得・交渉→説得、機器操作→操縦、修理・製作→製作、走る・跳ぶ→運動"
            "\nなければ {\"judgments\":[]} を返してください。"
            "\n必ずJSONのみ返してください（コードブロック不要）。"
            "\n形式：{\"judgments\":[{\"character\":\"キャラ名\",\"skill\":\"スキル名\"}]}"
        ) if is_ja else (
            "You are a TRPG judgment-necessity decider. Read the recent conversation and return JSON listing "
            "any skill checks that should occur right now. "
            "If 'investigators' is used collectively, pick 1-2 most relevant characters."
            f"\nInvestigators (use only these names): {char_names_str}"
            "\nOnly these exact skill names allowed (no inventing names like 機械工作 etc.): "
            "察知,調査,医学,博学,推理,解読,記憶,操縦,説得,欺瞞,威圧,魅了,意志力,共感,煽動,危機察知,"
            "回避,格闘,射撃,隠密,運動,耐久,治療,運転,社交,情報収集,調達,偽装,生存,追跡,潜入,製作,"
            "or stat names: 思考,情動,身体,環境"
            "\nSkill guide: reading emotions/people→共感, observing objects/places→察知, "
            "sensing danger/presence→危機察知, persuading→説得, operating machinery→操縦, crafting/repairing→製作, "
            "running/jumping→運動, avoiding danger→回避"
            "\nIf none needed, return {\"judgments\":[]}."
            "\nReturn JSON only, no code blocks."
            "\nFormat: {\"judgments\":[{\"character\":\"name\",\"skill\":\"skill\"}]}"
        )

    def damage_roll(self, rulebook: dict) -> dict:
        """ダメージ表を振る（`POST /api/trpg/damage`。以前は API に直書きされていた。B-030）。

        ダメージ表は `damage_mechanics.damage_table.entries`（出目 → 能力値と増減）。項目に
        `result`（例: 「即死」）があり `stat` が無ければ、その出目は致命の結果で、`"result": "fatal"` と、表示用の
        言葉 `label`（ルールブックのデータの `result` の値）を返す。画面はこの言葉をそのまま出す。
        """
        result = rule_engine.roll_dice(self.dice_notation(rulebook))
        roll_val = result["total"]
        entries = rulebook.get("damage_mechanics", {}).get("damage_table", {}).get("entries", [])
        entry = next((e for e in entries if e.get("roll") == roll_val), None)
        if not entry:
            return {"error": "Entry not found", "roll": roll_val}
        # 致命の結果は「result があり stat の無い項目」（ルールブックの書き方の決まり。実装レビュー2の🟢）。
        # result があっても stat のある項目は、能力値の増減として扱う
        if entry.get("result") and not entry.get("stat"):
            return {
                "roll": roll_val,
                "result": "fatal",
                "label": entry["result"],
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

    def dice_notation(self, rulebook: dict) -> str:
        return rulebook.get("dice_system", "1d100")

    def build_rule_context(self, rulebook: dict, scenario: dict | None, lang: str) -> str:
        """ルールブック・シナリオを、システムプロンプト用の文に展開する（以前の
        `context_builder.build_trpg_context` の中身。B-030 で移した。文は tests/characterization の写しで固定）。"""
        _is_ja = lang == "ja"
        parts = []

        system_name = rulebook.get("rule_system_name", "")
        world = rulebook.get("world_setting", "")
        dice_sys = self.dice_notation(rulebook)
        judgment = rulebook.get("judgment", {})
        golden = rulebook.get("golden_rule", "")

        if _is_ja:
            parts.append(f"【TRPGルールブック: {system_name}】")
            if world:
                parts.append(f"世界観: {world}")
            parts.append(f"ダイスシステム: {dice_sys}")
            cond = judgment.get("success_condition", "roll_lte_skill")
            cond_label = {
                "roll_lte_skill": "ダイス目 ≤ スキル値で成功",
                "roll_gte_skill": "ダイス目 ≥ スキル値で成功",
            }.get(cond, cond)
            parts.append(f"判定: {cond_label}")
            if golden:
                parts.append(f"ゴールデンルール: {golden}")
        else:
            parts.append(f"[TRPG Rulebook: {system_name}]")
            if world:
                parts.append(f"World: {world}")
            parts.append(f"Dice system: {dice_sys}")
            cond = judgment.get("success_condition", "roll_lte_skill")
            cond_label = {
                "roll_lte_skill": "roll ≤ skill value = success",
                "roll_gte_skill": "roll ≥ skill value = success",
            }.get(cond, cond)
            parts.append(f"Judgment: {cond_label}")
            if golden:
                parts.append(f"Golden rule: {golden}")

        if scenario:
            title = scenario.get("title", "")
            synopsis = scenario.get("synopsis", "")
            current_scene = scenario.get("scenes", [{}])[0] if scenario.get("scenes") else {}
            scene_title = current_scene.get("title", "")
            scene_desc = current_scene.get("description", "")
            if _is_ja:
                parts.append(f"\n【シナリオ: {title}】")
                if synopsis:
                    parts.append(f"概要: {synopsis}")
                if scene_title:
                    parts.append(f"現在の場面: {scene_title}")
                if scene_desc:
                    parts.append(scene_desc)
            else:
                parts.append(f"\n[Scenario: {title}]")
                if synopsis:
                    parts.append(f"Synopsis: {synopsis}")
                if scene_title:
                    parts.append(f"Current scene: {scene_title}")
                if scene_desc:
                    parts.append(scene_desc)

        return "\n".join(parts)
