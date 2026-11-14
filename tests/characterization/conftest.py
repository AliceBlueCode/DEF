"""挙動を固定するテスト（キャラクタリゼーションテスト）の fixture。

要求仕様 C-001〜C-002（`DEF_マルチルールブック基盤_要求仕様_内部用.md`）。今の def_original の
挙動を、そのまま記録する。基盤の作り直し（A章）の後も、1件も変えずに通ることを条件にする。
わざと変える挙動（C-002 の一覧）のテストは、docstring を「C-002: A章でわざと変える挙動」で始める。

読み込み先の差し替え（`_set_dirs`）だけは、基盤で読み込みを1か所にまとめた（B-010、2026-11-13）ときに
中身を書き換えた。差し替える先が変わっただけで、各テストの期待値は変えていない。
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from char_helpers import FIXTURE_ROOT


def _set_dirs(monkeypatch, public: Path, private: Path) -> None:
    """ルールブックとシナリオの読み込み先を、public と private の2か所に向ける。

    読み込み先は `def_kari/trpg/resources.py` の1か所にある（B-010。2026-11-13 までは
    `api/routes/trpg.py` と `gm/context_builder.py` の2か所にあり、両方を差し替えていた）。
    """
    from def_kari.trpg import resources

    # 外部の置き場所（プラグインのデータ、TRPG_RULEBOOK_REPO_PATHS。B-011）は見ない。開発機の .env の
    # 設定で、固定したい挙動が変わらないようにするため（2026-11-14、手順4a で足した）。
    monkeypatch.setattr(resources, "_external_sources", lambda: [])
    monkeypatch.setattr(resources, "RULEBOOK_DIRS", [public / "trpg_rules", private / "trpg_rules"])
    monkeypatch.setattr(resources, "PUBLIC_RULEBOOK_DIRS", [public / "trpg_rules"])
    monkeypatch.setattr(resources, "SCENARIO_DIRS", [public / "trpg_scenarios", private / "trpg_scenarios"])
    monkeypatch.setattr(resources, "PUBLIC_SCENARIO_DIRS", [public / "trpg_scenarios"])


@pytest.fixture
def use_fixture_rulebooks(monkeypatch):
    """`tests/fixtures/trpg/` の固定の写しを読ませる（C-005）。"""
    _set_dirs(monkeypatch, FIXTURE_ROOT / "public", FIXTURE_ROOT / "private")


@pytest.fixture
def rulebook_dirs(monkeypatch, tmp_path):
    """空の public と private を作って読ませる。読み込みの順番を確かめるテスト用。"""
    public = tmp_path / "public"
    private = tmp_path / "private"
    for base in (public, private):
        (base / "trpg_rules").mkdir(parents=True)
        (base / "trpg_scenarios").mkdir(parents=True)
    _set_dirs(monkeypatch, public, private)
    return public, private


@pytest.fixture
def fixed_dice():
    """`roll_dice` の出目を、渡した順に固定する（例: `with fixed_dice(12, 7): roll_dice("2d20")` →
    rolls は [12, 7]）。B-005 の乱数の口はまだ無いので、`secrets.randbelow` を差し替える
    （`roll_dice` は `randbelow(sides) + 1` を出目にするので、1 を引いて返す）。
    """
    def _fixed(*faces: int):
        it = iter(faces)
        return patch("def_kari.trpg.rule_engine.secrets.randbelow", side_effect=lambda _n: next(it) - 1)
    return _fixed
