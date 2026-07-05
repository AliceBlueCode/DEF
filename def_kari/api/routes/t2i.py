"""T2I API routes."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from def_kari.t2i.backend import generate_image
from def_kari.settings import load_settings

router = APIRouter()

ASSET_DIR = (Path(__file__).parent.parent.parent.parent / "assets").resolve()
_last_t2i_debug: dict = {}


class T2IRequest(BaseModel):
    prompt: str
    backend: str = ""
    model: str = ""
    negative_prompt: str = ""
    width: int = 0
    height: int = 0
    seed: int = -1
    steps: int = 20
    cfg_scale: float = 7.0


@router.post("/")
def generate_t2i(req: T2IRequest):
    settings = load_settings()
    backend = req.backend or settings.get("t2i_backend", "")
    if not backend:
        return {"error": "T2Iバックエンドが設定されていません"}

    model = req.model or settings.get(f"t2i_model_{backend}") or None
    width = req.width or settings.get("t2i_width", 512)
    height = req.height or settings.get("t2i_height", 768)
    workflow = settings.get("comfyui_workflow", "default") if backend == "comfyui" else ""

    global _last_t2i_debug
    _last_t2i_debug = {
        "backend": backend,
        "model": model or "",
        "workflow": workflow,
        "prompt_input": req.prompt,
        "width": int(width),
        "height": int(height),
        "seed": req.seed,
        "steps": req.steps,
        "cfg_scale": req.cfg_scale,
    }
    try:
        from def_kari.models.t2i_profiles import get_quality_settings
        quality_tags, default_neg = get_quality_settings(model)
        prompt = req.prompt
        if quality_tags:
            prompt = f"{prompt}, {quality_tags}"
        negative_prompt = req.negative_prompt or default_neg

        _last_t2i_debug.update({
            "quality_tags": quality_tags,
            "prompt_final": prompt,
            "negative_prompt": negative_prompt,
        })

        from def_kari.resources.vram_lock import get_vram_lock
        _vram_lock = get_vram_lock()
        _vram_lock.acquire()
        try:
            image_path = generate_image(
                prompt=prompt,
                width=int(width),
                height=int(height),
                model=model,
                backend=backend,
                negative_prompt=negative_prompt,
                seed=req.seed,
                steps=req.steps,
                cfg_scale=req.cfg_scale,
                workflow_name=workflow,
            )
        finally:
            _vram_lock.release()
        filename = Path(image_path).name
        _last_t2i_debug["url"] = f"/api/t2i/image/{filename}"
        return {"url": f"/api/t2i/image/{filename}", "prompt": prompt}
    except Exception as e:
        _last_t2i_debug["error"] = str(e)
        return {"error": str(e)}


def set_t2i_debug(data: dict) -> None:
    global _last_t2i_debug
    _last_t2i_debug = data


@router.get("/debug")
def get_t2i_debug():
    return _last_t2i_debug


@router.get("/image/{filename}")
def get_t2i_image(filename: str):
    path = (ASSET_DIR / filename).resolve()
    if not str(path).startswith(str(ASSET_DIR)) or not path.exists():
        return {"error": "Image not found"}
    return FileResponse(str(path), media_type="image/png")
