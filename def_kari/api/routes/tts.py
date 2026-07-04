"""TTS API routes."""

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from def_kari.characters import load_profiles, get_character, get_tts_speaker_id, apply_name_reading
from def_kari.workers._tts_synth import synthesize

router = APIRouter()

ASSET_DIR = (Path(__file__).parent.parent.parent.parent / "assets").resolve()


class TTSRequest(BaseModel):
    text: str
    character_id: str
    backend: str = "voicevox"


@router.post("/")
def generate_tts(req: TTSRequest):
    profiles = load_profiles()
    char = get_character(req.character_id, profiles)
    speaker_id = get_tts_speaker_id(char, req.backend)
    text = apply_name_reading(req.text, char)

    try:
        audio_bytes = synthesize(text, speaker_id, req.backend)
        return Response(content=audio_bytes, media_type="audio/wav")
    except Exception as e:
        return {"error": str(e)}


@router.get("/status")
def get_tts_status():
    from def_kari.backends import is_voicevox_running, is_irodori_running
    return {
        "voicevox": is_voicevox_running(),
        "irodori": is_irodori_running(),
    }


@router.get("/speakers")
def get_tts_speakers():
    from def_kari.backends import is_voicevox_running
    if not is_voicevox_running():
        return {"speakers": [], "running": False}
    try:
        import requests as _req
        resp = _req.get("http://127.0.0.1:50021/speakers", timeout=5)
        resp.raise_for_status()
        speakers = []
        for ch in resp.json():
            for style in ch.get("styles", []):
                speakers.append({"id": style["id"], "label": f"{ch['name']}({style['name']})"})
        return {"speakers": speakers, "running": True}
    except Exception as e:
        return {"speakers": [], "running": False, "error": str(e)}


@router.get("/voices")
def get_tts_voices():
    from def_kari.backends import is_irodori_running, IRODORI_DIR
    if not is_irodori_running():
        return {"voices": [], "running": False}
    voices_dir = os.path.join(IRODORI_DIR, "voices") if IRODORI_DIR else ""
    voices = []
    if os.path.isdir(voices_dir):
        voices = [
            os.path.splitext(f)[0]
            for f in sorted(os.listdir(voices_dir))
            if f.lower().endswith((".wav", ".mp3", ".flac", ".ogg"))
        ]
    return {"voices": voices, "running": True}


class TestTTSRequest(BaseModel):
    backend: str = "voicevox"
    speaker_id: int | str = 2
    text: str = "あめんぼ、あかいな、あいうえお"


@router.post("/test")
def test_tts(req: TestTTSRequest):
    try:
        audio_bytes = synthesize(req.text, req.speaker_id, req.backend)
        return Response(content=audio_bytes, media_type="audio/wav")
    except Exception as e:
        return {"error": str(e)}


@router.post("/save")
async def save_tts_audio(file: UploadFile = File(...)):
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"tts_{uuid.uuid4().hex}.wav"
    path = ASSET_DIR / filename
    path.write_bytes(await file.read())
    return {"url": f"/api/tts/audio/{filename}"}


@router.get("/audio/{filename}")
def get_tts_audio(filename: str):
    path = (ASSET_DIR / filename).resolve()
    if not str(path).startswith(str(ASSET_DIR)) or not path.exists():
        return {"error": "Audio not found"}
    return FileResponse(str(path), media_type="audio/wav")
