"""Episode API routes."""

import os
import json as _json

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.models.registry import get_llm_profile
from def_kari.config import DEFAULT_T2I_BACKEND

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
    user_language: str | None = None


@router.post("/generate")
def generate_candidates(req: GenerateRequest):
    from def_kari.settings import load_settings
    user_language = req.user_language or load_settings().get("user_language", "ja")

    sys_prompt = req.plot
    if not sys_prompt:
        sys_prompt = (
            "Continue the story naturally. Maintain the tone, style, and world-building. "
            "Do not repeat the given text. Write only new content."
        ) if user_language == "en" else (
            "与えられた物語の続きを、文体や世界観を保ったまま自然に書き続けてください。"
            "与えられたテキストを繰り返してはいけません。新しい展開のみを書いてください。"
        )

    user_content = req.body or (
        "No text yet. Start the story." if user_language == "en"
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


class T2IRequest(BaseModel):
    scene_text: str
    plot: str = ""
    llm_backend: str = DEFAULT_LLM_BACKEND
    llm_model: str = ""
    t2i_backend: str = DEFAULT_T2I_BACKEND
    t2i_model: str = ""
    width: int | None = None
    height: int | None = None


@router.post("/t2i")
def generate_episode_image(req: T2IRequest):
    from def_kari.settings import load_settings
    _saved = load_settings()
    width = req.width or _saved.get("episode_t2i_width", 1216)
    height = req.height or _saved.get("episode_t2i_height", 832)

    t2i_sys = (
        "You are an image prompt generator. Given a scene from a story, generate a concise English image prompt "
        "suitable for AI image generation (Stable Diffusion style). Output ONLY the prompt, no explanation."
    )
    if req.plot:
        t2i_sys += f"\n\nStory context:\n{req.plot[:500]}"

    messages = [
        {"role": "system", "content": t2i_sys},
        {"role": "user", "content": req.scene_text[:1000]},
    ]

    backend_id = req.llm_backend
    if backend_id not in LLM_BACKENDS:
        backend_id = DEFAULT_LLM_BACKEND

    try:
        img_prompt = LLM_BACKENDS[backend_id]["chat"](messages, req.llm_model, json_mode=False, options={"num_predict": 150})
    except Exception as e:
        return {"error": f"prompt generation failed: {e}"}

    if not img_prompt:
        return {"error": "empty prompt"}

    try:
        from def_kari.workers._t2i_generate import generate_image
        img_path = generate_image(
            prompt=img_prompt,
            width=width,
            height=height,
            model_name=req.t2i_model,
            backend=req.t2i_backend,
        )
    except Exception as e:
        return {"error": f"image generation failed: {e}", "prompt": img_prompt}

    filename = os.path.basename(img_path)
    return {"prompt": img_prompt, "image_url": f"/api/episode/image/{filename}"}


@router.get("/image/{filename}")
def get_episode_image(filename: str):
    from def_kari.workers._t2i_generate import ASSET_DIR
    path = ASSET_DIR / filename
    if not path.exists() or ".." in filename:
        return {"error": "Image not found"}
    return FileResponse(str(path), media_type="image/png")
