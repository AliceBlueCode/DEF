"""挙動を固定するテスト（キャラクタリゼーションテスト）の fixture。

要求仕様 C-001〜C-002（`DEF_マルチルールブック基盤_要求仕様_内部用.md`）。今の def_original の
挙動を、そのまま記録する。基盤の作り直し（A章）の後も、1件も変えずに通ることを条件にする。
わざと変える挙動（C-002 の一覧）のテストは、docstring を「C-002: A章でわざと変える挙動」で始める。

読み込み先の差し替え（`_set_dirs`）だけは、基盤で読み込みを1か所にまとめる（B-010）ときに
中身を書き換える。差し替える先が変わるだけで、各テストの期待値は変えない。
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from char_helpers import FIXTURE_ROOT


def _set_dirs(monkeypatch, public: Path, private: Path) -> None:
    """ルールブックとシナリオの読み込み先を、public と private の2か所に向ける。

    今の DEF は、`api/routes/trpg.py` と `gm/context_builder.py` の2か所に読み込み先を持つ
    （要求仕様 B-010 で1か所にまとめる予定）。両方を同じ置き場に向ける。
    """
    from def_kari.api.routes import trpg as trpg_routes
    from def_kari.gm import context_builder as cb

    rules = [public / "trpg_rules", private / "trpg_rules"]
    scenarios = [public / "trpg_scenarios", private / "trpg_scenarios"]
    monkeypatch.setattr(trpg_routes, "_RULEBOOK_DIRS", rules)
    monkeypatch.setattr(trpg_routes, "_SCENARIO_DIRS", scenarios)
    monkeypatch.setattr(cb, "_TRPG_RULEBOOK_DIRS", rules)
    monkeypatch.setattr(cb, "_PUBLIC_TRPG_RULEBOOK_DIRS", [public / "trpg_rules"])
    monkeypatch.setattr(cb, "_TRPG_SCENARIO_DIRS", scenarios)
    monkeypatch.setattr(cb, "_PUBLIC_TRPG_SCENARIO_DIRS", [public / "trpg_scenarios"])


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
