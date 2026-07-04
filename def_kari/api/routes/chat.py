"""Chat API routes."""

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

def _debug_guard():
    if os.environ.get("DEF_DEBUG_ENDPOINTS", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Not found")

from def_kari.characters import load_profiles, get_character
from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.llm.client import generate_structured_reply
from def_kari.image_prompt.emotion_tags import apply_emotion_tags
from def_kari.settings import load_settings

router = APIRouter()

_last_debug: dict = {}
_force_rating: dict = {"enabled": False, "tag": "nsfw"}

_FORCE_RATING_TAGS = ["nsfw", "hentai", "violence", "gore", "extreme", "sfw"]


class ChatRequest(BaseModel):
    message: str
    character_id: str
    backend: str = DEFAULT_LLM_BACKEND
    model: str = ""
    history: list[dict] = []
    user_language: str = "ja"


class ChatResponse(BaseModel):
    text: str
    emotion: str = "neutral"
    image_prompt_en: str = ""
    tags: list[str] = []
    raw: str = ""


@router.post("/", response_model=ChatResponse)
def chat(req: ChatRequest):
    profiles = load_profiles()
    char = get_character(req.character_id, profiles)

    history = []
    for h in req.history[-20:]:
        history.append({"role": h.get("role", "user"), "content": h.get("content", "")})

    backend_id = req.backend
    if backend_id not in LLM_BACKENDS:
        backend_id = DEFAULT_LLM_BACKEND

    model = req.model
    if not model:
        model = LLM_BACKENDS.get(backend_id, {}).get("default_model", "")

    global _last_debug, _force_rating
    try:
        result = generate_structured_reply(
            user_text=req.message,
            history=history,
            model=model,
            character=char,
            backend=backend_id,
        )
    except Exception as e:
        _last_debug = {"error": str(e), "success": False, "attempts": []}
        return ChatResponse(text=str(e), raw=str(e))

    attempts = result.get("attempts", [])
    if result.get("success") and result.get("result"):
        parsed = result["result"]
        raw = attempts[-1]["raw"] if attempts else ""
        tags = parsed.get("tags", [])
        if _force_rating["enabled"]:
            forced = _force_rating["tag"]
            if forced not in tags:
                tags = [forced]
            _force_rating["enabled"] = False
        image_prompt_en = parsed.get("image_prompt_en", "")
        settings = load_settings()
        if settings.get("emotion_tag_enabled", True):
            image_prompt_en = apply_emotion_tags(image_prompt_en, parsed.get("emotion", "neutral"))
        _last_debug = {
            "success": True,
            "text": parsed.get("dialogue", ""),
            "emotion": parsed.get("emotion", "neutral"),
            "image_prompt_en": image_prompt_en,
            "tags": tags,
            "raw": raw,
            "attempts": attempts,
            "character_id": req.character_id,
            "backend": backend_id,
        }
        return ChatResponse(
            text=parsed.get("dialogue", ""),
            emotion=parsed.get("emotion", "neutral"),
            image_prompt_en=image_prompt_en,
            tags=tags,
            raw=raw,
        )

    errors = "; ".join(e for a in attempts for e in a.get("errors", []))
    raw = attempts[-1]["raw"] if attempts else ""
    _last_debug = {
        "success": False,
        "raw": raw,
        "attempts": attempts,
        "character_id": req.character_id,
        "backend": backend_id,
    }
    return ChatResponse(text=f"(generation failed: {errors})" if errors else "(generation failed)", raw=raw)


@router.get("/debug")
def get_last_debug():
    return _last_debug


@router.get("/force-rating")
def get_force_rating():
    _debug_guard()
    return _force_rating


class ForceRatingRequest(BaseModel):
    enabled: bool
    tag: str = "nsfw"


@router.post("/force-rating")
def set_force_rating(req: ForceRatingRequest):
    _debug_guard()
    global _force_rating
    if req.tag not in _FORCE_RATING_TAGS:
        raise HTTPException(status_code=400, detail=f"invalid tag: {req.tag}")
    _force_rating = {"enabled": req.enabled, "tag": req.tag}
    return _force_rating


@router.get("/vram-lock")
def get_vram_lock_status():
    from def_kari.resources.vram_lock import get_vram_lock
    locked = get_vram_lock().locked()
    return {"locked": locked}
