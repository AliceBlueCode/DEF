"""Settings API routes."""

import os

from fastapi import APIRouter
from pydantic import BaseModel

from def_kari.settings import load_settings, save_settings
from def_kari.llm.backend import LLM_BACKENDS, LLM_BACKEND_LABELS, DEFAULT_LLM_BACKEND
from def_kari.config import T2I_BACKENDS, T2I_BACKEND_LABELS, DEFAULT_T2I_BACKEND

router = APIRouter()

import json as _json
from pathlib import Path as _Path

_API_SERVICES_PATH = _Path(__file__).parent.parent.parent.parent / "data" / "api_services.json"


def _load_api_services() -> list[dict]:
    if _API_SERVICES_PATH.exists():
        try:
            return _json.loads(_API_SERVICES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _env_map() -> dict[str, str]:
    return {s["id"]: s.get("env_var", f"{s['id'].upper()}_API_KEY") for s in _load_api_services()}


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


@router.get("/api-services")
def get_api_services():
    return {"services": _load_api_services()}


@router.get("/api-keys")
def get_api_key_status():
    from def_kari.secrets_store import has_api_key
    services = _load_api_services()
    return {s["id"]: has_api_key(s["id"]) for s in services}


class SetApiKeyRequest(BaseModel):
    api_key: str


@router.post("/api-keys/{service}")
def set_api_key_route(service: str, req: SetApiKeyRequest):
    env_map = _env_map()
    if service not in env_map:
        return {"error": "unknown service"}
    from def_kari.secrets_store import set_api_key
    set_api_key(service, req.api_key.strip())
    if req.api_key.strip():
        os.environ[env_map[service]] = req.api_key.strip()
    return {"status": "ok"}


@router.delete("/api-keys/{service}")
def delete_api_key_route(service: str):
    env_map = _env_map()
    if service not in env_map:
        return {"error": "unknown service"}
    from def_kari.secrets_store import delete_api_key
    delete_api_key(service)
    os.environ.pop(env_map[service], None)
    return {"status": "ok"}
