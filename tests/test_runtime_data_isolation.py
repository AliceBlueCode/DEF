"""テスト中に書き込むデータが、本物の data/ に行かないこと（2026-11-10）。

キャラの記憶（episodic）は、キャラのディレクトリの中の memory/ に書く。以前はテストでも
本物のキャラのディレクトリに書いていたため、公開キャラでセッションを終えるテストがあると、
テストの経験が本物のキャラの記憶に混ざり得た。記憶も def_kari.runtime_paths の切り替え口
（DEF_ISOLATED_DATA_DIR、リポジトリ直下の conftest.py が一時ディレクトリを設定）を通す。
"""

import os
from pathlib import Path

from def_kari.gm import memory
from def_kari.runtime_paths import REPO_DATA_DIR, writable_data_dir

CHAR_ID = "character_hanfei_001"  # git で管理している公開のサンプルキャラ


def _episodes(d: Path) -> set[str]:
    return {p.name for p in d.glob("*.json")} if d.exists() else set()


def test_isolated_data_dir_is_active_during_tests():
    assert os.environ.get("DEF_ISOLATED_DATA_DIR")
    assert writable_data_dir() != REPO_DATA_DIR


def test_episodic_memory_is_written_to_the_isolated_dir_not_the_repo():
    repo_dir = REPO_DATA_DIR / "public" / "characters" / CHAR_ID / "memory" / "episodic"
    before = _episodes(repo_dir)
    assert memory.save_episodic(CHAR_ID, {"summary": "テストの経験"}) is True

    isolated_dir = writable_data_dir() / "public" / "characters" / CHAR_ID / "memory" / "episodic"
    assert _episodes(isolated_dir), "the memory should be written under DEF_ISOLATED_DATA_DIR"
    assert _episodes(repo_dir) == before, "the real character's memory must not change"
    assert memory.load_episodic(CHAR_ID, limit=1)[-1]["summary"] == "テストの経験"
