"""キャラクター画像配信のうち、外部公開しても安全なエンドポイントのみを含むルーター。

`def_kari/api/public_main.py`（Cloudflare Tunnel等でリモート公開する軽量アプリ）専用。
一覧・詳細プロファイル・raw-profile・voice-settings・アップロード/生成系など、
ホストの非公開データ操作に繋がるエンドポイントは意図的に含めない
（`characters.py`のフル機能ルーターとは別ファイルに分離することで、
将来の変更で誤って危険なエンドポイントが公開側に混入するのを防ぐ）。
"""

from fastapi import APIRouter
from fastapi.responses import FileResponse
from def_kari.api.routes.characters_common import find_char_dir, _NO_CACHE_HEADERS

router = APIRouter()


@router.get("/{character_id}/icon")
def get_character_icon(character_id: str):
    d = find_char_dir(character_id)
    if d:
        icon = d / "icon.png"
        if icon.exists():
            return FileResponse(str(icon), media_type="image/png", headers=_NO_CACHE_HEADERS)
    return {"error": "Icon not found"}


@router.get("/{character_id}/standing")
def get_character_standing(character_id: str):
    d = find_char_dir(character_id)
    if d:
        standing = d / "standing.png"
        if standing.exists():
            return FileResponse(str(standing), media_type="image/png", headers=_NO_CACHE_HEADERS)
    return {"error": "Standing image not found"}
