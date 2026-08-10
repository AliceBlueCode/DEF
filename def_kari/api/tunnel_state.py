"""dual_run.py がcloudflaredを自動起動した場合に検出したQuick Tunnel URLを保持する。

_sessions/game_event_bus/vram_lock等と同じ「同一プロセス内のモジュール変数で共有する」
パターン。main.py側の /api/tunnel_url エンドポイントがここを読み、フロントエンドは
それを自動取得することでホストが手作業でURLを探す必要をなくす。
"""

url: str | None = None
