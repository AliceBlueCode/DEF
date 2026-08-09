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


_COMPATIBLE_IDS: set[str] = set()


def _register_compatible_backends():
    try:
        from def_kari.compatible_backends_store import all_backends_with_keys
        from def_kari.llm.adapters.compatible import make_chat_fn
        for entry in all_backends_with_keys():
            if "llm" not in entry.get("capabilities", ["llm"]):
                continue
            name = entry["name"]
            chat_fn, list_fn = make_chat_fn(
                base_url=entry["base_url"],
                api_key=entry["api_key"],
                default_model=entry["model"],
                extra_headers=entry.get("extra_headers") or None,
            )
            LLM_BACKENDS[name] = {
                "chat": chat_fn,
                "list_models": list_fn,
                "default_model": entry["model"],
            }
            LLM_BACKEND_LABELS[name] = entry.get("label", name)
            _COMPATIBLE_IDS.add(name)
    except Exception:
        pass


_register_compatible_backends()

DEFAULT_LLM_BACKEND = os.environ.get("LLM_BACKEND", "openai")
if DEFAULT_LLM_BACKEND not in LLM_BACKENDS:
    # "openai"はdata/llm_services.json（gitignore対象）経由でのみ登録されるため、
    # その設定が無い環境（新規clone等）では常時ハードコード済みのtextgen_webuiへ逃がす
    DEFAULT_LLM_BACKEND = "textgen_webui"
