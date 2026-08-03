"""T2I生成画像配信のうち、外部公開しても安全な読み取り専用エンドポイントのみを含むルーター。

`def_kari/api/public_main.py`（Cloudflare Tunnel等でリモート公開する軽量アプリ）専用。
画像生成そのもの（`POST /`）は無制限にGPU時間を消費できてしまうため意図的に含めない。
生成はサーバー側（session.py の `_generate_turn_image` 等）でのみ行い、参加者はここで
配信URLを読むだけにする。
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from def_kari.api.path_safety import is_safe_path

router = APIRouter()

ASSET_DIR = (Path(__file__).parent.parent.parent.parent / "assets").resolve()


@router.get("/image/{filename}")
def get_t2i_image(filename: str):
    path = (ASSET_DIR / filename).resolve()
    if not is_safe_path(path, ASSET_DIR) or not path.exists():
        return {"error": "Image not found"}
    return FileResponse(str(path), media_type="image/png")
