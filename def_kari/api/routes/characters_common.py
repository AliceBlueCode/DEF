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
# characters_public.py（外部公開用、無認証）専用の探索範囲。data/private/charactersを
# 含まない（8.18対策）。data/visitorsは持ち込みキャラの画像をセッション参加者に見せる
# 目的で必要なため残す（VISITOR_ICON_READYイベント参照）。
_PUBLIC_CHAR_DIRS = [
    _BASE / "data" / "public" / "characters",
    _BASE / "data" / "visitors",
]
_SAFE_ID_RE = re.compile(r'^[A-Za-z0-9_\-]+$')
_NO_CACHE_HEADERS = {"Cache-Control": "no-cache, no-store, must-revalidate"}


def find_char_dir(character_id: str, public_only: bool = False) -> Path | None:
    """キャラクターのディレクトリを探す。

    `public_only=True`（characters_public.py専用）の場合、data/private/charactersを
    検索対象から除外する。以前はcharacters_public.pyもこの関数を無条件に共有しており、
    character_idさえ分かればホストの非公開/NSFWキャラクターのicon/standing画像を
    誰でも取得できた（レーティングゲートも一切バイパスされる）。DEF-Characterリポジトリ
    側の`public/`探索は設計上公開前提のため、public_onlyでも変わらず対象に含む。
    """
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
    for d in (_PUBLIC_CHAR_DIRS if public_only else _CHAR_DIRS):
        p = d / character_id
        if p.is_dir():
            return p
    return None
