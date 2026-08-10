"""Settings API routes."""

import os
import threading

from fastapi import APIRouter
from pydantic import BaseModel

_settings_lock = threading.Lock()

from def_kari.settings import load_settings, save_settings
from def_kari.llm.backend import LLM_BACKENDS, LLM_BACKEND_LABELS, DEFAULT_LLM_BACKEND
from def_kari.config import DEFAULT_T2I_BACKEND
from def_kari.t2i.backend import T2I_BACKENDS, T2I_BACKEND_LABELS

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


@router.post("/jwt-secret/regenerate")
async def regenerate_jwt_secret_endpoint():
    """JWT秘密鍵を再生成し、全アクティブセッションのWS接続をcode=1008で強制切断する。

    マルチプレイ設計書§7で「設定タブから再生成可能」と決定されていたが未実装だった
    機能。再生成前に発行された全JWT（player_token/host_token含む）は新しい鍵で
    検証できなくなり無効になるため、参加者は招待コードで、ホストは再度セッション
    開始操作で入り直す必要がある。
    """
    from def_kari.settings import regenerate_jwt_secret
    regenerate_jwt_secret()

    from def_kari.api.routes.session import _sessions
    disconnected = 0
    for sess in list(_sessions.values()):
        connections = sess.get("ws_connections", {})
        for ws in list(connections.values()):
            try:
                await ws.close(code=1008)
                disconnected += 1
            except Exception:
                pass
        connections.clear()
    return {"status": "ok", "disconnected_connections": disconnected}


