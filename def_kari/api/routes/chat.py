"""Chat API routes."""

from fastapi import APIRouter
from pydantic import BaseModel

from def_kari.characters import load_profiles, get_character
from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.llm.client import generate_structured_reply

router = APIRouter()


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

    try:
        result = generate_structured_reply(
            user_text=req.message,
            history=history,
            model=model,
            character=char,
            backend=backend_id,
        )
    except Exception as e:
        return ChatResponse(text=str(e), raw=str(e))

    if result.get("success") and result.get("result"):
        parsed = result["result"]
        raw = result["attempts"][-1]["raw"] if result.get("attempts") else ""
        return ChatResponse(
            text=parsed.get("dialogue", ""),
            emotion=parsed.get("emotion", "neutral"),
            image_prompt_en=parsed.get("image_prompt_en", ""),
            tags=parsed.get("tags", []),
            raw=raw,
        )

    attempts = result.get("attempts", [])
    errors = "; ".join(
        e for a in attempts for e in a.get("errors", [])
    )
    raw = attempts[-1]["raw"] if attempts else ""
    return ChatResponse(text=f"(generation failed: {errors})" if errors else "(generation failed)", raw=raw)
