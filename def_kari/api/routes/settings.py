"""Settings API routes."""

from fastapi import APIRouter
from pydantic import BaseModel

from def_kari.settings import load_settings, save_settings
from def_kari.llm.backend import LLM_BACKENDS, LLM_BACKEND_LABELS, DEFAULT_LLM_BACKEND
from def_kari.config import T2I_BACKENDS, T2I_BACKEND_LABELS, DEFAULT_T2I_BACKEND

router = APIRouter()


@router.get("/")
def get_settings():
    return {"settings": load_settings()}


class SaveSettingsRequest(BaseModel):
    settings: dict


@router.post("/")
def update_settings(req: SaveSettingsRequest):
    # Simulate session_state for save_settings compatibility
    class FakeState(dict):
        def __getattr__(self, key):
            return self.get(key)
    state = FakeState(req.settings)
    save_settings(state)
    return {"status": "ok"}


@router.get("/backends")
def get_backends():
    return {
        "llm": {
            "backends": list(LLM_BACKENDS.keys()),
            "labels": LLM_BACKEND_LABELS,
            "default": DEFAULT_LLM_BACKEND,
        },
        "t2i": {
            "backends": T2I_BACKENDS,
            "labels": T2I_BACKEND_LABELS,
            "default": DEFAULT_T2I_BACKEND,
        },
    }
