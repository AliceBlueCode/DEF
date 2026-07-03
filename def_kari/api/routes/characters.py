"""Character API routes."""

import os
import re
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import FileResponse
from def_kari.characters import load_profiles, get_character, list_character_choices

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
    return {"characters": [{"id": cid, "name": name} for cid, name in choices]}


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
