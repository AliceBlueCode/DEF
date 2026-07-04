"""Novel API routes."""

import os
import re
import json as _json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.models.registry import get_llm_profile
from def_kari.config import DEFAULT_T2I_BACKEND

router = APIRouter()

_DATA_ROOT = Path(__file__).parent.parent.parent.parent / "data"
_NOVELS_DIR = _DATA_ROOT / "private" / "novels"
_PLOTS_DIRS = [
    _DATA_ROOT / "public" / "episode_prompts",
    _DATA_ROOT / "private" / "episode_prompts",
]

_SAFE_NAME_RE = re.compile(r'[^\w\-　-鿿゠-ヿ぀-ゟ]+')


def _safe_path(title: str) -> Path | None:
    safe_name = _SAFE_NAME_RE.sub("_", title).strip("_") or "untitled"
    path = (_NOVELS_DIR / f"{safe_name}.json").resolve()
    if not str(path).startswith(str(_NOVELS_DIR.resolve())):
        return None
    return path


@router.get("/plots")
def list_plots():
    files = []
    for d in _PLOTS_DIRS:
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix in (".txt", ".md"):
                    files.append({"name": f.name, "dir": str(d)})
    return {"files": files}


@router.get("/plots/{filename}")
def get_plot(filename: str):
    for d in _PLOTS_DIRS:
        path = (d / filename).resolve()
        if str(path).startswith(str(d.resolve())) and path.exists():
            return {"content": path.read_text(encoding="utf-8"), "name": filename}
    return {"error": "not found"}


class SavePlotFileRequest(BaseModel):
    content: str


@router.put("/plots/{filename}")
def save_plot_file(filename: str, req: SavePlotFileRequest):
    for d in _PLOTS_DIRS:
        path = (d / filename).resolve()
        if str(path).startswith(str(d.resolve())) and path.exists():
            path.write_text(req.content, encoding="utf-8")
            return {"status": "ok", "name": filename}
    return {"error": "not found"}


@router.get("/")
def list_novels():
    if not _NOVELS_DIR.is_dir():
        return {"novels": []}
    episodes = []
    for f in sorted(_NOVELS_DIR.iterdir()):
        if not f.suffix == ".json":
            continue
        try:
            ep = _json.loads(f.read_text(encoding="utf-8"))
            ep.setdefault("title", f.stem)
            episodes.append({"title": ep["title"], "file": f.name})
        except (_json.JSONDecodeError, OSError):
            pass
    return {"novels": episodes}


@router.get("/{title}")
def get_novel(title: str):
    path = _safe_path(title)
    if path is None or not path.exists():
        return {"error": "Novel not found"}
    return {"novel": _json.loads(path.read_text(encoding="utf-8"))}


class SaveNovelRequest(BaseModel):
    novel: dict


@router.post("/")
def save_novel(req: SaveNovelRequest):
    _NOVELS_DIR.mkdir(parents=True, exist_ok=True)
    title = req.novel.get("title", "untitled")
    path = _safe_path(title)
    if path is None:
        return {"error": "Invalid title"}
    path.write_text(_json.dumps(req.novel, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok", "title": title}


@router.delete("/{title}")
def delete_novel(title: str):
    path = _safe_path(title)
    if path is None or not path.exists():
        return {"error": "Novel not found"}
    path.unlink()
    return {"status": "ok"}


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
    from def_kari.resources.vram_lock import get_vram_lock
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
    vram_lock = get_vram_lock()
    vram_lock.acquire()
    try:
        for i in range(max(1, min(req.candidate_count, 5))):
            try:
                cont = LLM_BACKENDS[backend_id]["chat"](messages, model, json_mode=False, options=opts)
                if cont:
                    candidates.append(cont)
            except Exception as e:
                errors.append(f"#{i + 1}: {e}")
    finally:
        vram_lock.release()

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
    from def_kari.resources.vram_lock import get_vram_lock
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

    vram_lock = get_vram_lock()
    vram_lock.acquire()
    try:
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
    finally:
        vram_lock.release()

    filename = os.path.basename(img_path)
    return {"prompt": img_prompt, "image_url": f"/api/novel/image/{filename}"}


@router.get("/image/{filename}")
def get_novel_image(filename: str):
    from def_kari.workers._t2i_generate import ASSET_DIR
    path = (ASSET_DIR / filename).resolve()
    if not str(path).startswith(str(ASSET_DIR.resolve())) or not path.exists():
        return {"error": "Image not found"}
    return FileResponse(str(path), media_type="image/png")
