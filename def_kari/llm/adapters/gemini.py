"""GeminiLlmAdapter: Google Gemini API(外部API)— リモートフォールバック"""

import os

import requests

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MODEL = "gemini-2.5-flash"


def make_chat_fn(api_url: str, api_key_service: str, default_model: str):
    """JSON定義からGemini互換のchat関数を生成する。"""
    def _get_key():
        key = os.environ.get(f"{api_key_service.upper()}_API_KEY")
        if not key:
            try:
                from def_kari.secrets_store import get_api_key
                key = get_api_key(api_key_service)
            except Exception:
                pass
        if not key:
            raise RuntimeError(f"{api_key_service} APIキーが設定されていません。")
        return key

    def _chat(messages, model, json_mode=True, options=None):
        system_parts = []
        contents = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                role = "model" if m["role"] == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})
        if not contents:
            contents.append({"role": "user", "parts": [{"text": "\n".join(system_parts)}]})
            system_parts = []
        body = {"contents": contents}
        if system_parts:
            body["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
        generation_config = {}
        if json_mode:
            generation_config["responseMimeType"] = "application/json"
        if options and "num_predict" in options:
            generation_config["maxOutputTokens"] = options["num_predict"]
        if generation_config:
            body["generationConfig"] = generation_config
        resp = requests.post(
            f"{api_url}/{model or default_model}:generateContent",
            params={"key": _get_key()},
            json=body,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        cand = data.get("candidates", [{}])[0]
        if not cand.get("content"):
            reason = cand.get("finishReason") or data.get("promptFeedback", {}).get("blockReason", "unknown")
            raise RuntimeError(f"Gemini: コンテンツなし (finishReason={reason})")
        return cand["content"]["parts"][0]["text"]

    def _list_models():
        try:
            resp = requests.get(api_url, params={"key": _get_key()}, timeout=10)
            resp.raise_for_status()
            return [
                m["name"].removeprefix("models/")
                for m in resp.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
        except Exception:
            return []

    return _chat, _list_models


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        try:
            from def_kari.secrets_store import get_api_key
            key = get_api_key("gemini")
        except Exception:
            pass
    if not key:
        raise RuntimeError(
            "Gemini APIキーが設定されていません。"
            "APIキー管理から設定してください。"
        )
    return key


def chat(
    messages: list[dict],
    model: str,
    json_mode: bool = True,
    options: dict | None = None,
) -> str:
    system_parts = []
    contents = []
    for m in messages:
        if m["role"] == "system":
            system_parts.append(m["content"])
        else:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

    if not contents:
        contents.append({"role": "user", "parts": [{"text": "\n".join(system_parts)}]})
        system_parts = []

    body: dict = {"contents": contents}
    if system_parts:
        body["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}

    generation_config: dict = {}
    if json_mode:
        generation_config["responseMimeType"] = "application/json"
    if options and "num_predict" in options:
        generation_config["maxOutputTokens"] = options["num_predict"]
    if generation_config:
        body["generationConfig"] = generation_config

    resp = requests.post(
        f"{GEMINI_API_URL}/{model or MODEL}:generateContent",
        params={"key": _api_key()},
        json=body,
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    cand = data.get("candidates", [{}])[0]
    if not cand.get("content"):
        reason = cand.get("finishReason") or data.get("promptFeedback", {}).get("blockReason", "unknown")
        raise RuntimeError(f"Gemini: コンテンツなし (finishReason={reason})")
    return cand["content"]["parts"][0]["text"]


def list_models() -> list[str]:
    resp = requests.get(GEMINI_API_URL, params={"key": _api_key()}, timeout=10)
    resp.raise_for_status()
    return [
        m["name"].removeprefix("models/")
        for m in resp.json().get("models", [])
        if "generateContent" in m.get("supportedGenerationMethods", [])
    ]
