"""Thought tab API routes — thought journal with LLM assistance."""

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND

router = APIRouter()

_BASE = Path(__file__).parent.parent.parent.parent
_DATA_FILE = _BASE / "data" / "private" / "thoughts.json"

_SYSTEM_PROMPT = (
    "あなたはユーザーの思考の整理・深掘りを助ける汎用アシスタントです。"
    "ユーザーの入力内容を要約・整理したうえで、新たな視点や問いを提示し、"
    "ユーザー自身が考えを深められるように応答してください。"
)


def _load() -> list[dict]:
    try:
        if _DATA_FILE.exists():
            return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save(entries: list[dict]) -> None:
    _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    _DATA_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


class ThoughtRequest(BaseModel):
    input: str
    backend: str = DEFAULT_LLM_BACKEND
    model: str = ""


@router.get("/")
def list_thoughts():
    return {"entries": _load()}


@router.post("/")
def create_thought(req: ThoughtRequest):
    if not req.input.strip():
        raise HTTPException(status_code=400, detail="input is empty")

    backend_id = req.backend if req.backend in LLM_BACKENDS else DEFAULT_LLM_BACKEND
    backend = LLM_BACKENDS[backend_id]
    model = req.model or backend.get("default_model", "")

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": req.input},
    ]
    try:
        output = backend["chat"](messages, model, json_mode=False)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    entry = {
        "id": str(uuid.uuid4()),
        "input": req.input,
        "output": output,
        "model": model,
    }
    entries = _load()
    entries.insert(0, entry)
    _save(entries)
    return entry


@router.delete("/{entry_id}")
def delete_thought(entry_id: str):
    entries = _load()
    new_entries = [e for e in entries if e.get("id") != entry_id]
    if len(new_entries) == len(entries):
        raise HTTPException(status_code=404, detail="entry not found")
    _save(new_entries)
    return {"ok": True}
