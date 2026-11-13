"""C-001: `gm/context_builder.build_trpg_context()` の今の出力を固定する（日本語・英語）。

B-003 で「AIに渡すルールの説明の組み立て」をルールシステムごとに差し替える。差し替えた後も、
def_original の卓では一字一句同じ文になることを、写し（snapshot）と比べて確かめる。
"""

import json

import pytest

from char_helpers import FIXTURE_ROOT, assert_snapshot
from def_kari.gm.context_builder import build_trpg_context

DEF_ORIGINAL = json.loads((FIXTURE_ROOT / "public" / "trpg_rules" / "def_original.json").read_text(encoding="utf-8"))

# シナリオは中身を問わないので、テスト用に書いたもの（実在のシナリオの写しは置かない）
_SCENARIO = {
    "title": "テストの卓",
    "synopsis": "あらすじの一文。",
    "scenes": [
        {"title": "最初の場面", "description": "場面の説明。"},
        {"title": "次の場面", "description": "使われない。"},
    ],
}


@pytest.mark.parametrize("lang", ["ja", "en"])
@pytest.mark.parametrize("with_scenario", [False, True])
def test_def_original_context(lang, with_scenario):
    text = build_trpg_context(DEF_ORIGINAL, _SCENARIO if with_scenario else None, lang)
    name = f"trpg_context_def_original_{'scenario' if with_scenario else 'none'}_{lang}.txt"
    assert_snapshot(name, text + "\n")


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_label_falls_back_to_raw_condition(lang):
    """日本語・英語の説明が無い判定の型は、型の名前がそのまま出る。"""
    text = build_trpg_context({"judgment": {"success_condition": "roll_lte_stat_x5"}}, None, lang)
    assert text.splitlines()[-1].endswith("roll_lte_stat_x5")


def test_empty_rulebook_defaults():
    assert build_trpg_context({}, None, "ja") == "【TRPGルールブック: 】\nダイスシステム: 1d100\n判定: ダイス目 ≤ スキル値で成功"
    assert build_trpg_context({}, None, "en") == "[TRPG Rulebook: ]\nDice system: 1d100\nJudgment: roll ≤ skill value = success"


def test_non_ja_language_is_english():
    assert build_trpg_context({}, None, "fr") == build_trpg_context({}, None, "en")


def test_scenario_without_scenes():
    text = build_trpg_context({}, {"title": "T"}, "ja")
    assert text.endswith("\n\n【シナリオ: T】")
