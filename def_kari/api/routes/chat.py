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
from def_kari.history.store import load_full, save_session as _store_save, clear_history as _store_clear

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
    settings = load_settings()
    _allowed_sexual: list[str] = settings.get("allowed_rating_sexual", ["general"])
    _allowed_violence: list[str] = settings.get("allowed_rating_violence", ["general"])

    _forced_tag = ""
    _force_directive = ""
    _sexual_hierarchy = ["general", "sfw", "nsfw", "hentai"]
    _violence_hierarchy = ["general", "violence", "gore", "extreme"]
    if _force_rating["enabled"]:
        _forced_tag = _force_rating["tag"]
        if _forced_tag in _sexual_hierarchy:
            idx = _sexual_hierarchy.index(_forced_tag)
            _allowed_sexual = _sexual_hierarchy[:idx + 1]
        elif _forced_tag in _violence_hierarchy:
            idx = _violence_hierarchy.index(_forced_tag)
            _allowed_violence = _violence_hierarchy[:idx + 1]
        _force_directive = (
            f"【強制指示】この返答では必ず \"{_forced_tag}\" レーティングに相応しい内容を生成すること。"
            f"tags には必ず \"{_forced_tag}\" を含めること。"
            f"image_prompt_en にも \"{_forced_tag}\" タグを含めること。"
        )

    _last_emotion = req.history[-1].get("emotion", "neutral") if req.history else "neutral"
    if isinstance(_last_emotion, list):
        _last_emotion = ", ".join(_last_emotion)

    from def_kari.resources.vram_lock import get_vram_lock
    _vram_lock = get_vram_lock()
    _vram_lock.acquire()
    try:
        result = generate_structured_reply(
            user_text=req.message,
            history=history,
            model=model,
            character=char,
            backend=backend_id,
            extra_instruction=_force_directive,
            allowed_sexual=_allowed_sexual,
            allowed_violence=_allowed_violence,
            current_emotion=_last_emotion,
        )
    except Exception as e:
        _last_debug = {"error": str(e), "success": False, "attempts": []}
        return ChatResponse(text=str(e), raw=str(e))
    finally:
        _vram_lock.release()

    attempts = result.get("attempts", [])
    if result.get("success") and result.get("result"):
        parsed = result["result"]
        raw = attempts[-1]["raw"] if attempts else ""
        tags = parsed.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        if _forced_tag:
            if _forced_tag not in tags:
                tags = [_forced_tag] + [t for t in tags if t != _forced_tag]
        image_prompt_en = parsed.get("image_prompt_en", "")
        _emotion_raw = parsed.get("emotion", "neutral")
        emotion_str = (_emotion_raw[0] if _emotion_raw else "neutral") if isinstance(_emotion_raw, list) else str(_emotion_raw or "neutral")
        if _forced_tag and _forced_tag not in image_prompt_en:
            image_prompt_en = f"{image_prompt_en}, {_forced_tag}" if image_prompt_en else _forced_tag
        settings = load_settings()
        if settings.get("emotion_tag_enabled", True):
            image_prompt_en = apply_emotion_tags(image_prompt_en, _emotion_raw)
        _last_debug = {
            "success": True,
            "text": parsed.get("dialogue", ""),
            "emotion": emotion_str,
            "image_prompt_en": image_prompt_en,
            "tags": tags,
            "raw": raw,
            "attempts": attempts,
            "character_id": req.character_id,
            "backend": backend_id,
        }
        return ChatResponse(
            text=parsed.get("dialogue", ""),
            emotion=emotion_str,
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
    return _force_rating


class ForceRatingRequest(BaseModel):
    enabled: bool
    tag: str = "nsfw"


@router.post("/force-rating")
def set_force_rating(req: ForceRatingRequest):
    global _force_rating
    if req.tag not in _FORCE_RATING_TAGS:
        raise HTTPException(status_code=400, detail=f"invalid tag: {req.tag}")
    _force_rating = {"enabled": req.enabled, "tag": req.tag}
    return _force_rating


@router.get("/history/{character_id}")
def get_history(character_id: str, tail: int = 0):
    all_msgs = load_full(character_id)
    total = len(all_msgs)
    if tail > 0 and total > tail:
        return {"messages": all_msgs[-tail:], "total": total, "has_more": True}
    return {"messages": all_msgs, "total": total, "has_more": False}


class LoadMoreRequest(BaseModel):
    loaded_ids: list[str] = []
    batch: int = 20


@router.post("/history/{character_id}/load-more")
def load_more_history(character_id: str, req: LoadMoreRequest):
    all_msgs = load_full(character_id)
    existing_ids = set(req.loaded_ids)
    missing = [m for m in all_msgs if m.get("id") not in existing_ids]
    if not missing:
        return {"messages": [], "has_more": False}
    to_load = missing[-req.batch:]
    return {"messages": to_load, "has_more": len(missing) > req.batch}


class SaveHistoryRequest(BaseModel):
    messages: list[dict]


@router.post("/history/{character_id}")
def save_history(character_id: str, req: SaveHistoryRequest):
    _store_save(req.messages, character_id)
    return {"status": "ok"}


@router.delete("/history/{character_id}")
def delete_history(character_id: str):
    _store_clear(character_id)
    return {"status": "ok"}


@router.get("/vram-lock")
def get_vram_lock_status():
    from def_kari.resources.vram_lock import get_vram_lock
    locked = get_vram_lock().locked()
    return {"locked": locked}
