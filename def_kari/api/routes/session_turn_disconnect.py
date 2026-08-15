"""通信途絶（切断）タイムアウト検知と、タイムアウト後の自動skipスケジューリング。

マルチプレイ設計書§3.7「切断（通信途絶）時のターン処理」の実装。`session_turn_engine.py`
の一部だったが、ターン進行本体（_run_ai_turns・next_turn等）への依存が
`_apply_skip`経由の1箇所（自動skip実行時にAIターン再開をトリガーする）のみのため
独立モジュール化した（TODO.md「session_turn_engine.pyのさらなる分割」参照）。
`_apply_skip`・`_get_current_speaker`はturn_engine側から見て「下流」にあたるため、
循環import回避のため呼び出し時に遅延import する（他のsessionモジュールで
確立済みのパターンを踏襲）。
"""

import asyncio

from def_kari.api.routes.session_state import _sessions

_DEFAULT_DISCONNECT_TIMEOUT_SEC = 60.0


def _disconnect_timeout_sec() -> float:
    from def_kari.settings import load_settings
    try:
        return max(1.0, float(load_settings().get("disconnect_timeout_sec", _DEFAULT_DISCONNECT_TIMEOUT_SEC)))
    except (TypeError, ValueError):
        return _DEFAULT_DISCONNECT_TIMEOUT_SEC


def _find_player_token(session: dict, char_id: str) -> str | None:
    """char_id を担当する人間プレイヤーの token を逆引きする。

    見つからない場合は None（オフラインセッション等、そもそもWS接続を介して
    操作されていないキャラ）。この場合「切断」の概念自体が存在しないため、
    呼び出し側は切断タイムアウトの対象外として扱う。
    """
    return next((t for t, c in session.get("players", {}).items() if c == char_id), None)


def _schedule_disconnect_skip(session_id: str, char_id: str) -> None:
    """切断中のキャラが設定秒数以内に再接続しなければ、自動的にターンをskipする。

    マルチプレイ設計書§3.7「切断（通信途絶）時のターン処理（決定・一部未実装）」の
    自動skip部分。現在のターン担当者が切断した場合（ws_endpointのfinallyブロック）と、
    まだターンが来ていないキャラが切断中のままターンが回ってきた場合
    （WAITING_FOR_HUMAN発行直後）の両方から呼ぶ。再接続・退室・expel・セッション
    終了時は必ず _cancel_disconnect_skip を呼ぶこと。
    """
    session = _sessions.get(session_id)
    if not session:
        return
    timers: dict[str, asyncio.Task] = session.setdefault("disconnect_skip_tasks", {})
    existing = timers.get(char_id)
    if existing and not existing.done():
        return  # 既にタイマー起動中
    timeout = _disconnect_timeout_sec()

    async def _do_skip() -> None:
        try:
            await asyncio.sleep(timeout)
        except asyncio.CancelledError:
            raise
        sess = _sessions.get(session_id)
        if not sess:
            return
        sess.setdefault("disconnect_skip_tasks", {}).pop(char_id, None)
        token = _find_player_token(sess, char_id)
        if token is not None and token in sess.get("ws_connections", {}):
            return  # 再接続済み
        from def_kari.api.routes.session_turn_engine import _apply_skip, _get_current_speaker
        if _get_current_speaker(sess) != char_id:
            return  # 別の経緯で既にターンが進んでいた
        _apply_skip(session_id, sess, char_id)

    timers[char_id] = asyncio.create_task(_do_skip())


def _cancel_disconnect_skip(session_id: str, char_id: str) -> None:
    session = _sessions.get(session_id)
    if not session:
        return
    timers: dict[str, asyncio.Task] = session.get("disconnect_skip_tasks", {})
    task = timers.pop(char_id, None)
    if task and not task.done():
        task.cancel()


def _maybe_schedule_disconnect_skip(session_id: str, session: dict, char_id: str) -> None:
    """WAITING_FOR_HUMANの対象キャラが既に切断中なら、切断タイムアウトタイマーを仕込む。

    3つのWAITING_FOR_HUMAN送出経路（_emit_waiting_for_human／_run_ai_turns内の
    waiting_for_human分岐／ロビー開始直後の初回通知）すべてから呼ぶ。
    """
    token = _find_player_token(session, char_id)
    if token is not None and token not in session.get("ws_connections", {}):
        _schedule_disconnect_skip(session_id, char_id)
