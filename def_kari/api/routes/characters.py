"""Character API routes."""

import io
import os
import re
import shutil
from pathlib import Path
from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from def_kari.characters import load_profiles, get_character, list_character_choices, get_raw_profile, save_profile
from def_kari.settings import load_settings

router = APIRouter()

_BASE = Path(__file__).parent.parent.parent.parent
_CHAR_DIRS = [
    _BASE / "data" / "public" / "characters",
    _BASE / "data" / "private" / "characters",
]
_SAFE_ID_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


def _find_char_dir(character_id: str) -> Path | None:
    if not _SAFE_ID_RE.match(character_id):
        return None
    for d in _CHAR_DIRS:
        p = d / character_id
        if p.is_dir():
            return p
    return None


@router.get("/")
def list_characters():
    profiles = load_profiles()
    choices = list_character_choices(profiles)
    result = []
    for cid, name in choices:
        char = get_character(cid, profiles)
        image_color = char.get("image_color") if char else None
        result.append({"id": cid, "name": name, "image_color": image_color})
    return {"characters": result}


@router.get("/{character_id}")
def get_character_detail(character_id: str):
    profiles = load_profiles()
    char = get_character(character_id, profiles)
    if not char:
        return {"error": "Character not found"}
    return {"character": char}


@router.get("/{character_id}/icon")
def get_character_icon(character_id: str):
    d = _find_char_dir(character_id)
    if d:
        icon = d / "icon.png"
        if icon.exists():
            return FileResponse(str(icon), media_type="image/png")
    return {"error": "Icon not found"}


@router.get("/{character_id}/standing")
def get_character_standing(character_id: str):
    d = _find_char_dir(character_id)
    if d:
        standing = d / "standing.png"
        if standing.exists():
            return FileResponse(str(standing), media_type="image/png")
    return {"error": "Standing image not found"}


@router.get("/{character_id}/raw-profile")
def get_character_raw_profile(character_id: str):
    if not _SAFE_ID_RE.match(character_id):
        return {"error": "Invalid character ID"}
    return {"profile": get_raw_profile(character_id)}


class SaveRawProfileRequest(BaseModel):
    profile: dict


@router.put("/{character_id}/raw-profile")
def save_character_raw_profile(character_id: str, req: SaveRawProfileRequest):
    if not _SAFE_ID_RE.match(character_id):
        return {"error": "Invalid character ID"}
    save_profile(character_id, req.profile)
    return {"status": "ok"}


class SaveVoiceSettingsRequest(BaseModel):
    backend: str
    speaker_id: int | str


@router.post("/{character_id}/voice-settings")
def save_voice_settings(character_id: str, req: SaveVoiceSettingsRequest):
    if not _SAFE_ID_RE.match(character_id):
        return {"error": "Invalid character ID"}
    raw = get_raw_profile(character_id)
    dmc = raw.setdefault("default_model_config", {})
    if req.backend == "voicevox":
        dmc["voicevox_speaker_id"] = req.speaker_id
    elif req.backend == "irodori":
        dmc["irodori_speaker_id"] = req.speaker_id
    save_profile(character_id, raw)
    return {"status": "ok"}


@router.post("/{character_id}/icon")
async def upload_icon(character_id: str, file: UploadFile = File(...)):
    if not _SAFE_ID_RE.match(character_id):
        return {"error": "Invalid character ID"}
    from PIL import Image as _PILImage
    d = _find_char_dir(character_id) or (_CHAR_DIRS[0] / character_id)
    d.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    img = _PILImage.open(io.BytesIO(content)).convert("RGB")
    img = img.resize((512, 512), _PILImage.LANCZOS)
    img.save(str(d / "icon.png"), "PNG")
    return {"status": "ok"}


@router.post("/{character_id}/standing")
async def upload_standing(character_id: str, file: UploadFile = File(...)):
    if not _SAFE_ID_RE.match(character_id):
        return {"error": "Invalid character ID"}
    from PIL import Image as _PILImage
    d = _find_char_dir(character_id) or (_CHAR_DIRS[0] / character_id)
    d.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    img = _PILImage.open(io.BytesIO(content)).convert("RGB")
    img = img.resize((832, 1216), _PILImage.LANCZOS)
    img.save(str(d / "standing.png"), "PNG")
    return {"status": "ok"}


class GenerateCharImageRequest(BaseModel):
    backend: str = ""
    model: str = ""


@router.post("/{character_id}/icon/generate")
def generate_icon(character_id: str, req: GenerateCharImageRequest):
    if not _SAFE_ID_RE.match(character_id):
        return {"error": "Invalid character ID"}
    profiles = load_profiles()
    char = get_character(character_id, profiles)
    appearance_tags = char.get("appearance_tags", "")
    if not appearance_tags:
        return {"error": "appearance_tags が設定されていません"}
    settings = load_settings()
    backend = req.backend or settings.get("t2i_backend", "")
    if not backend:
        return {"error": "T2Iバックエンドが未設定です"}
    model = req.model or settings.get(f"t2i_model_{backend}") or None
    prompt = f"portrait, face close-up, {appearance_tags}, white background, simple background"
    try:
        from def_kari.t2i.backend import generate_image
        image_path = generate_image(prompt=prompt, backend=backend, model=model, width=512, height=512)
        d = _find_char_dir(character_id) or (_CHAR_DIRS[0] / character_id)
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_path, d / "icon.png")
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}


@router.post("/{character_id}/standing/generate")
def generate_standing(character_id: str, req: GenerateCharImageRequest):
    if not _SAFE_ID_RE.match(character_id):
        return {"error": "Invalid character ID"}
    profiles = load_profiles()
    char = get_character(character_id, profiles)
    appearance_tags = char.get("appearance_tags", "")
    if not appearance_tags:
        return {"error": "appearance_tags が設定されていません"}
    settings = load_settings()
    backend = req.backend or settings.get("t2i_backend", "")
    if not backend:
        return {"error": "T2Iバックエンドが未設定です"}
    model = req.model or settings.get(f"t2i_model_{backend}") or None
    prompt = f"full body, standing, {appearance_tags}, white background, simple background"
    try:
        from def_kari.t2i.backend import generate_image
        image_path = generate_image(prompt=prompt, backend=backend, model=model, width=832, height=1216)
        d = _find_char_dir(character_id) or (_CHAR_DIRS[0] / character_id)
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_path, d / "standing.png")
        return {"status": "ok"}
    except Exception as e:
        return {"error": str(e)}
