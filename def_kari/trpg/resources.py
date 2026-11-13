"""TRPG のルールブックとシナリオの置き場所と読み込み（1か所にまとめたもの）。

以前は、読み込み先が `api/routes/trpg.py`（一覧・取得・保存）と `gm/context_builder.py`
（セッションで使う読み込み）の2か所に重ねて書かれていた。置き場所を足す（外部のリポジトリ、
プラグインのデータ）前に、ここへ集めた（2026-11-13、マルチルールブック基盤 B-010）。

このモジュールは、集める前の挙動をそのまま引き継ぐ。挙動は `tests/characterization/` が固定している:

- 置き場所は public → private の順。
- ID を指定した読み込み（`load_rulebook` など）は、先に見つかった方を使う。ファイル名が ID。
- 一覧（`all_rulebooks` など）は、JSON の `id`（無ければファイル名）を ID とし、後から読んだ方で
  上書きする。同じ ID が public と private の両方にあると、ID を指定した読み込みとは勝つ方が逆になる。
  この食い違いは、読み込み先を足すとき（B-011）に直す。

読み込み先の一覧（`RULEBOOK_DIRS` など）は、呼ばれるたびにこのモジュールの値を見る。テストは
この値を差し替える。
"""

import json
import re
from pathlib import Path

_BASE = Path(__file__).parent.parent.parent

RULEBOOK_DIRS: list[Path] = [
    _BASE / "data" / "public" / "trpg_rules",
    _BASE / "data" / "private" / "trpg_rules",
]
PUBLIC_RULEBOOK_DIRS: list[Path] = [_BASE / "data" / "public" / "trpg_rules"]
SCENARIO_DIRS: list[Path] = [
    _BASE / "data" / "public" / "trpg_scenarios",
    _BASE / "data" / "private" / "trpg_scenarios",
]
PUBLIC_SCENARIO_DIRS: list[Path] = [_BASE / "data" / "public" / "trpg_scenarios"]

# 8.26対策: rulebook_id / scenario_id は、クライアントの入力をそのままファイル名に使う。
# ID の許可リストと、パスを解決した後に置き場所の内側にあるかの確認の二重で、パストラバーサルと
# 絶対パスの注入を防ぐ。
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def is_safe_id(resource_id: str) -> bool:
    return bool(resource_id) and bool(SAFE_ID_RE.match(resource_id))


def load_resource(resource_id: str, dirs: list[Path]) -> dict:
    """`dirs` を順に探し、最初に読めた `{resource_id}.json` を返す。無ければ空の dict。"""
    if not is_safe_id(resource_id):
        return {}
    for d in dirs:
        base = d.resolve()
        candidate = (d / f"{resource_id}.json").resolve()
        try:
            if not candidate.is_relative_to(base):
                continue
        except ValueError:
            continue
        if candidate.exists():
            try:
                return json.loads(candidate.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def load_rulebook(rulebook_id: str, public_only: bool = False) -> dict:
    return load_resource(rulebook_id, PUBLIC_RULEBOOK_DIRS if public_only else RULEBOOK_DIRS)


def load_scenario(scenario_id: str, public_only: bool = False) -> dict:
    return load_resource(scenario_id, PUBLIC_SCENARIO_DIRS if public_only else SCENARIO_DIRS)


def _load_all(dirs: list[Path]) -> dict:
    """`dirs` のすべての JSON を読み、ID → 中身 の dict を返す（後から読んだ方で上書き）。"""
    found: dict = {}
    for d in dirs:
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix == ".json" and f.name != ".gitkeep":
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        found[data.get("id", f.stem)] = data
                    except (json.JSONDecodeError, OSError):
                        pass
    return found


def all_rulebooks() -> dict:
    return _load_all(RULEBOOK_DIRS)


def all_scenarios() -> dict:
    return _load_all(SCENARIO_DIRS)


def _find_file(resource_id: str, dirs: list[Path]) -> Path | None:
    """`{resource_id}.json` がある最初の置き場所のパス。ID の確かめは呼ぶ側で済ませておく。"""
    for d in dirs:
        path = d / f"{resource_id}.json"
        if path.exists():
            return path
    return None


def find_rulebook_file(rulebook_id: str) -> Path | None:
    return _find_file(rulebook_id, RULEBOOK_DIRS)


def find_scenario_file(scenario_id: str) -> Path | None:
    return _find_file(scenario_id, SCENARIO_DIRS)


def new_rulebook_file(rulebook_id: str) -> Path:
    """新しく保存するルールブックのパス（置き場所の1つ目。無ければ作る）。"""
    RULEBOOK_DIRS[0].mkdir(parents=True, exist_ok=True)
    return RULEBOOK_DIRS[0] / f"{rulebook_id}.json"
