"""DEF(kari) デュアルポート起動。

同一プロセス内で、ローカル向けフル機能アプリ（デフォルト127.0.0.1:8511）と、
Cloudflare Tunnel等での公開向け軽量アプリ（デフォルト0.0.0.0:8512、session機能＋
画像/音声の読み取り専用配信のみ）を同時に起動する。

シングルトン（game_event_bus / vram_lock / _sessions）は同一プロセス内のメモリで
共有されるため、2つのアプリ間でセッション状態の不整合は起きない
（別プロセスに分けると壊れる。マルチプレイ設計書§14「--workers は必ず1」と同じ理由）。

使い方:
    python -m def_kari.api.dual_run
    python -m def_kari.api.dual_run --local-port 8511 --public-port 8512 --public-host 0.0.0.0
"""

import argparse
import asyncio

import uvicorn

from def_kari.api.main import app
from def_kari.api.public_main import public_app


async def _run(local_host: str, local_port: int, public_host: str, public_port: int) -> None:
    local_config = uvicorn.Config(app, host=local_host, port=local_port, log_level="info")
    public_config = uvicorn.Config(public_app, host=public_host, port=public_port, log_level="info")
    local_server = uvicorn.Server(local_config)
    public_server = uvicorn.Server(public_config)
    print(f"[dual_run] local (full API):   http://{local_host}:{local_port}")
    print(f"[dual_run] public (Tunnel用):  http://{public_host}:{public_port}")
    await asyncio.gather(local_server.serve(), public_server.serve())


def main() -> None:
    parser = argparse.ArgumentParser(description="DEF(kari) デュアルポート起動")
    parser.add_argument("--local-host", default="127.0.0.1")
    parser.add_argument("--local-port", type=int, default=8511)
    parser.add_argument("--public-host", default="0.0.0.0")
    parser.add_argument("--public-port", type=int, default=8512)
    args = parser.parse_args()
    asyncio.run(_run(args.local_host, args.local_port, args.public_host, args.public_port))


if __name__ == "__main__":
    main()
