"""TgwAdapter: Text Generation WebUI(ローカル、OpenAI互換API)— デフォルト"""

import os
import re
import sys

import requests


def _debug_print(text: str) -> None:
    """診断用printのラッパー。Windowsのコンソール/リダイレクト先がcp932等の
    非UTF-8エンコーディングの場合、LLM応答に含まれる一部文字（em dash等）で
    UnicodeEncodeErrorが送出され、診断出力のはずがLLM呼び出し自体を失敗させて
    しまっていた（2026-08-22、TRPGキーパーのナレーション生成がこれで丸ごと
    失敗する不具合として発覚）。診断表示はベストエフォートとし、失敗しても
    本処理には影響させない。
    """
    try:
        print(text)
    except UnicodeEncodeError:
        try:
            enc = sys.stdout.encoding or "ascii"
            print(text.encode(enc, errors="replace").decode(enc, errors="replace"))
        except Exception:
            pass


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

# 汎用JSONオブジェクト制約のGBNF文法。TGWはOpenAIの`response_format`相当を持たず
# `grammar_string`(GBNF)でトークン生成そのものを制約する設計
# (`modules/api/typing.py`のGenerateBaseParams、公式ドキュメント`docs/12 - OpenAI API.md`
# には明記が無く、typing.pyのフィールド定義から確認)。中身のスキーマまでは制約せず
# 「有効なJSON文字列であること」だけを保証する最小文法。
_JSON_OBJECT_GRAMMAR = r"""
root   ::= object
value  ::= object | array | string | number | ("true" | "false" | "null")
object ::= "{" ws (string ":" ws value ("," ws string ":" ws value)*)? ws "}"
array  ::= "[" ws (value ("," ws value)*)? ws "]"
string ::= "\"" ([^"\\] | "\\" .)* "\""
number ::= "-"? [0-9]+ ("." [0-9]+)? ([eE] [+-]? [0-9]+)?
ws     ::= [ \t\n]*
"""


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
    if json_mode:
        body["grammar_string"] = _JSON_OBJECT_GRAMMAR
    if options:
        if "num_predict" in options:
            body["max_tokens"] = options["num_predict"]
        for _pkey in ("temperature", "top_p", "top_k", "repetition_penalty", "frequency_penalty", "presence_penalty"):
            if _pkey in options:
                body[_pkey] = options[_pkey]
        if "instruction_template" in options:
            body["instruction_template"] = options["instruction_template"]
    _debug_print(f"[TGW] request max_tokens={body.get('max_tokens', 'NOT SET')}")

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
    _debug_print(f"[TGW] content len={len(_content)}, reasoning len={len(_reasoning)}")
    if _content:
        _debug_print(f"[TGW] content (first 200): {_content[:200]}")
    if _reasoning and not _content:
        _debug_print(f"[TGW] reasoning (last 300): ...{_reasoning[-300:]}")
    if not _content and _reasoning:
        _content = _extract_from_reasoning(_reasoning)
    if _THINKING_PROCESS_RE.match(_content):
        _content = _extract_from_reasoning(_content)
    return _content


def chat_with_tools(
    messages: list[dict],
    model: str,
    tools: list[dict],
    options: dict | None = None,
) -> dict:
    """OpenAI互換のtool-calling(`docs/12 - OpenAI API.md`のTool/Function callingサンプル
    に準拠、DEF独自の実装)。モデルがツール呼び出しを選んだ場合は
    `{"tool_calls": [...], "content": ""}`、選ばなかった場合(通常の文章応答)は
    `{"tool_calls": None, "content": <文章>}`を返す。

    tool-calling自体はQwen/Mistral/GPT-OSS系などモデル依存の機能なので、対応
    モデルかどうかは呼び出し元が`models.registry.get_quirks()`の
    `tool_calling_capable`で判断すること(本関数はTGW側の対応可否のみを扱う)。
    """
    body: dict = {"model": model or MODEL, "messages": messages, "tools": tools}
    if options:
        if "num_predict" in options:
            body["max_tokens"] = options["num_predict"]
        for _pkey in ("temperature", "top_p", "top_k", "repetition_penalty"):
            if _pkey in options:
                body[_pkey] = options[_pkey]

    resp = requests.post(
        f"{TEXTGEN_WEBUI_URL}/chat/completions",
        headers=_headers(),
        json=body,
        timeout=600,
    )
    resp.raise_for_status()
    _choice = resp.json()["choices"][0]
    _msg = _choice.get("message", {})
    if _choice.get("finish_reason") == "tool_calls" and _msg.get("tool_calls"):
        return {"tool_calls": _msg["tool_calls"], "content": ""}
    return {"tool_calls": None, "content": _msg.get("content") or ""}


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


def get_current_model() -> str:
    """現在 TGW にロードされているモデル名を返す。取得失敗時は空文字。"""
    try:
        resp = requests.get(
            f"{TEXTGEN_WEBUI_URL}/internal/model/info", headers=_headers(), timeout=5
        )
        if resp.ok:
            name = resp.json().get("model_name", "")
            return name if name and name != "None" else ""
    except requests.RequestException:
        pass
    return ""


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
