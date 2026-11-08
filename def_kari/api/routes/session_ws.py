"""Session WebSocket基盤: 未認証接続の同時数制限・安全な送信・イベント配信。

`session.py`分割の一部。`ws_endpoint`本体（ルートハンドラ）はターン進行系の
ヘルパー（`_get_current_speaker`等、`session_turn_engine.py`予定）に深く依存する
ため、循環importを避けるべくこのモジュールには含めない——turn_engine抽出後に
改めてここへ合流させる。このモジュールが持つのは、それ単体で完結する接続管理
インフラのみ。
"""

import asyncio
import json
import logging

from fastapi import WebSocket

from def_kari.api.routes import session_state as _session_state
from def_kari.api.routes.session_state import _sessions, _ws_send_locks
from def_kari.gm.events import game_event_bus as _game_event_bus

_log = logging.getLogger("def.session")


# 8.32対策: WS接続はaccept()直後にfirst-message authを最大5秒待つが、それまでの
# 「未認証で保持中」の接続数には上限が無く、_check_ws_rate（認証後、token単位）も
# ここには効かない。authを一切送らず大量に同時接続されると、TCP/asyncioタスク/
# メモリを際限なく消費できてしまう（2026-08-11、外部レビュー指摘）。IP単位・
# プロセス全体単位の同時「認証待ち」接続数に上限を設ける。
_ws_pending_auth_by_ip: dict[str, int] = {}
_ws_pending_auth_total = {"n": 0}
_WS_PENDING_AUTH_LIMIT_PER_IP = 20
_WS_PENDING_AUTH_LIMIT_TOTAL = 500


def _try_acquire_ws_pending_auth_slot(client_ip: str) -> bool:
    """True=枠を確保できた（呼び出し元は必ずrelease_ws_pending_auth_slotを対で呼ぶこと）。"""
    if (_ws_pending_auth_by_ip.get(client_ip, 0) >= _WS_PENDING_AUTH_LIMIT_PER_IP
            or _ws_pending_auth_total["n"] >= _WS_PENDING_AUTH_LIMIT_TOTAL):
        return False
    _ws_pending_auth_by_ip[client_ip] = _ws_pending_auth_by_ip.get(client_ip, 0) + 1
    _ws_pending_auth_total["n"] += 1
    return True


def _release_ws_pending_auth_slot(client_ip: str) -> None:
    if client_ip in _ws_pending_auth_by_ip:
        _ws_pending_auth_by_ip[client_ip] -= 1
        if _ws_pending_auth_by_ip[client_ip] <= 0:
            del _ws_pending_auth_by_ip[client_ip]
    if _ws_pending_auth_total["n"] > 0:
        _ws_pending_auth_total["n"] -= 1


async def _safe_send(session_id: str, token: str, ws: WebSocket, event: dict) -> None:
    """送信失敗時に ws_connections から除去する。create_task 経由で呼ぶ。

    同一接続への並列 send_json を Lock でシリアライズする。
    """
    lock = _ws_send_locks.setdefault(token, asyncio.Lock())
    async with lock:
        try:
            await ws.send_json(event)
        except Exception:
            sess = _sessions.get(session_id)
            if sess:
                sess["ws_connections"].pop(token, None)
            _ws_send_locks.pop(token, None)


def _session_tokens(sess: dict) -> set[str]:
    """このセッションの認証トークン（ホスト・参加者・GM）。イベントに混ざっていないかの照合用。"""
    tokens = set(sess.get("players", {}).keys())
    tokens.update(t for t in (sess.get("host_token"), sess.get("invited_gm_token")) if t)
    tokens.update(sess.get("token_to_participant", {}).keys())
    return {t for t in tokens if isinstance(t, str) and len(t) >= 20}


def _ws_broadcast_handler(session_id: str, event: dict) -> None:
    """game_event_bus の全イベントを接続中の全 WebSocket に配信する。

    asyncio コルーチン内から呼ばれた場合は loop.create_task、
    FastAPI の同期ハンドラ（スレッドプール）から呼ばれた場合は
    run_coroutine_threadsafe でメインループに転送する。
    """
    sess = _sessions.get(session_id)
    if not sess:
        return
    connections = list(sess.get("ws_connections", {}).items())
    if not connections:
        return

    # 守り1: このセッションの認証トークンを含むイベントは、誰にも送らない。
    # 以前は WS の接続・切断の通知が、ホストのJWTを participant_id の代わりに入れて全タブへ
    # 配っていた（2026-11-08、全体レビューで指摘）。発生源は直したが、同じ型の漏れが
    # どこかで再発しても外へ出ないよう、全イベントが通るここで止める。
    tokens = _session_tokens(sess)
    if tokens:
        try:
            text = json.dumps(event, ensure_ascii=False, default=str)
        except Exception:
            text = str(event)
        if any(t in text for t in tokens):
            _log.error("[ws] dropped event %s: it contained a session token", event.get("type"))
            return

    # 守り2: GM専用（gm_only）のイベントは、キーパー（ホスト・参加したGM）の接続にだけ送る。
    # 以前は全接続へ送っており、GET からは外した NPC の知識（8.27）が、WS 経由でプレイヤーと
    # Observer に届いていた（2026-11-08、全体レビューで指摘）。
    payload = event.get("payload")
    if isinstance(payload, dict) and payload.get("gm_only"):
        keepers = {sess.get("host_token"), sess.get("invited_gm_token")} - {None, ""}
        connections = [(t, ws) for t, ws in connections if t in keepers]
        if not connections:
            return

    async def _do_broadcast() -> None:
        for token, ws in connections:
            asyncio.create_task(_safe_send(session_id, token, ws, event))

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_do_broadcast())
    except RuntimeError:
        if _session_state._main_loop and _session_state._main_loop.is_running():
            asyncio.run_coroutine_threadsafe(_do_broadcast(), _session_state._main_loop)


_game_event_bus.subscribe("*", _ws_broadcast_handler)
