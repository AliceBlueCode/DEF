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
_CHAR_DIRS = [
    _BASE / "data" / "public" / "characters",
    _BASE / "data" / "private" / "characters",
    _BASE / "data" / "visitors",  # 持ち込みキャラ（guest_*）の副本。session.py:_autosave_visitors 参照
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


def load_episodic(char_id: str, limit: int = 5) -> list[dict]:
    """直近 limit 件のエピソード記憶を古い順で返す。ディレクトリ未作成の場合は []。"""
    base = _char_base_dir(char_id)
    if not base:
        return []
    episodic_dir = base / "memory" / "episodic"
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
    episodic_dir = base / "memory" / "episodic"
    episodic_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    seq = next(_save_seq)
    path = episodic_dir / f"{ts}_{seq:08d}.json"
    try:
        path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False
