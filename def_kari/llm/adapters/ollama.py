"""OllamaAdapter: Ollama(ローカル)— フォールバック"""

import json as _json
import os

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"

MODEL = os.environ.get("OLLAMA_DEFAULT_MODEL", "huihui_ai/qwen2.5-abliterate:7b")


def chat(
    messages: list[dict],
    model: str,
    json_mode: bool = True,
    options: dict | None = None,
) -> str:
    payload = {"model": model, "messages": messages, "stream": False}
    if json_mode:
        payload["format"] = "json"
    if options:
        payload["options"] = options

    resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    if not data["message"]["content"]:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=300)
        resp.raise_for_status()
        data = resp.json()
    return data["message"]["content"]


def list_models() -> list[str]:
    resp = requests.get(OLLAMA_TAGS_URL, timeout=10)
    resp.raise_for_status()
    return [m["name"] for m in resp.json().get("models", [])]
