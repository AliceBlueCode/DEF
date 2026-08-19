"""E2Eテスト用の最小OpenAI互換モックLLMサーバー。

CIでは実際のLLM(APIキー・GPU)を用意できないため、`TEXTGEN_WEBUI_URL`環境変数を
このサーバーに向けることで、DEFの標準TGWバックエンド(`llm/adapters/tgw.py`)から
見て「TGWが既に起動している」状態を作る。DEFのJSON構造化出力スキーマ
(`llm/schema.py`のRESPONSE_SCHEMA)に沿った固定レスポンスを即座に返すだけで、
生成内容の質は問わない(e2eはUI/WS/認可の挙動を検証するためのもので、
生成テキストの中身自体は検証対象ではない)。

依存追加を避けるため標準ライブラリのみで実装。

使い方:
    python scripts/e2e_mock_llm.py [--port 5000]
"""

from __future__ import annotations

import argparse
import itertools
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_counter = itertools.count(1)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: D401 - 標準出力を静かに保つ
        pass

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            self._send_json(200, {"data": [{"id": "mock-model"}]})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send_json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)  # リクエスト内容は読み捨てる(検証不要)
        n = next(_counter)
        content = json.dumps(
            {
                "dialogue": f"モック応答その{n}です。",
                "emotion": "neutral",
                "image_prompt_en": "1girl, standing, neutral expression",
                "tags": [],
            },
            ensure_ascii=False,
        )
        self._send_json(
            200,
            {
                "choices": [{"message": {"role": "assistant", "content": content}}],
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
