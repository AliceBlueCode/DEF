"""Character episodic memory: キャラクターの経験・出来事の記憶。

設計書 10節参照:
  profile.json は「設定」、memory/ は「経験」。混在させない。

  Character/
  ├── profile.json
  └── memory/
      ├── episodic/      ← 出来事の記憶（このモジュールが担当）
      ├── knowledge/     ← 獲得した知識（Phase 5以降）
      └── relationship/  ← 関係性・感情値（Phase 5以降）
"""

import itertools
import json
from datetime import datetime
from pathlib import Path

_BASE = Path(__file__).parent.parent.parent
from def_kari.runtime_paths import writable_data_dir as _writable_data_dir  # noqa: E402

_CHAR_DIRS = [
    _BASE / "data" / "public" / "characters",
    _BASE / "data" / "private" / "characters",
    # 持ち込みキャラ（guest_*）の副本。session_persistence._autosave_visitors が書く場所と同じ
    # （実行中に書き込むデータなので、テストでは一時ディレクトリ。def_kari.runtime_paths 参照）
    _writable_data_dir() / "visitors",
]

# save_episodic()のファイル名サフィックス用プロセス内連番。datetime.now()の
# 実効分解能がWindowsではマイクロ秒より粗く、短時間の連続呼び出しでタイムスタンプが
# 衝突し得るため、単調増加する連番で保存順を保証する(乱数サフィックスだと
# タイムスタンプが衝突した際の順序が不定になりload_episodic()のソート順が崩れる)。
_save_seq = itertools.count()


def _char_base_dir(char_id: str) -> Path | None:
    for base in _CHAR_DIRS:
        d = base / char_id
        if d.exists():
            return d
    return None


def _memory_dir(char_dir: Path) -> Path:
    """キャラの記憶の置き場所。キャラのディレクトリの中の memory/。

    記憶は実行中に書き込むデータなので、テストでは一時ディレクトリへ向ける
    （def_kari.runtime_paths、DEF_ISOLATED_DATA_DIR）。リポジトリの data/ の下にある
    キャラなら、同じ相対パスを書き込み先の根の下に作る。普段の起動では両者が同じなので、
    パスは従来と変わらない。以前はテストでも本物のキャラのディレクトリに書いており、
    公開キャラでセッションを終えるテストがあると、テストの経験が本物のキャラの記憶に
    混ざり得た（2026-11-10、保全の洗い出しで発見）。
    data/ の外のキャラ（テストが差し替えた置き場所など）は、従来どおりその中に置く。
    """
    from def_kari.runtime_paths import REPO_DATA_DIR, writable_data_dir

    try:
        rel = char_dir.resolve().relative_to(REPO_DATA_DIR.resolve())
    except ValueError:
        return char_dir / "memory"
    return writable_data_dir() / rel / "memory"


def load_episodic(char_id: str, limit: int = 5) -> list[dict]:
    """直近 limit 件のエピソード記憶を古い順で返す。ディレクトリ未作成の場合は []。"""
    base = _char_base_dir(char_id)
    if not base:
        return []
    episodic_dir = _memory_dir(base) / "episodic"
    if not episodic_dir.exists():
        return []
    files = sorted(episodic_dir.glob("*.json"), reverse=True)[:limit]
    memories = []
    for f in reversed(files):
        try:
            memories.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return memories


def save_episodic(char_id: str, entry: dict) -> bool:
    """エピソード記憶を保存する。ファイル名は ISO日時(マイクロ秒) + 単調増加連番。

    Returns:
        True if saved successfully, False otherwise.
    """
    base = _char_base_dir(char_id)
    if not base:
        return False
    episodic_dir = _memory_dir(base) / "episodic"
    episodic_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    seq = next(_save_seq)
    path = episodic_dir / f"{ts}_{seq:08d}.json"
    try:
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False
