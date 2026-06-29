"""Character API routes."""

import os
from fastapi import APIRouter
from fastapi.responses import FileResponse
from def_kari.characters import load_profiles, get_character, list_character_choices

router = APIRouter()

_CHAR_DIRS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "..", "data", "public", "characters"),
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "..", "data", "private", "characters"),
]


def _find_char_dir(character_id: str) -> str | None:
    for d in _CHAR_DIRS:
        p = os.path.join(d, character_id)
        if os.path.isdir(p):
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
        icon = os.path.join(d, "icon.png")
        if os.path.exists(icon):
            return FileResponse(icon, media_type="image/png")
    return {"error": "Icon not found"}


@router.get("/{character_id}/standing")
def get_character_standing(character_id: str):
    d = _find_char_dir(character_id)
    if d:
        standing = os.path.join(d, "standing.png")
        if os.path.exists(standing):
            return FileResponse(standing, media_type="image/png")
    return {"error": "Standing image not found"}
