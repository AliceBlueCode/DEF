"""Settings API routes."""

import os
import threading

from fastapi import APIRouter
from pydantic import BaseModel

_settings_lock = threading.Lock()

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


@router.get("/version")
def get_version():
    from def_kari import __version__
    return {"version": __version__}


@router.get("/")
def get_settings():
    return {"settings": load_settings()}


class SaveSettingsRequest(BaseModel):
    settings: dict


@router.post("/")
def update_settings(req: SaveSettingsRequest):
    from def_kari.settings import PERSISTED_KEYS, DATA_DIR, SETTINGS_PATH
    import json as _j
    with _settings_lock:
        existing = load_settings()
        for k, v in req.settings.items():
            if k in PERSISTED_KEYS:
                existing[k] = v
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            _j.dump(existing, f, ensure_ascii=False, indent=2)
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


@router.get("/llm-models")
def get_llm_models(backend: str = ""):
    if not backend or backend not in LLM_BACKENDS:
        return {"models": [], "default": ""}
    try:
        models = LLM_BACKENDS[backend]["list_models"]() or []
    except Exception:
        models = []
    return {"models": models, "default": LLM_BACKENDS[backend].get("default_model", "")}


@router.get("/load-llm-model")
def load_llm_model(backend: str = "", model: str = ""):
    if backend == "textgen_webui" and model:
        from def_kari.llm.adapters.tgw import load_model
        err = load_model(model)
        if err:
            return {"status": "error", "message": err}
        return {"status": "ok"}
    return {"status": "unsupported"}


@router.get("/t2i-models")
def get_t2i_models(backend: str = ""):
    models: list[str] = []
    workflows: list[str] = []
    if backend == "a1111":
        try:
            from def_kari.workers._t2i_generate import list_a1111_models
            models = list_a1111_models() or []
        except Exception:
            pass
    elif backend == "comfyui":
        try:
            from def_kari.workers._t2i_generate import list_comfyui_models, list_comfyui_workflows
            models = list_comfyui_models() or []
            workflows = list_comfyui_workflows() or []
        except Exception:
            pass
    elif backend == "huggingface":
        models = [
            "black-forest-labs/FLUX.1-schnell",
            "stabilityai/stable-diffusion-xl-base-1.0",
            "stabilityai/stable-diffusion-2-1",
        ]
    return {"models": models, "workflows": workflows}


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


_CIVITAI_MODELS_PATH = _Path(__file__).parent.parent.parent.parent / "data" / "civitai_models.json"
_LLM_PROFILES_DIR = _Path(__file__).parent.parent.parent.parent / "data" / "llm_profiles"


@router.get("/llm-profile")
def get_llm_profile(model: str = ""):
    if not model:
        return {"profile": {}}
    from def_kari.models.registry import get_llm_profile as _get, DEFAULT_QUIRKS
    return {"profile": _get(model), "default_quirks": DEFAULT_QUIRKS}


class SaveLlmProfileRequest(BaseModel):
    model: str
    profile: dict


@router.post("/llm-profile")
def save_llm_profile(req: SaveLlmProfileRequest):
    if not req.model:
        return {"error": "model required"}
    from def_kari.models.registry import _save_profile
    _save_profile(req.model, req.profile)
    return {"status": "ok"}


@router.get("/civitai-models")
def get_civitai_models():
    if not _CIVITAI_MODELS_PATH.exists():
        return {"models": []}
    try:
        return {"models": _json.loads(_CIVITAI_MODELS_PATH.read_text(encoding="utf-8"))}
    except Exception:
        return {"models": []}


class AddCivitaiModelRequest(BaseModel):
    label: str
    model_air: str


