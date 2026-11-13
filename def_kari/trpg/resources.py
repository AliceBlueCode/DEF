"""TRPG のルールブックとシナリオの置き場所と読み込み（1か所にまとめたもの）。

以前は、読み込み先が `api/routes/trpg.py`（一覧・取得・保存）と `gm/context_builder.py`
（セッションで使う読み込み）の2か所に重ねて書かれていた。置き場所を足す（外部のリポジトリ、
プラグインのデータ）前に、ここへ集めた（2026-11-13、マルチルールブック基盤 B-010）。

このモジュールは、集める前の挙動をそのまま引き継ぐ。挙動は `tests/characterization/` が固定している:

- 置き場所は public → private の順。
- どの読み方でも、パスを解決した後に置き場所の内側にある普通のファイルだけを読む（`safe_file`、B-012）。
- ID を指定した読み込み（`load_rulebook` など）は、先に見つかった方を使う。ファイル名が ID。
- 一覧（`all_rulebooks` など）は、JSON の `id`（無ければファイル名）を ID とし、後から読んだ方で
  上書きする。同じ ID が public と private の両方にあると、ID を指定した読み込みとは勝つ方が逆になる。
  この食い違いは、読み込み先を足すとき（B-011）に直す。

読み込み先の一覧（`RULEBOOK_DIRS` など）は、呼ばれるたびにこのモジュールの値を見る。テストは
この値を差し替える。
"""

import json
import logging
import re
from pathlib import Path

from def_kari.trpg import registry

_log = logging.getLogger("def.trpg")

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


def safe_file(d: Path, name: str) -> Path | None:
    """置き場所 `d` の中のファイル `name` のパスを、安全なときだけ返す（B-012）。

    パスを解決した後（シンボリックリンクをたどった後）も `d` の内側にあり、普通のファイルで
    あるときだけ、解決した後のパスを返す。それ以外は None。読み込み・一覧・個別の取得・保存先の
    検索は、すべてこの関数を通す（2026-11-13 まで、一覧と個別の取得は確かめずに読んでおり、
    置き場所の中のシンボリックリンクから外のファイルを読めた。一次レビューの指摘）。
    """
    try:
        base = d.resolve()
        candidate = (d / name).resolve()
        if not candidate.is_relative_to(base):
            if (d / name).exists() or (d / name).is_symlink():
                _log.warning("[trpg] %s points outside %s; ignored", d / name, d)
            return None
        return candidate if candidate.is_file() else None
    except (OSError, ValueError):
        return None


def load_resource(resource_id: str, dirs: list[Path]) -> dict:
    """`dirs` を順に探し、最初に読めた `{resource_id}.json` を返す。無ければ空の dict。"""
    if not is_safe_id(resource_id):
        return {}
    for d in dirs:
        path = safe_file(d, f"{resource_id}.json")
        if path is not None:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def load_rulebook(rulebook_id: str, public_only: bool = False) -> dict:
    """ルールブックを読む。登録されていない `rule_system` のものは読まない（空の dict。B-002）。"""
    data = load_resource(rulebook_id, PUBLIC_RULEBOOK_DIRS if public_only else RULEBOOK_DIRS)
    if data and not registry.is_known(data):
        _log.warning("[trpg] rulebook %s uses an unknown rule_system %r; not loaded",
                     rulebook_id, registry.rule_system_of(data))
        return {}
    return data


def load_scenario(scenario_id: str, public_only: bool = False) -> dict:
    return load_resource(scenario_id, PUBLIC_SCENARIO_DIRS if public_only else SCENARIO_DIRS)


def _load_all(dirs: list[Path]) -> dict:
    """`dirs` のすべての JSON を読み、ID → 中身 の dict を返す（後から読んだ方で上書き）。"""
    found: dict = {}
    for d in dirs:
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix == ".json" and f.name != ".gitkeep":
                    path = safe_file(d, f.name)
                    if path is None:
                        continue
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                        found[data.get("id", f.stem)] = data
                    except (json.JSONDecodeError, OSError):
                        pass
    return found


def all_rulebooks() -> dict:
    """一覧に出すルールブック。登録されていない `rule_system` のものは除く（B-002）。"""
    return {k: v for k, v in _load_all(RULEBOOK_DIRS).items() if registry.is_known(v)}


def all_scenarios() -> dict:
    return _load_all(SCENARIO_DIRS)


def _find_file(resource_id: str, dirs: list[Path]) -> Path | None:
    """`{resource_id}.json` がある最初の置き場所の、安全なパス（`safe_file`）。無ければ None。"""
    if not is_safe_id(resource_id):
        return None
    for d in dirs:
        path = safe_file(d, f"{resource_id}.json")
        if path is not None:
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
