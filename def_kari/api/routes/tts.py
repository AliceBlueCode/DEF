"""TTS API routes."""

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from def_kari.characters import load_profiles, get_character, get_tts_speaker_id, apply_name_reading
from def_kari.workers._tts_synth import synthesize

router = APIRouter()


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
