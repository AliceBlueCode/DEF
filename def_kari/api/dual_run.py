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
import os

import uvicorn

from def_kari.api.main import app, _SESSION_BODY_SIZE_LIMIT
from def_kari.api.public_main import public_app


async def _run(local_host: str, local_port: int, public_host: str, public_port: int) -> None:
    # 8.15対策: ws_max_sizeを指定しない場合uvicornのデフォルト(16MB)のままになり、
    # HTTP側のSessionBodySizeLimitMiddleware（512KB）と釣り合わない上限になる。
    # WS経由のメッセージにも同じ上限をかける。
    local_config = uvicorn.Config(app, host=local_host, port=local_port, log_level="info", ws_max_size=_SESSION_BODY_SIZE_LIMIT)
    public_config = uvicorn.Config(public_app, host=public_host, port=public_port, log_level="info", ws_max_size=_SESSION_BODY_SIZE_LIMIT)
    local_server = uvicorn.Server(local_config)
    public_server = uvicorn.Server(public_config)
    print(f"[dual_run] local (full API):   http://{local_host}:{local_port}")
    print(f"[dual_run] public (Tunnel用):  http://{public_host}:{public_port}")
    if os.environ.get("DEF_BEHIND_CLOUDFLARE_TUNNEL"):
        print("[dual_run] CF-Connecting-IP trust: ENABLED (DEF_BEHIND_CLOUDFLARE_TUNNEL=1)")
    else:
        print("[dual_run] CF-Connecting-IP trust: disabled (--no-trust-cloudflare-tunnel が指定されました)")
    await asyncio.gather(local_server.serve(), public_server.serve())


def main() -> None:
    parser = argparse.ArgumentParser(description="DEF(kari) デュアルポート起動")
    parser.add_argument("--local-host", default="127.0.0.1")
    parser.add_argument("--local-port", type=int, default=8511)
    parser.add_argument("--public-host", default="0.0.0.0")
    parser.add_argument("--public-port", type=int, default=8512)
    parser.add_argument(
        "--no-trust-cloudflare-tunnel",
        action="store_true",
        help=(
            "本スクリプトはCloudflare Tunnel経由での公開を前提とするため、"
            "デフォルトで DEF_BEHIND_CLOUDFLARE_TUNNEL=1 を設定し、"
            "session.py の招待コードレート制限が実クライアントIP（CF-Connecting-IP）を"
            "使えるようにする（cloudflaredを経由しない直接接続からは、TCPピアが"
            "ループバックにならないため、この信頼設定はそもそも悪用できない）。"
            "cloudflaredを使わずローカルネットワークのみで動かす等、Cloudflare Tunnel"
            "を前提としない運用の場合はこのフラグを指定して無効化すること。"
        ),
    )
    args = parser.parse_args()
    if not args.no_trust_cloudflare_tunnel:
        os.environ.setdefault("DEF_BEHIND_CLOUDFLARE_TUNNEL", "1")
    asyncio.run(_run(args.local_host, args.local_port, args.public_host, args.public_port))


if __name__ == "__main__":
    main()
