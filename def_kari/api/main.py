"""DEF(kari) FastAPI backend."""

import os
import sys

# Ensure def_kari package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from def_kari.api.routes import chat, characters, settings, tts, episode, session

from def_kari import __version__

app = FastAPI(
    title="DEF(kari) API",
    version=__version__,
    description="Multimodal AI Creative Platform API",
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
_KEY_MAP = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
try:
    from def_kari.secrets_store import get_api_key as _get_key, STORE_PATH as _SP, KEY_PATH as _KP
    print(f"[API] secrets_store: store={_SP} exists={_SP.exists()}, key={_KP} exists={_KP.exists()}")
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
app.include_router(episode.router, prefix="/api/episode", tags=["episode"])
app.include_router(session.router, prefix="/api/session", tags=["session"])


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}
