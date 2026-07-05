"""DEF(kari) FastAPI backend."""

import os
import sys
import threading

# Ensure def_kari package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from def_kari.api.routes import chat, characters, settings, tts, novel, session, t2i, thought

from def_kari import __version__


def _auto_start():
    import time
    try:
        from def_kari.settings import load_settings
        from def_kari.backends import auto_start_backends, is_tgw_running
        s = load_settings()
        llm_backend = s.get("llm_backend", "textgen_webui")
        tts_backend = s.get("tts_backend", "voicevox")
        t2i_backend = s.get("t2i_backend", "a1111")
        results = auto_start_backends(llm_backend, tts_backend, t2i_backend)
        for name, err in results.items():
            if err:
                print(f"[autostart] {name}: {err}")
            else:
                print(f"[autostart] {name}: ok")

        if llm_backend == "textgen_webui":
            autoload = s.get("tgw_autoload_model", "")
            if autoload:
                print(f"[autostart] waiting for TGW to be ready for model load: {autoload}")
                for _ in range(36):  # 最大3分待つ
                    if is_tgw_running():
                        break
                    time.sleep(5)
                else:
                    print("[autostart] TGW did not start in time, skipping model load")
                    return
                from def_kari.llm.adapters.tgw import load_model, get_current_model
                current = get_current_model()
                if current:
                    print(f"[autostart] TGW model already loaded: {current}")
                else:
                    print(f"[autostart] loading TGW model: {autoload}")
                    err = load_model(autoload)
                    if err:
                        print(f"[autostart] TGW model load error: {err}")
                    else:
                        print(f"[autostart] TGW model loaded ok")
    except Exception as e:
        print(f"[autostart] error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_auto_start, daemon=True).start()
    yield


app = FastAPI(
    title="DEF(kari) API",
    version=__version__,
    description="DEF(kari) — Persistent Character Platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files for generated assets
_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# Load .env
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

# Load encrypted API keys into environment
_KEY_MAP = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepl": "DEEPL_API_KEY",
    "civitai": "CIVITAI_API_TOKEN",
    "huggingface": "HF_TOKEN",
}
try:
    from def_kari.secrets_store import get_api_key as _get_key, set_api_key as _set_key, STORE_PATH as _SP, KEY_PATH as _KP
    print(f"[API] secrets_store: store={_SP} exists={_SP.exists()}, key={_KP} exists={_KP.exists()}")

    # Migrate plain-text keys from mvp_settings.json → secrets_store (one-time)
    _MIGRATE_MAP = {"deepl_api_key": "deepl", "civitai_api_token": "civitai"}
    try:
        from def_kari.settings import load_settings as _load_s, SETTINGS_PATH as _SP2
        import json as _json
        _plain = _load_s()
        _migrated = False
        for _plain_key, _svc in _MIGRATE_MAP.items():
            _v = _plain.pop(_plain_key, None)
            if _v and not _get_key(_svc):
                _set_key(_svc, _v)
                print(f"[API] migrated {_plain_key} → secrets_store:{_svc}")
                _migrated = True
        if _migrated:
            _SP2.write_text(_json.dumps(_plain, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as _me:
        print(f"[API] migration warning: {_me}")

    for _svc, _env in _KEY_MAP.items():
        _val = _get_key(_svc)
        if _val:
            os.environ[_env] = _val
            print(f"[API] {_svc} key loaded")
        else:
            print(f"[API] {_svc} key not found in secrets_store")
except Exception as _e:
    import traceback
    traceback.print_exc()
    print(f"[API] Failed to load API keys: {_e}")

# Register routes
app.include_router(characters.router, prefix="/api/characters", tags=["characters"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(tts.router, prefix="/api/tts", tags=["tts"])
app.include_router(novel.router, prefix="/api/novel", tags=["novel"])
app.include_router(session.router, prefix="/api/session", tags=["session"])
app.include_router(t2i.router, prefix="/api/t2i", tags=["t2i"])
app.include_router(thought.router, prefix="/api/thought", tags=["thought"])


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}
