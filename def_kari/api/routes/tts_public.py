"""TTS音声配信のうち、外部公開しても安全な読み取り専用エンドポイントのみを含むルーター。

`def_kari/api/public_main.py`（Cloudflare Tunnel等でリモート公開する軽量アプリ）専用。
音声合成そのもの（`POST /`）は無制限にCPU/GPU時間を消費できてしまうため意図的に含めない。
生成はサーバー側（session.py の `_generate_turn_audio` 等）でのみ行い、参加者はここで
配信URLを読むだけにする。
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

ASSET_DIR = (Path(__file__).parent.parent.parent.parent / "assets").resolve()


@router.get("/audio/{filename}")
def get_tts_audio(filename: str):
    path = (ASSET_DIR / filename).resolve()
    if not str(path).startswith(str(ASSET_DIR)) or not path.exists():
        return {"error": "Audio not found"}
    return FileResponse(str(path), media_type="audio/wav")
