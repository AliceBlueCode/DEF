"""キャラクター画像配信のうち、外部公開しても安全なエンドポイントのみを含むルーター。

`def_kari/api/public_main.py`（Cloudflare Tunnel等でリモート公開する軽量アプリ）専用。
一覧・詳細プロファイル・raw-profile・voice-settings・アップロード/生成系など、
ホストの非公開データ操作に繋がるエンドポイントは意図的に含めない
（`characters.py`のフル機能ルーターとは別ファイルに分離することで、
将来の変更で誤って危険なエンドポイントが公開側に混入するのを防ぐ）。
"""

import json

from fastapi import APIRouter
from fastapi.responses import FileResponse
from def_kari.api.routes.characters_common import find_char_dir, _NO_CACHE_HEADERS

router = APIRouter()


@router.get("/{character_id}/icon")
def get_character_icon(character_id: str):
    d = find_char_dir(character_id, public_only=True)
    if d:
        icon = d / "icon.png"
        if icon.exists():
            return FileResponse(str(icon), media_type="image/png", headers=_NO_CACHE_HEADERS)
    return {"error": "Icon not found"}


@router.get("/{character_id}/standing")
def get_character_standing(character_id: str):
    d = find_char_dir(character_id, public_only=True)
    if d:
        standing = d / "standing.png"
        if standing.exists():
            return FileResponse(str(standing), media_type="image/png", headers=_NO_CACHE_HEADERS)
    return {"error": "Standing image not found"}


@router.get("/{character_id}/game_sheets")
def get_character_game_sheets(character_id: str):
    """8.29対策: characters.pyのフル機能ルーターにしか無く、Cloudflare Tunnel経由の
    オンラインTRPGセッションではキャラシート復元（SessionTab.tsxが無条件に
    /api/characters/{id}/game_sheets を叩く）が404で機能しなくなっていた
    （セキュリティ上の抜けではなく、公開APIを絞った際の機能回帰）。
    characters.py側と同じ`game_rules_sheets`を返すが、public_only=Trueで
    data/private/charactersを検索対象から除外する。"""
    d = find_char_dir(character_id, public_only=True)
    if not d:
        return {"game_sheets": {}}
    pf = d / "profile.json"
    if not pf.exists():
        return {"game_sheets": {}}
    try:
        with open(pf, encoding="utf-8-sig") as f:
            data = json.load(f)
        raw = next(iter(data.values())) if data else {}
    except (json.JSONDecodeError, OSError, StopIteration):
        raw = {}
    return {"game_sheets": raw.get("game_rules_sheets", {})}
