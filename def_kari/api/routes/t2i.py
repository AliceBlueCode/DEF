"""T2I API routes."""

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from def_kari.t2i.backend import generate_image
from def_kari.settings import load_settings

router = APIRouter()


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

    model = req.model or settings.get("t2i_model") or None
    width = req.width or settings.get("t2i_width", 512)
    height = req.height or settings.get("t2i_height", 768)

    try:
        image_path = generate_image(
            prompt=req.prompt,
            width=int(width),
            height=int(height),
            model=model,
            backend=backend,
            negative_prompt=req.negative_prompt,
            seed=req.seed,
            steps=req.steps,
            cfg_scale=req.cfg_scale,
        )
        with open(image_path, "rb") as f:
            image_bytes = f.read()
        return Response(content=image_bytes, media_type="image/png")
    except Exception as e:
        return {"error": str(e)}
