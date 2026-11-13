"""挙動を固定するテストの共通の関数（fixture 以外）。

`conftest.py` から import すると、リポジトリ直下の `conftest.py` と名前がぶつかるので、ここに分ける。
"""

import os
from pathlib import Path

import pytest

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
FIXTURE_ROOT = Path(__file__).parent.parent / "fixtures" / "trpg"

# C-002 の一覧（A章でわざと変える挙動）に当たるテストは、docstring を
# 「C-002: A章でわざと変える挙動（B-xxx ...）」で始める。`grep -rn "C-002:" tests/characterization` で一覧できる。


def assert_snapshot(name: str, text: str) -> None:
    """`snapshots/<name>` と一字一句同じかを確かめる。

    写しが無いときは、環境変数 `DEF_UPDATE_SNAPSHOTS=1` のときだけ作る（それ以外は失敗させる）。
    わざと挙動を変えたときは、写しを消して作り直し、変えた理由をコミットとPRに書く（C-002）。
    """
    path = SNAPSHOT_DIR / name
    if not path.exists():
        if os.environ.get("DEF_UPDATE_SNAPSHOTS") == "1":
            path.write_text(text, encoding="utf-8", newline="\n")
            return
        pytest.fail(f"snapshot が無い: {path}（DEF_UPDATE_SNAPSHOTS=1 で作る）")
    assert text == path.read_text(encoding="utf-8"), f"snapshot と違う: {name}"
