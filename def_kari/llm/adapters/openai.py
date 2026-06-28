"""OpenAIAdapter: OpenAI API(外部API)— リモートフォールバック"""

import os

import requests

OPENAI_API_URL = "https://api.openai.com/v1"
MODEL = "gpt-4o-mini"


def make_chat_fn(api_url: str, api_key_service: str, default_model: str):
    """JSON定義からOpenAI互換のchat関数を生成する。"""
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
        body = {"model": model or default_model, "messages": messages}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if options and "num_predict" in options:
            body["max_tokens"] = options["num_predict"]
        resp = requests.post(
            f"{api_url}/chat/completions",
            headers={"Authorization": f"Bearer {_get_key()}"},
            json=body,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _list_models():
        try:
            resp = requests.get(
                f"{api_url}/models",
                headers={"Authorization": f"Bearer {_get_key()}"},
                timeout=10,
            )
            resp.raise_for_status()
            return sorted(m["id"] for m in resp.json().get("data", []))
        except Exception:
            return []

    return _chat, _list_models


def _api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        try:
            from def_kari.secrets_store import get_api_key
            key = get_api_key("openai")
        except Exception:
            pass
    if not key:
        raise RuntimeError(
            "OpenAI APIキーが設定されていません。"
            "APIキー管理から設定してください。"
        )
    return key


def chat(
    messages: list[dict],
    model: str,
    json_mode: bool = True,
    options: dict | None = None,
) -> str:
    body: dict = {"model": model or MODEL, "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if options and "num_predict" in options:
        body["max_tokens"] = options["num_predict"]

    resp = requests.post(
        f"{OPENAI_API_URL}/chat/completions",
        headers={"Authorization": f"Bearer {_api_key()}"},
        json=body,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def list_models() -> list[str]:
    resp = requests.get(
        f"{OPENAI_API_URL}/models",
        headers={"Authorization": f"Bearer {_api_key()}"},
        timeout=10,
    )
    resp.raise_for_status()
    return sorted(
        m["id"]
        for m in resp.json().get("data", [])
        if m["id"].startswith(("gpt-", "o1", "o3", "o4"))
    )
