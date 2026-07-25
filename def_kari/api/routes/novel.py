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

_last_novel_t2i_debug: dict = {}

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
    t2i_prompt_mode: str = ""


@router.post("/t2i")
def generate_episode_image(req: T2IRequest):
    from def_kari.settings import load_settings
    from def_kari.resources.vram_lock import get_vram_lock
    from def_kari.models.t2i_profiles import get_current_tag_format
    _saved = load_settings()
    width = req.width or _saved.get("episode_t2i_width", 1216)
    height = req.height or _saved.get("episode_t2i_height", 832)
    t2i_prompt_mode = req.t2i_prompt_mode or _saved.get("episode_t2i_prompt_mode", "current")
    _tag_format = get_current_tag_format()
    _is_tag_based = _tag_format in ("danbooru", "e621")
    _fmt_label = {"danbooru": "Danbooru", "e621": "e621", "natural": "natural language", "other": "English"}.get(_tag_format, "Danbooru")

    plot_context = f"\n\nStory context:\n{req.plot[:500]}" if req.plot else ""

    global _last_novel_t2i_debug
    _t2i_model_resolved = req.t2i_model or _saved.get(f"t2i_model_{req.t2i_backend}") or ""
    _last_novel_t2i_debug = {
        "mode": t2i_prompt_mode,
        "tag_format": _tag_format,
        "backend": req.t2i_backend,
        "model": _t2i_model_resolved,
        "scene_text": req.scene_text[:300],
        "width": width,
        "height": height,
    }

    if t2i_prompt_mode == "passthrough":
        img_prompt = req.scene_text.strip()
        if not img_prompt:
            return {"error": "empty scene_text for passthrough mode"}
    else:
        backend_id = req.llm_backend
        if backend_id not in LLM_BACKENDS:
            backend_id = DEFAULT_LLM_BACKEND

        if t2i_prompt_mode == "dedicated":
            if _is_tag_based:
                system_prompt = (
                    f"Image tag generator. Output comma-separated {_fmt_label} tags ONLY. "
                    "Start your response with the first tag immediately. "
                    "No prose, no reasoning, no abstract concepts. "
                    "Only visual descriptors: characters, setting, lighting, color, composition."
                    + plot_context
                )
                user_text = (
                    req.scene_text[:1000] +
                    f"\n\nIMMEDIATELY output 10-20 {_fmt_label}-style image tags, comma-separated. "
                    "Visual tags only. NO explanation. NO reasoning. First token must be a tag."
                )
            else:
                system_prompt = (
                    "Image description generator for Stable Diffusion. "
                    "Output a concise English visual description ONLY. "
                    "No reasoning, no abstract concepts. Only what can be seen."
                    + plot_context
                )
                user_text = (
                    req.scene_text[:1000] +
                    "\n\nIMMEDIATELY output a short English image description (1-3 sentences). "
                    "Visual details only. NO explanation. NO reasoning. Start with the description directly."
                )
            num_predict = 128
        else:
            # current
            if _is_tag_based:
                system_prompt = (
                    "You are an image prompt generator for Stable Diffusion. "
                    f"Output ONLY {_fmt_label}-style image tags, comma-separated. "
                    "Do NOT think out loud. Do NOT explain. Output tags immediately."
                    + plot_context
                )
                user_text = (
                    req.scene_text[:1000] +
                    f"\n\nOutput ONLY {_fmt_label}-style image tags in English, comma-separated. "
                    "No explanation. No reasoning. Tags only."
                )
            else:
                system_prompt = (
                    "You are an image prompt generator for Stable Diffusion. "
                    "Output ONLY a concise English visual description. "
                    "Do NOT think out loud. Do NOT explain. Output the description immediately."
                    + plot_context
                )
                user_text = (
                    req.scene_text[:1000] +
                    "\n\nOutput ONLY a short English image description (2-4 sentences). "
                    "Describe characters, setting, mood, and lighting. No explanation. Visual details only."
                )
            num_predict = 150

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]

        vram_lock = get_vram_lock()
        vram_lock.acquire()
        try:
            try:
                img_prompt = LLM_BACKENDS[backend_id]["chat"](messages, req.llm_model, json_mode=False, options={"num_predict": num_predict})
            except Exception as e:
                return {"error": f"prompt generation failed: {e}"}
        finally:
            vram_lock.release()

        img_prompt = re.sub(r'#(\w)', r'\1', img_prompt).strip().strip('"').strip("'")
        if not img_prompt:
            return {"error": "empty prompt"}

    vram_lock_t2i = get_vram_lock()
    vram_lock_t2i.acquire()
    try:
        try:
            from def_kari.workers._t2i_generate import generate_image
            _t2i_backend = req.t2i_backend
            _t2i_model = _t2i_model_resolved or None
            img_path = generate_image(
                prompt=img_prompt,
                width=width,
                height=height,
                model_name=_t2i_model,
                backend=_t2i_backend,
            )
        except Exception as e:
            return {"error": f"image generation failed: {e}", "prompt": img_prompt}
    finally:
        vram_lock_t2i.release()

    filename = os.path.basename(img_path)
    _last_novel_t2i_debug["prompt_generated"] = img_prompt
    _last_novel_t2i_debug["url"] = f"/api/novel/image/{filename}"
    return {"prompt": img_prompt, "image_url": f"/api/novel/image/{filename}"}


@router.get("/t2i/debug")
def get_novel_t2i_debug():
    return _last_novel_t2i_debug


@router.get("/image/{filename}")
def get_novel_image(filename: str):
    from def_kari.workers._t2i_generate import ASSET_DIR
    path = (ASSET_DIR / filename).resolve()
    if not str(path).startswith(str(ASSET_DIR.resolve())) or not path.exists():
        return {"error": "Image not found"}
    return FileResponse(str(path), media_type="image/png")
