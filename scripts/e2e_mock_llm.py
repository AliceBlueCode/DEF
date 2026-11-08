"""E2Eテスト用の最小OpenAI互換モックLLMサーバー（台本つき）。

CIでは実際のLLM(APIキー・GPU)を用意できないため、`TEXTGEN_WEBUI_URL`環境変数を
このサーバーに向けることで、DEFの標準TGWバックエンド(`llm/adapters/tgw.py`)から
見て「TGWが既に起動している」状態を作る。

既定の動き: DEFのJSON構造化出力スキーマ(`llm/schema.py`のRESPONSE_SCHEMA)に沿った
固定レスポンスを即座に返す（生成内容の質は問わない）。

台本（2026-11-08、v4.2.1 の D）: 実機確認の手順書の項目（生成の失敗、AIの投票の発議、
弁明の途中での取り消し等）を自動で再現するため、テストから「この条件の呼び出しには、
この返事を返す」という規則を差し込めるようにした。規則が1つも当たらなければ既定の動き。

制御用のエンドポイント（`/_` で始まる。DEFからは呼ばれない）:
    POST /_script   {"rules": [規則, ...]}  規則を末尾に足す
    POST /_reset    規則と呼び出しの記録を消す
    GET  /_calls    呼び出しの記録 [{"n", "matched", "speaker", "last_user", "system"(各先頭300文字), "json_mode"}]
                    speaker は system の「あなたの役割: 名前」の名前（全文から取る。無ければ ''）

規則:
    {
      "name": "任意の名前（記録に残る）",
      "last_user_contains": [...],     # 最後の user メッセージ（いまの指示）に、すべて含まれる
      "last_user_not_contains": [...], # 最後の user メッセージに、どれも含まれない
      "system_contains": [...],        # system メッセージ（人格・「あなたの役割: 名前」）に、すべて含まれる
      "json_mode": true,               # JSONを求める呼び出し（grammar_string あり）だけ／false で求めないものだけ
      "contains": [...],               # 全メッセージをつないだ文字列に、すべて含まれる
      "not_contains": [...],           # 全メッセージに、どれも含まれない
      "times": 1,                      # 何回まで当たるか（省略で無制限）
      "delay_ms": 0,                   # 返すまでの待ち時間
      # 返す内容は次のどれか1つ
      "json": {...},                   # このJSONを本文として返す
      "content": "文字列",             # この文字列をそのまま本文として返す
      "status": 500                    # このHTTPステータスでエラーを返す
    }
規則は先に足したものから順に調べ、最初に当たったものを使う。

照合の注意: 会話の履歴には過去の発言（「[投票提案]…」等）がそのまま入るため、「全メッセージ」で
照合すると誤って当たる。いまの呼び出しの種類は最後の user メッセージで、話しているキャラは
system メッセージの「あなたの役割: 名前」で見分ける（`frontend/e2e/helpers.js` の mockRules）。

依存追加を避けるため標準ライブラリのみで実装。

使い方:
    python scripts/e2e_mock_llm.py [--port 5000]
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_counter = itertools.count(1)
_lock = threading.Lock()
_rules: list[dict] = []
_calls: list[dict] = []
_CALL_LOG_MAX = 2000


def _request_text(req: dict) -> str:
    """リクエストの全メッセージ（と response_format）を1つの文字列にする。規則の照合用。"""
    parts: list[str] = []
    for m in req.get("messages") or []:
        if isinstance(m, dict):
            parts.append(_message_text(m))
    if req.get("prompt"):
        parts.append(str(req["prompt"]))
    if req.get("response_format"):
        parts.append(json.dumps(req["response_format"], ensure_ascii=False))
    return "\n".join(parts)


def _message_text(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
    return ""


def _views(req: dict) -> dict:
    """照合に使う部分ごとの文字列。"""
    msgs = [m for m in req.get("messages") or [] if isinstance(m, dict)]
    users = [m for m in msgs if m.get("role") == "user"]
    return {
        "all": _request_text(req),
        "last_user": _message_text(users[-1]) if users else "",
        "system": "\n".join(_message_text(m) for m in msgs if m.get("role") == "system"),
        "json_mode": bool(req.get("grammar_string") or req.get("response_format")),
    }


def _matches(rule: dict, v: dict) -> bool:
    if "json_mode" in rule and bool(rule["json_mode"]) != v["json_mode"]:
        return False
    checks = (
        ("contains", "all", True), ("not_contains", "all", False),
        ("last_user_contains", "last_user", True), ("last_user_not_contains", "last_user", False),
        ("system_contains", "system", True),
    )
    for key, view, must in checks:
        needles = rule.get(key) or []
        if must and not all(n in v[view] for n in needles):
            return False
        if not must and any(n in v[view] for n in needles):
            return False
    return True


def _pick_rule(v: dict) -> dict | None:
    with _lock:
        for rule in _rules:
            if rule.get("times") is not None and rule.get("_used", 0) >= rule["times"]:
                continue
            if not _matches(rule, v):
                continue
            rule["_used"] = rule.get("_used", 0) + 1
            return dict(rule)
    return None


def _default_content(n: int) -> str:
    return json.dumps(
        {
            "dialogue": f"モック応答その{n}です。",
            "emotion": "neutral",
            "image_prompt_en": "1girl, standing, neutral expression",
            "tags": [],
        },
        ensure_ascii=False,
    )


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: D401 - 標準出力を静かに保つ
        pass

    def _send_json(self, status: int, payload) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def do_GET(self) -> None:
        path = self.path.rstrip("/")
        if path.endswith("/models"):
            self._send_json(200, {"data": [{"id": "mock-model"}]})
            return
        if path == "/_calls":
            with _lock:
                self._send_json(200, list(_calls))
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = self.path.rstrip("/")
        if path == "/_script":
            rules = self._read_json().get("rules") or []
            with _lock:
                _rules.extend(r for r in rules if isinstance(r, dict))
                count = len(_rules)
            self._send_json(200, {"rules": count})
            return
        if path == "/_reset":
            with _lock:
                _rules.clear()
                _calls.clear()
            self._send_json(200, {"ok": True})
            return
        if not path.endswith("/chat/completions"):
            self._send_json(404, {"error": "not found"})
            return

        req = self._read_json()
        v = _views(req)
        n = next(_counter)
        rule = _pick_rule(v)
        with _lock:
            role = re.search(r"あなたの役割: ([^\n]+)", v["system"])  # 名前に空白があっても行末まで
            _calls.append({
                "n": n, "matched": (rule or {}).get("name", ""),
                "speaker": role.group(1).strip() if role else "",
                "last_user": v["last_user"][:300], "system": v["system"][:300], "json_mode": v["json_mode"],
            })
            del _calls[:-_CALL_LOG_MAX]

        if rule and rule.get("delay_ms"):
            time.sleep(rule["delay_ms"] / 1000)
        if rule and rule.get("status"):
            self._send_json(int(rule["status"]), {"error": {"message": f"mock error ({rule.get('name', '')})"}})
            return
        if rule and "json" in rule:
            content = json.dumps(rule["json"], ensure_ascii=False)
        elif rule and "content" in rule:
            content = str(rule["content"])
        else:
            content = _default_content(n)
        self._send_json(
            200,
            {
                "choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                "model": "mock-model",
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    print(f"[e2e_mock_llm] listening on http://127.0.0.1:{args.port}/v1")
    server.serve_forever()


if __name__ == "__main__":
    main()
