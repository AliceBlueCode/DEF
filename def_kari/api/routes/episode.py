"""Episode API routes."""

import os
import json as _json

from fastapi import APIRouter
from pydantic import BaseModel

from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.models.registry import get_llm_profile

router = APIRouter()

_EPISODES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "..", "data", "private", "episodes")


@router.get("/")
def list_episodes():
    if not os.path.isdir(_EPISODES_DIR):
        return {"episodes": []}
    episodes = []
    for f in sorted(os.listdir(_EPISODES_DIR)):
        if not f.endswith(".json"):
            continue
        try:
            with open(os.path.join(_EPISODES_DIR, f), encoding="utf-8") as fh:
                ep = _json.load(fh)
                ep.setdefault("title", os.path.splitext(f)[0])
                episodes.append({"title": ep["title"], "file": f})
        except (_json.JSONDecodeError, OSError):
            pass
    return {"episodes": episodes}


@router.get("/{title}")
def get_episode(title: str):
    safe_name = title.replace("/", "_").replace("\\", "_").replace(":", "_")
    path = os.path.join(_EPISODES_DIR, f"{safe_name}.json")
    if not os.path.exists(path):
        return {"error": "Episode not found"}
    with open(path, encoding="utf-8") as f:
        return {"episode": _json.load(f)}


class SaveEpisodeRequest(BaseModel):
    episode: dict


@router.post("/")
def save_episode(req: SaveEpisodeRequest):
    os.makedirs(_EPISODES_DIR, exist_ok=True)
    title = req.episode.get("title", "untitled")
    safe_name = title.replace("/", "_").replace("\\", "_").replace(":", "_")
    path = os.path.join(_EPISODES_DIR, f"{safe_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(req.episode, f, ensure_ascii=False, indent=2)
    return {"status": "ok", "title": title}


@router.delete("/{title}")
def delete_episode(title: str):
    safe_name = title.replace("/", "_").replace("\\", "_").replace(":", "_")
    path = os.path.join(_EPISODES_DIR, f"{safe_name}.json")
    if os.path.exists(path):
        os.remove(path)
        return {"status": "ok"}
    return {"error": "Episode not found"}


class GenerateRequest(BaseModel):
    body: str = ""
    plot: str = ""
    backend: str = DEFAULT_LLM_BACKEND
    model: str = ""
    candidate_count: int = 3
    user_language: str = "ja"


@router.post("/generate")
def generate_candidates(req: GenerateRequest):
    sys_prompt = req.plot
    if not sys_prompt:
        sys_prompt = (
            "Continue the story naturally. Maintain the tone, style, and world-building. "
            "Do not repeat the given text. Write only new content."
        ) if req.user_language == "en" else (
            "与えられた物語の続きを、文体や世界観を保ったまま自然に書き続けてください。"
            "与えられたテキストを繰り返してはいけません。新しい展開のみを書いてください。"
        )

    user_content = req.body or (
        "No text yet. Start the story." if req.user_language == "en"
        else "(まだ本文はありません。物語の冒頭を書き始めてください。)"
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_content},
    ]

    backend_id = req.backend
    if backend_id not in LLM_BACKENDS:
        backend_id = DEFAULT_LLM_BACKEND
    model = req.model
    if not model:
        model = LLM_BACKENDS.get(backend_id, {}).get("default_model", "")

    profile = get_llm_profile(model)
    max_tokens = profile.get("max_tokens", 2048)
    gen_params = profile.get("generation_params", {})
    opts = {"num_predict": max_tokens}
    opts.update(gen_params)

    candidates = []
    errors = []
    for i in range(max(1, min(req.candidate_count, 5))):
        try:
            cont = LLM_BACKENDS[backend_id]["chat"](messages, model, json_mode=False, options=opts)
            if cont:
                candidates.append(cont)
        except Exception as e:
            errors.append(f"#{i + 1}: {e}")

    return {"candidates": candidates, "errors": errors}
