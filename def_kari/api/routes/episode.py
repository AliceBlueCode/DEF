"""Episode API routes."""

import os
import json as _json

from fastapi import APIRouter
from pydantic import BaseModel

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
