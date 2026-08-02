"""キャラクターディレクトリ探索の共通ヘルパー。

`characters.py`（フル機能・ローカル専用）と `characters_public.py`（画像配信のみ・
外部公開用）の両方から使われる。公開用ルーターを分離する際にロジックが重複・
乖離しないよう、この一箇所に集約している。
"""

import re
from pathlib import Path

_BASE = Path(__file__).parent.parent.parent.parent
_CHAR_DIRS = [
    _BASE / "data" / "public" / "characters",
    _BASE / "data" / "private" / "characters",
    _BASE / "data" / "visitors",  # 持ち込みキャラ（guest_*）の副本
]
_SAFE_ID_RE = re.compile(r'^[A-Za-z0-9_\-]+$')
_NO_CACHE_HEADERS = {"Cache-Control": "no-cache, no-store, must-revalidate"}


def find_char_dir(character_id: str) -> Path | None:
    if not _SAFE_ID_RE.match(character_id):
        return None
    # DEF-Character リポジトリ（再帰走査、先勝ち）
    from def_kari.characters import _get_repo_paths
    for _repo in _get_repo_paths():
        _public = _repo / "public"
        if not _public.exists():
            continue
        for pf in sorted(_public.rglob("profile.json")):
            if pf.parent.name == character_id:
                return pf.parent
    # フォールバック: DEF自身の data/
    for d in _CHAR_DIRS:
        p = d / character_id
        if p.is_dir():
            return p
    return None