@router.get("/backends")
def get_backends():
    from def_kari.tts.backend import TTS_BACKENDS, TTS_BACKEND_LABELS, DEFAULT_TTS_BACKEND
    return {
        "llm": {
            "backends": list(LLM_BACKENDS.keys()),
            "labels": LLM_BACKEND_LABELS,
            "default": DEFAULT_LLM_BACKEND,
        },
        "tts": {
            "backends": list(TTS_BACKENDS.keys()),
            "labels": TTS_BACKEND_LABELS,
            "default": DEFAULT_TTS_BACKEND,
        },
        "t2i": {
            "backends": list(T2I_BACKENDS.keys()),
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
            "black-forest-labs/FLUX.1-dev",
            "stabilityai/stable-diffusion-3.5-large",
            "stabilityai/stable-diffusion-xl-base-1.0",
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
    from def_kari.models.registry import get_or_create_llm_profile, DEFAULT_QUIRKS
    return {"profile": get_or_create_llm_profile(model), "default_quirks": DEFAULT_QUIRKS}


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
    for v in updates.values():
        if "\n" in v or "\r" in v:
            raise ValueError("env value must not contain newline characters")
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


@router.get("/cloudflared-dir")
def get_cloudflared_dir():
    """cloudflared(Cloudflare Tunnel)のインストール先ディレクトリ。

    TGW/ComfyUI等のAI生成バックエンド(_BACKEND_DIR_DEFS)とは性質が異なる
    （AIモデル推論ではなく単なるネットワークトンネリングツール）ため、
    設定タブでは「バックエンド / APIキー」とは別セクションに分けて表示する
    （2026-08-10、混在させたところユーザーから違和感の指摘）。永続化先は
    同じ.envファイル(CLOUDFLARED_DIR)を使い回す。dual_run.py --cloudflare-tunnel
    が起動時にこれを読んでcloudflared.exeを探す。
    """
    env = _load_env_file()
    return {"dir": os.environ.get("CLOUDFLARED_DIR", env.get("CLOUDFLARED_DIR", ""))}


class SaveCloudflaredDirRequest(BaseModel):
    dir: str


@router.post("/cloudflared-dir")
def save_cloudflared_dir(req: SaveCloudflaredDirRequest):
    _save_env_file({"CLOUDFLARED_DIR": req.dir})
    if req.dir:
        os.environ["CLOUDFLARED_DIR"] = req.dir
    else:
        os.environ.pop("CLOUDFLARED_DIR", None)
    return {"status": "ok"}


class CompatibleBackendRequest(BaseModel):
    name: str
    base_url: str
    model: str = ""
    extra_headers: dict = {}
    capabilities: list[str] = ["llm"]
    label: str = ""
    api_key: str | None = None


@router.get("/compatible-backends")
def get_compatible_backends():
    from def_kari.compatible_backends_store import list_backends
    return {"backends": list_backends()}


@router.post("/compatible-backends")
def add_compatible_backend(req: CompatibleBackendRequest):
    from def_kari.compatible_backends_store import list_backends, save_backend
    existing = {b["name"] for b in list_backends()}
    if req.name in existing:
        return {"error": f"'{req.name}' は既に存在します"}
    save_backend(req.name, req.base_url, req.model, req.extra_headers,
                 req.capabilities, req.label, req.api_key)
    _reload_compatible_backends()
    return {"status": "ok"}


@router.put("/compatible-backends/{name}")
def update_compatible_backend(name: str, req: CompatibleBackendRequest):
    from def_kari.compatible_backends_store import save_backend
    save_backend(name, req.base_url, req.model, req.extra_headers,
                 req.capabilities, req.label, req.api_key)
    _reload_compatible_backends()
    return {"status": "ok"}


@router.delete("/compatible-backends/{name}")
def delete_compatible_backend(name: str):
    from def_kari.compatible_backends_store import delete_backend
    if not delete_backend(name):
        return {"error": "not found"}
    _reload_compatible_backends()
    return {"status": "ok"}


def _reload_compatible_backends():
    """追加・更新・削除後にLLM/TTS/T2I BACKENDSを即時反映する。compatible管理分だけ差し替える。"""
    from def_kari.compatible_backends_store import all_backends_with_keys
    entries = all_backends_with_keys()

    # LLM
    try:
        from def_kari.llm.backend import LLM_BACKENDS, LLM_BACKEND_LABELS, _COMPATIBLE_IDS
        from def_kari.llm.adapters.compatible import make_chat_fn
        for name in list(_COMPATIBLE_IDS):
            LLM_BACKENDS.pop(name, None)
            LLM_BACKEND_LABELS.pop(name, None)
        _COMPATIBLE_IDS.clear()
        for entry in entries:
            if "llm" not in entry.get("capabilities", ["llm"]):
                continue
            name = entry["name"]
            chat_fn, list_fn = make_chat_fn(
                base_url=entry["base_url"],
                api_key=entry["api_key"],
                default_model=entry["model"],
                extra_headers=entry.get("extra_headers") or None,
            )
            LLM_BACKENDS[name] = {"chat": chat_fn, "list_models": list_fn, "default_model": entry["model"]}
            LLM_BACKEND_LABELS[name] = entry.get("label", name)
            _COMPATIBLE_IDS.add(name)
    except Exception:
        pass

    # TTS
    try:
        from def_kari.tts.backend import TTS_BACKENDS, TTS_BACKEND_LABELS, _COMPATIBLE_TTS_IDS
        from def_kari.tts.adapters.compatible_tts import make_synthesize_fn
        for name in list(_COMPATIBLE_TTS_IDS):
            TTS_BACKENDS.pop(name, None)
            TTS_BACKEND_LABELS.pop(name, None)
        _COMPATIBLE_TTS_IDS.clear()
        for entry in entries:
            if "tts" not in entry.get("capabilities", []):
                continue
            name = entry["name"]
            TTS_BACKENDS[name] = make_synthesize_fn(
                base_url=entry["base_url"],
                api_key=entry["api_key"],
                default_model=entry.get("model", "tts-1"),
            )
            TTS_BACKEND_LABELS[name] = entry.get("label", name)
            _COMPATIBLE_TTS_IDS.add(name)
    except Exception:
        pass

    # T2I
    try:
        from def_kari.t2i.backend import T2I_BACKENDS as _T2I_B, T2I_BACKEND_LABELS as _T2I_L, _COMPATIBLE_T2I_IDS
        from def_kari.t2i.adapters.compatible import make_generate_fn
        for name in list(_COMPATIBLE_T2I_IDS):
            _T2I_B.pop(name, None)
            _T2I_L.pop(name, None)
        _COMPATIBLE_T2I_IDS.clear()
        for entry in entries:
            if "t2i" not in entry.get("capabilities", []):
                continue
            name = entry["name"]
            _T2I_B[name] = make_generate_fn(
                base_url=entry["base_url"],
                api_key=entry["api_key"],
                default_model=entry.get("model", ""),
                name=name,
                extra_headers=entry.get("extra_headers") or None,
            )
            _T2I_L[name] = entry.get("label", name)
            _COMPATIBLE_T2I_IDS.add(name)
    except Exception:
        pass


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
    """バックエンド疎通確認（意図的にSSRF相当の機能を持つ、ホストのローカルLAN上の
    ComfyUI/A1111等への到達性テスト）。main.py（ローカル専用）にのみ存在する。

    CSRF対策（8.16）はTestBackendCSRFMiddleware（api/main.py）で行う。FastAPIは
    TestBackendRequestのボディパースをこの関数本体の実行より前に行うため、
    ここでContent-Typeを検証しても手遅れ（text/plain等の不正な形式は既に422で
    弾かれた後か、運悪くdictとしてパースされた後）。ミドルウェアなら
    ルーティング解決前にヘッダーだけを見て確実に弾ける。
    """
    import time
    import urllib.request
    from urllib.parse import urlparse
    parsed = urlparse(req.url)
    if parsed.scheme not in ("http", "https"):
        return {"ok": False, "error": "Invalid URL scheme"}
    try:
        start = time.time()
        with urllib.request.urlopen(req.url, timeout=5) as r:
            ms = int((time.time() - start) * 1000)
            return {"ok": True, "status": r.status, "ms": ms}
    except Exception as e:
        return {"ok": False, "error": str(e)}
