"""Settings API routes."""

import os

from fastapi import APIRouter
from pydantic import BaseModel

from def_kari.settings import load_settings, save_settings
from def_kari.llm.backend import LLM_BACKENDS, LLM_BACKEND_LABELS, DEFAULT_LLM_BACKEND
from def_kari.config import T2I_BACKENDS, T2I_BACKEND_LABELS, DEFAULT_T2I_BACKEND

router = APIRouter()

_SERVICES = ("gemini", "openai", "anthropic")
_ENV_KEY_MAP = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


@router.get("/")
def get_settings():
    return {"settings": load_settings()}


class SaveSettingsRequest(BaseModel):
    settings: dict


@router.post("/")
def update_settings(req: SaveSettingsRequest):
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


@router.get("/api-keys")
def get_api_key_status():
    from def_kari.secrets_store import has_api_key
    return {svc: has_api_key(svc) for svc in _SERVICES}


class SetApiKeyRequest(BaseModel):
    api_key: str


@router.post("/api-keys/{service}")
def set_api_key_route(service: str, req: SetApiKeyRequest):
    if service not in _SERVICES:
        return {"error": "unknown service"}
    from def_kari.secrets_store import set_api_key
    set_api_key(service, req.api_key.strip())
    if req.api_key.strip():
        os.environ[_ENV_KEY_MAP[service]] = req.api_key.strip()
    return {"status": "ok"}


@router.delete("/api-keys/{service}")
def delete_api_key_route(service: str):
    if service not in _SERVICES:
        return {"error": "unknown service"}
    from def_kari.secrets_store import delete_api_key
    delete_api_key(service)
    os.environ.pop(_ENV_KEY_MAP[service], None)
    return {"status": "ok"}
