"""AnthropicAdapter: Anthropic Claude API（外部API）"""

import os

import requests

ANTHROPIC_API_URL = "https://api.anthropic.com/v1"
MODEL = "claude-sonnet-4-6"
API_VERSION = "2023-06-01"


def make_chat_fn(api_url: str, api_key_service: str, default_model: str):
    """JSON定義からAnthropic互換のchat関数を生成する。"""
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
        system_text = ""
        api_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text = (system_text + "\n" + m["content"]).strip() if system_text else m["content"]
            else:
                role = "assistant" if m["role"] == "assistant" else "user"
                content = m.get("content") or ""
                if not content:
                    continue
                if api_messages and api_messages[-1]["role"] == role:
                    api_messages[-1]["content"] += "\n" + content
                else:
                    api_messages.append({"role": role, "content": content})

        if not api_messages:
            api_messages.append({"role": "user", "content": system_text or "Hello"})
            system_text = ""

        if api_messages[0]["role"] != "user":
            api_messages.insert(0, {"role": "user", "content": "（会話を続けてください）"})

        body = {
            "model": model or default_model,
            "messages": api_messages,
            "max_tokens": (options or {}).get("num_predict", 1024),
        }
        if system_text:
            body["system"] = system_text

        print(f"[ANTHROPIC] request model={body['model']}, max_tokens={body['max_tokens']}, messages={len(api_messages)}")
        resp = requests.post(
            f"{api_url}/messages",
            headers={
                "x-api-key": _get_key(),
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            json=body,
            timeout=120,
        )
        if resp.status_code != 200:
            print(f"[ANTHROPIC] error {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
        content_blocks = resp.json().get("content", [])
        return "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")

    def _list_models():
        return [default_model]

    return _chat, _list_models


def _api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        try:
            from def_kari.secrets_store import get_api_key
            key = get_api_key("anthropic")
        except Exception:
            pass
    if not key:
        raise RuntimeError(
            "Anthropic APIキーが設定されていません。"
            "APIキー管理から設定してください。"
        )
    return key


def chat(
    messages: list[dict],
    model: str,
    json_mode: bool = True,
    options: dict | None = None,
) -> str:
    system_text = ""
    api_messages = []
    for m in messages:
        if m["role"] == "system":
            system_text = (system_text + "\n" + m["content"]).strip() if system_text else m["content"]
        else:
            role = "assistant" if m["role"] == "assistant" else "user"
            content = m.get("content") or ""
            if not content:
                continue
            # 連続同一ロール回避: 直前と同じロールなら結合
            if api_messages and api_messages[-1]["role"] == role:
                api_messages[-1]["content"] += "\n" + content
            else:
                api_messages.append({"role": role, "content": content})

    if not api_messages:
        api_messages.append({"role": "user", "content": system_text or "Hello"})
        system_text = ""

    # Anthropic APIはuserで始まる必要がある
    if api_messages[0]["role"] != "user":
        api_messages.insert(0, {"role": "user", "content": "（会話を続けてください）"})

    body = {
        "model": model or MODEL,
        "messages": api_messages,
        "max_tokens": (options or {}).get("num_predict", 1024),
    }
    if system_text:
        body["system"] = system_text

    print(f"[ANTHROPIC] request model={body['model']}, max_tokens={body['max_tokens']}, messages={len(api_messages)}")
    print(f"[ANTHROPIC] first msg role={api_messages[0]['role']}, content[:100]={api_messages[0]['content'][:100]}")

    resp = requests.post(
        f"{ANTHROPIC_API_URL}/messages",
        headers={
            "x-api-key": _api_key(),
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        },
        json=body,
        timeout=120,
    )
    if resp.status_code != 200:
        print(f"[ANTHROPIC] error {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    content_blocks = resp.json().get("content", [])
    return "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")


def list_models() -> list[str]:
    return [MODEL]
