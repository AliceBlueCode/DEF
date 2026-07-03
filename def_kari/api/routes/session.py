"""Session API routes."""

import random
import secrets
from collections import OrderedDict

from fastapi import APIRouter
from pydantic import BaseModel

from def_kari.characters import load_profiles, get_character
from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.llm.client import generate_structured_reply

router = APIRouter()

_MAX_SESSIONS = 100
_sessions: OrderedDict[str, dict] = OrderedDict()


class SessionStartRequest(BaseModel):
    character_ids: list[str]
    topic: str = ""
    backend: str = DEFAULT_LLM_BACKEND


class SessionNextRequest(BaseModel):
    session_id: str
    backend: str = DEFAULT_LLM_BACKEND
    model: str = ""


class SessionHumanMessage(BaseModel):
    session_id: str
    message: str


@router.post("/start")
def start_session(req: SessionStartRequest):
    session_id = secrets.token_urlsafe(16)
    initiative = random.sample(req.character_ids, len(req.character_ids))
    profiles = load_profiles()
    name_map = {}
    for cid in req.character_ids:
        char = get_character(cid, profiles)
        name_map[cid] = char.get("name", cid) if char else cid

    if len(_sessions) >= _MAX_SESSIONS:
        _sessions.popitem(last=False)
    _sessions[session_id] = {
        "id": session_id,
        "initiative": initiative,
        "name_map": name_map,
        "topic": req.topic,
        "backend": req.backend,
        "round": 1,
        "turn": 0,
        "history": [],
    }

    order = [name_map.get(c, c) for c in initiative]
    return {"session_id": session_id, "initiative": initiative, "order": order}


@router.post("/next")
def next_turn(req: SessionNextRequest):
    session = _sessions.get(req.session_id)
    if not session:
        return {"error": "Session not found"}

    initiative = session["initiative"]
    turn = session["turn"]
    if turn >= len(initiative):
        session["round"] += 1
        session["turn"] = 0
        turn = 0

    current_char_id = initiative[turn]
    profiles = load_profiles()
    char = get_character(current_char_id, profiles)
    name_map = session["name_map"]

    backend_id = req.backend or session["backend"]
    if backend_id not in LLM_BACKENDS:
        backend_id = DEFAULT_LLM_BACKEND
    model = req.model
    if not model:
        model = LLM_BACKENDS.get(backend_id, {}).get("default_model", "")

    history = []
    for h in session["history"][-20:]:
        history.append({"role": h["role"], "content": h["content"]})

    topic_prefix = f"[Topic: {session['topic']}] " if session["topic"] else ""
    user_text = f"{topic_prefix}Continue the conversation as {name_map.get(current_char_id, current_char_id)}."

    try:
        result = generate_structured_reply(
            user_text=user_text,
            history=history,
            model=model,
            character=char,
            backend=backend_id,
        )
    except Exception as e:
        return {"error": str(e), "character_id": current_char_id, "character_name": name_map.get(current_char_id, current_char_id), "text": f"(error: {e})", "emotion": "neutral", "round": session["round"], "turn": turn + 1}

    text = ""
    emotion = "neutral"
    if result.get("success") and result.get("result"):
        parsed = result["result"]
        text = parsed.get("dialogue", "")
        emotion = parsed.get("emotion", "neutral")
    else:
        attempts = result.get("attempts", [])
        errors = "; ".join(e for a in attempts for e in a.get("errors", []))
        text = f"(generation failed: {errors})" if errors else "(generation failed)"

    session["history"].append({
        "role": "assistant",
        "content": f"{name_map.get(current_char_id, current_char_id)}: {text}",
        "character_id": current_char_id,
        "emotion": emotion,
    })
    session["turn"] = turn + 1

    return {
        "character_id": current_char_id,
        "character_name": name_map.get(current_char_id, current_char_id),
        "text": text,
        "emotion": emotion,
        "round": session["round"],
        "turn": turn + 1,
    }


@router.post("/human")
def human_message(req: SessionHumanMessage):
    session = _sessions.get(req.session_id)
    if not session:
        return {"error": "Session not found"}
    session["history"].append({
        "role": "user",
        "content": req.message,
        "character_id": "human",
        "emotion": "",
    })
    return {"status": "ok"}


@router.get("/{session_id}")
def get_session(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    return {"session": session}
