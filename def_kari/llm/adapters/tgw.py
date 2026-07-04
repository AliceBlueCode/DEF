"""TgwAdapter: Text Generation WebUI(ローカル、OpenAI互換API)— デフォルト"""

import os
import re

import requests

_THINKING_PROCESS_RE = re.compile(r"^Here's a thinking process:.*", re.DOTALL)


def _extract_from_reasoning(text: str) -> str:
    """reasoning_contentからJSON応答または日本語テキストを抽出する。"""
    json_match = re.search(r'\n(\{.*)', text, re.DOTALL)
    if json_match:
        return json_match.group(1).strip()
    lines = text.split('\n')
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if line and not line.startswith(('-', '*', '#')) and not line[0].isdigit():
            jp_block = '\n'.join(lines[i:]).strip()
            if any(ord(c) > 0x3000 for c in jp_block):
                return jp_block
    return text

TEXTGEN_WEBUI_URL = os.environ.get("TEXTGEN_WEBUI_URL", "http://127.0.0.1:5000/v1")
MODEL = ""


def _headers() -> dict:
    api_key = os.environ.get("TEXTGEN_WEBUI_API_KEY")
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def chat(
    messages: list[dict],
    model: str,
    json_mode: bool = True,
    options: dict | None = None,
) -> str:
    body: dict = {"model": model or MODEL, "messages": messages}
    if options:
        if "num_predict" in options:
            body["max_tokens"] = options["num_predict"]
        for _pkey in ("temperature", "top_p", "top_k", "repetition_penalty", "frequency_penalty", "presence_penalty"):
            if _pkey in options:
                body[_pkey] = options[_pkey]
    print(f"[TGW] request max_tokens={body.get('max_tokens', 'NOT SET')}")

    resp = requests.post(
        f"{TEXTGEN_WEBUI_URL}/chat/completions",
        headers=_headers(),
        json=body,
        timeout=600,
    )
    resp.raise_for_status()
    _msg = resp.json()["choices"][0]["message"]
    _content = _msg.get("content") or ""
    _reasoning = _msg.get("reasoning_content") or ""
    print(f"[TGW] content len={len(_content)}, reasoning len={len(_reasoning)}")
    if _content:
        print(f"[TGW] content (first 200): {_content[:200]}")
    if _reasoning and not _content:
        print(f"[TGW] reasoning (last 300): ...{_reasoning[-300:]}")
    if not _content and _reasoning:
        _content = _extract_from_reasoning(_reasoning)
    if _THINKING_PROCESS_RE.match(_content):
        _content = _extract_from_reasoning(_content)
    return _content


def load_model(name: str) -> str | None:
    """指定モデルをTGWにロードする。エラー時はメッセージを返す。"""
    url = os.environ.get("TEXTGEN_WEBUI_URL", TEXTGEN_WEBUI_URL)
    try:
        resp = requests.post(
            f"{url}/internal/model/load",
            headers=_headers(),
            json={"model_name": name},
            timeout=300,
        )
        if resp.ok:
            return None
        return f"TGW load error {resp.status_code}: {resp.text[:200]}"
    except requests.RequestException as e:
        return str(e)


def list_models() -> list[str]:
    # 全モデル一覧を /internal/model/list から取得
    try:
        resp = requests.get(
            f"{TEXTGEN_WEBUI_URL}/internal/model/list", headers=_headers(), timeout=10
        )
        if resp.ok:
            names = resp.json().get("model_names", [])
            if names:
                return names
    except requests.RequestException:
        pass
    # フォールバック: 現在ロード中のモデルのみ
    try:
        resp = requests.get(
            f"{TEXTGEN_WEBUI_URL}/internal/model/info", headers=_headers(), timeout=10
        )
        if resp.ok:
            model_name = resp.json().get("model_name", "")
            if model_name and model_name != "None":
                return [model_name]
    except requests.RequestException:
        pass
    resp = requests.get(f"{TEXTGEN_WEBUI_URL}/models", headers=_headers(), timeout=10)
    resp.raise_for_status()
    return [m["id"] for m in resp.json().get("data", [])]
