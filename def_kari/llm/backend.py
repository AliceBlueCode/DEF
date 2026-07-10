"""LLMバックエンド切替(基本設計2.3節)

ローカルバックエンド(TGW/Ollama)はハードコード。
外部APIサービスはdata/llm_services.jsonから動的に読み込み。
"""

import json
import os
from pathlib import Path

from def_kari.llm.adapters import tgw, ollama

_LLM_SERVICES_PATH = Path(__file__).parent.parent.parent / "data" / "llm_services.json"

# ローカルバックエンド（ハードコード）
LLM_BACKENDS = {
    "textgen_webui": {
        "chat": tgw.chat,
        "list_models": tgw.list_models,
        "default_model": tgw.MODEL,
    },
    "ollama": {
        "chat": ollama.chat,
        "list_models": ollama.list_models,
        "default_model": ollama.MODEL,
    },
}

LLM_BACKEND_LABELS = {
    "textgen_webui": "text-generation-webui (ローカル)",
    "ollama": "Ollama (ローカル)",
}

# 外部APIサービス（JSONから動的読み込み）
def _load_external_services():
    if not _LLM_SERVICES_PATH.exists():
        return []
    try:
        with open(_LLM_SERVICES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _register_external_services():
    for svc in _load_external_services():
        svc_id = svc["id"]
        svc_type = svc.get("type", "openai_compatible")
        api_url = svc["api_url"]
        api_key_service = svc.get("api_key_service", svc_id)
        default_model = svc.get("default_model", "")

        if svc_type == "gemini":
            from def_kari.llm.adapters.gemini import make_chat_fn
            chat_fn, list_fn = make_chat_fn(api_url, api_key_service, default_model)
        elif svc_type == "anthropic":
            from def_kari.llm.adapters.anthropic import make_chat_fn
            chat_fn, list_fn = make_chat_fn(api_url, api_key_service, default_model)
        else:
            from def_kari.llm.adapters.openai import make_chat_fn
            chat_fn, list_fn = make_chat_fn(api_url, api_key_service, default_model)

        LLM_BACKENDS[svc_id] = {
            "chat": chat_fn,
            "list_models": list_fn,
            "default_model": default_model,
        }
        LLM_BACKEND_LABELS[svc_id] = svc["label"]


_register_external_services()

DEFAULT_LLM_BACKEND = os.environ.get("LLM_BACKEND", "openai")
if DEFAULT_LLM_BACKEND not in LLM_BACKENDS:
    DEFAULT_LLM_BACKEND = "openai"