@router.post("/civitai-models")
def add_civitai_model(req: AddCivitaiModelRequest):
    models = get_civitai_models()["models"]
    if any(m["model_air"] == req.model_air for m in models):
        return {"status": "already_exists"}
    models.append({"label": req.label or req.model_air, "model_air": req.model_air})
    _CIVITAI_MODELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CIVITAI_MODELS_PATH.write_text(_json.dumps(models, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok"}


@router.delete("/civitai-models/{index}")
def delete_civitai_model(index: int):
    models = get_civitai_models()["models"]
    if index < 0 or index >= len(models):
        return {"error": "out of range"}
    models.pop(index)
    _CIVITAI_MODELS_PATH.write_text(_json.dumps(models, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "ok"}


_HF_MODELS_PATH = _Path(__file__).parent.parent.parent.parent / "data" / "hf_models.json"

_HF_DEFAULT_MODELS = [
    {"label": "FLUX.1-schnell", "model_id": "black-forest-labs/FLUX.1-schnell"},
    {"label": "Stable Diffusion XL", "model_id": "stabilityai/stable-diffusion-xl-base-1.0"},
    {"label": "Stable Diffusion 2.1", "model_id": "stabilityai/stable-diffusion-2-1"},
]


def _load_hf_models() -> list[dict]:
    if not _HF_MODELS_PATH.exists():
        return list(_HF_DEFAULT_MODELS)
    try:
        return _json.loads(_HF_MODELS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return list(_HF_DEFAULT_MODELS)


def _save_hf_models(models: list[dict]) -> None:
    _HF_MODELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _HF_MODELS_PATH.write_text(_json.dumps(models, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/hf-models")
def get_hf_models():
    return {"models": _load_hf_models()}


class AddHfModelRequest(BaseModel):
    label: str
    model_id: str


@router.post("/hf-models")
def add_hf_model(req: AddHfModelRequest):
    models = _load_hf_models()
    if any(m["model_id"] == req.model_id for m in models):
        return {"status": "already_exists"}
    models.append({"label": req.label or req.model_id, "model_id": req.model_id})
    _save_hf_models(models)
    return {"status": "ok"}


@router.delete("/hf-models/{index}")
def delete_hf_model(index: int):
    models = _load_hf_models()
    if index < 0 or index >= len(models):
        return {"error": "out of range"}
    models.pop(index)
    _save_hf_models(models)
    return {"status": "ok"}


_BACKEND_DIR_DEFS = [
    {"id": "textgen_webui", "label": "TextGen WebUI (TGW)", "dir_env": "TEXTGEN_WEBUI_DIR", "url_env": None,              "default_url": None},
    {"id": "voicevox",      "label": "VOICEVOX",            "dir_env": "VOICEVOX_DIR",      "url_env": "VOICEVOX_URL",    "default_url": "http://127.0.0.1:50021"},
    {"id": "irodori",       "label": "Irodori-TTS",         "dir_env": "IRODORI_TTS_DIR",   "url_env": "IRODORI_TTS_URL", "default_url": "http://127.0.0.1:8088"},
    {"id": "kokoro",        "label": "Kokoro TTS",          "dir_env": "KOKORO_TTS_DIR",    "url_env": "KOKORO_TTS_URL",  "default_url": "http://127.0.0.1:8766"},
    {"id": "a1111",         "label": "A1111 (SD WebUI)",    "dir_env": "A1111_DIR",         "url_env": "A1111_URL",       "default_url": "http://localhost:7860"},
    {"id": "comfyui",       "label": "ComfyUI",             "dir_env": "COMFYUI_DIR",       "url_env": "COMFYUI_URL",     "default_url": "http://127.0.0.1:8188"},
]

_ENV_PATH = _Path(__file__).parent.parent.parent.parent / ".env"


def _load_env_file() -> dict[str, str]:
    result: dict[str, str] = {}
    if not _ENV_PATH.exists():
        return result
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        result[k.strip()] = v.strip()
    return result


def _save_env_file(updates: dict[str, str]) -> None:
    existing_lines = []
    if _ENV_PATH.exists():
        existing_lines = _ENV_PATH.read_text(encoding="utf-8").splitlines()
    written_keys: set[str] = set()
    new_lines = []
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        k = stripped.partition("=")[0].strip()
        if k in updates:
            new_lines.append(f"{k}={updates[k]}")
            written_keys.add(k)
        else:
            new_lines.append(line)
    for k, v in updates.items():
        if k not in written_keys:
            new_lines.append(f"{k}={v}")
    _ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


@router.get("/launch-backend")
def launch_backend(id: str = ""):
    from def_kari import backends as _be
    _map = {
        "voicevox":      (_be.is_voicevox_running, _be.start_voicevox),
        "irodori":       (_be.is_irodori_running,  _be.start_irodori),
        "kokoro":        (_be.is_kokoro_running,   _be.start_kokoro),
        "textgen_webui": (_be.is_tgw_running,      _be.start_tgw),
        "ollama":        (_be.is_ollama_running,   _be.start_ollama),
        "a1111":         (_be.is_a1111_running,     _be.start_a1111),
        "comfyui":       (_be.is_comfyui_running,   _be.start_comfyui),
    }
    if id not in _map:
        return {"status": "unknown"}
    is_running, start = _map[id]
    if is_running():
        return {"status": "already_running"}
    err = start()
    if err:
        return {"status": "error", "message": err}
    return {"status": "launched"}


@router.get("/t2i-quality")
def get_t2i_quality(model: str = ""):
    from def_kari.models.t2i_profiles import get_quality_settings
    quality_tags, negative_prompt = get_quality_settings(model or None)
    return {"quality_tags": quality_tags, "negative_prompt": negative_prompt}


class SaveT2iQualityRequest(BaseModel):
    model: str
    quality_tags: str
    negative_prompt: str


@router.post("/t2i-quality")
def save_t2i_quality(req: SaveT2iQualityRequest):
    if not req.model:
        return {"error": "model required"}
    from def_kari.models.t2i_profiles import save_quality_settings
    save_quality_settings(req.model, req.quality_tags, req.negative_prompt)
    return {"status": "ok"}


@router.get("/t2i-profile")
def get_t2i_profile(model: str = ""):
    from def_kari.models.t2i_profiles import get_profile
    return {"profile": get_profile(model or None)}


class SaveT2iProfileRequest(BaseModel):
    model: str
    profile: dict


@router.post("/t2i-profile")
def save_t2i_profile(req: SaveT2iProfileRequest):
    if not req.model:
        return {"error": "model required"}
    from def_kari.models.t2i_profiles import save_profile
    save_profile(req.model, req.profile)
    return {"status": "ok"}


@router.get("/stop-backend")
def stop_backend(id: str = ""):
    from def_kari import backends as _be
    _map = {
        "voicevox":      _be.stop_voicevox,
        "irodori":       _be.stop_irodori,
        "kokoro":        _be.stop_kokoro,
        "textgen_webui": _be.stop_tgw,
        "ollama":        _be.stop_ollama,
        "a1111":         _be.stop_a1111,
        "comfyui":       _be.stop_comfyui,
    }
    if id not in _map:
        return {"status": "unknown"}
    err = _map[id]()
    if err:
        return {"status": "error", "message": err}
    return {"status": "stopped"}


@router.get("/backend-dirs")
def get_backend_dirs():
    env = _load_env_file()
    values = {}
    for b in _BACKEND_DIR_DEFS:
        if b["dir_env"]:
            values[b["dir_env"]] = os.environ.get(b["dir_env"], env.get(b["dir_env"], ""))
        if b["url_env"]:
            values[b["url_env"]] = os.environ.get(b["url_env"], env.get(b["url_env"], b["default_url"] or ""))
    return {"backends": _BACKEND_DIR_DEFS, "values": values}


class SaveBackendDirsRequest(BaseModel):
    values: dict


@router.post("/backend-dirs")
def save_backend_dirs(req: SaveBackendDirsRequest):
    allowed_env_vars = {
        ev
        for b in _BACKEND_DIR_DEFS
        for ev in [b.get("dir_env"), b.get("url_env")]
        if ev
    }
    filtered = {k: v for k, v in req.values.items() if k in allowed_env_vars}
    _save_env_file(filtered)
    for k, v in filtered.items():
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    return {"status": "ok"}


@router.get("/browse-dir")
def browse_dir():
    import subprocess
    import sys
    script = (
        "import tkinter; from tkinter import filedialog; "
        "root = tkinter.Tk(); root.withdraw(); "
        "root.wm_attributes('-topmost', True); "
        "path = filedialog.askdirectory(title='フォルダを選択'); "
        "print(path if path else '', end='')"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=60,
        )
        return {"path": result.stdout.strip()}
    except Exception as e:
        return {"path": "", "error": str(e)}


class TestBackendRequest(BaseModel):
    url: str


@router.post("/test-backend")
def test_backend(req: TestBackendRequest):
    import time
    import urllib.request
    try:
        start = time.time()
        with urllib.request.urlopen(req.url, timeout=5) as r:
            ms = int((time.time() - start) * 1000)
            return {"ok": True, "status": r.status, "ms": ms}
    except Exception as e:
        return {"ok": False, "error": str(e)}
