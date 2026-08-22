"""OpenAI Compatible Adapter — Base URL / API Key / Model / Extra Headers で任意のエンドポイントに接続する汎用アダプター"""

import requests


def make_chat_fn(base_url: str, api_key: str, default_model: str, extra_headers: dict | None = None):
    """compatible_backends.json の1エントリからchat関数とlist_models関数を生成する。"""

    def _headers() -> dict:
        h = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if extra_headers:
            h.update(extra_headers)
        return h

    def _chat(messages: list[dict], model: str, json_mode: bool = True, options: dict | None = None) -> str:
        body: dict = {"model": model or default_model, "messages": messages}
        if json_mode:
            # OpenAI標準のjson_mode相当。TGW(llama.cpp、grammar_stringでGBNF制約)とは
            # 異なり、compatibleは任意のOpenAI互換エンドポイントを対象にするため
            # response_formatが最も広くサポートされている汎用の制約手段
            # (vLLM/llama.cpp server/LM Studio等が対応。従来json_modeが受け取られる
            # だけで一切使われていなかったデッドパラメータだった、2026-08-22発覚)。
            body["response_format"] = {"type": "json_object"}
        if options and "num_predict" in options:
            body["max_completion_tokens"] = options["num_predict"]
        resp = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=_headers(),
            json=body,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def _list_models() -> list[str]:
        try:
            resp = requests.get(
                f"{base_url.rstrip('/')}/models",
                headers=_headers(),
                timeout=10,
            )
            resp.raise_for_status()
            models = sorted(m["id"] for m in resp.json().get("data", []))
            return models if models else ([default_model] if default_model else [])
        except Exception:
            return [default_model] if default_model else []

    return _chat, _list_models
