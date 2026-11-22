"""プラグインが卓の中で使う DEF の機能（`PluginApi.llm_chat`・`PluginApi.emit` の中身。基本設計書 11.4）。

- プラグインが使えるのは、自分のルールシステムの卓だけ（ほかの卓の LLM を呼んだり、イベントを出したりしない）。
- LLM への送信は、外部への送信の確かめ（`backend_guard`、呼び出しの役つき。B-021）と `vram_lock`（B-051）を
  必ず通る。プラグインにバックエンドを直接呼ぶ道は渡さない。
- イベントは DEF のイベントの発行を通す。配るときは、見せてよいものの境界（`event_view`）を必ず通る
  （`session_ws._ws_broadcast_handler`）。

GM をサーバー側から呼ぶ卓（`gm_driver`）は、この `llm_chat` で GM 役の LLM を呼ぶ（差し込み口 2）。
"""

import logging
import os

from def_kari.api.routes.session_state import _sessions

_log = logging.getLogger("def.trpg")

_VRAM_LOCK_TIMEOUT_SECONDS = float(os.environ.get("DEF_VRAM_LOCK_TIMEOUT", "60"))


class PluginCallError(RuntimeError):
    """プラグインの呼び出しを DEF が断った（卓が違う・役が無い・外部への送信を許さない・混んでいる・失敗した）。"""


def _own_session(rule_systems: frozenset, session_id: str) -> dict:
    session = _sessions.get(session_id)
    if not session:
        raise PluginCallError(f"session not found: {session_id!r}")
    if session.get("trpg_rule_system") not in rule_systems:
        raise PluginCallError("this session does not belong to the plugin's rule system")
    return session


def llm_chat(rule_systems: frozenset, session_id: str, messages: list, *, role: str,
             json_mode: bool = False, options: dict | None = None) -> str:
    """卓のバックエンドで LLM を1回呼び、返った文字列を返す。断ったとき・失敗したときは PluginCallError。"""
    from def_kari.llm import backend_guard as _backend_guard
    from def_kari.llm.backend import DEFAULT_LLM_BACKEND, LLM_BACKENDS
    session = _own_session(rule_systems, session_id)
    if role not in _backend_guard.ROLES:
        raise PluginCallError(f"unknown role: {role!r} (one of {sorted(_backend_guard.ROLES)})")
    if not isinstance(messages, list) or not all(
            isinstance(m, dict) and isinstance(m.get("role"), str) and isinstance(m.get("content"), str)
            for m in messages):
        raise PluginCallError("messages must be a list of {role, content}")
    backend_id = session.get("backend") or DEFAULT_LLM_BACKEND
    if backend_id not in LLM_BACKENDS:
        raise PluginCallError(f"unknown LLM backend: {backend_id!r}")
    from def_kari.api.routes.session_image import _resolve_model
    model = _resolve_model(backend_id)
    try:
        _backend_guard.check(session, "llm", backend_id, model, role=role)
    except _backend_guard.ExternalServiceRefused as e:
        raise PluginCallError(str(e)) from e
    from def_kari.resources.vram_lock import get_vram_lock
    lock = get_vram_lock()
    if not lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
        raise PluginCallError(f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s")
    try:
        text = LLM_BACKENDS[backend_id]["chat"](messages, model, json_mode=json_mode, options=dict(options or {}))
    except Exception as e:  # バックエンドの失敗は、プラグインが作り直しと既定の動きで扱う（S-359）
        _log.warning("[plugin llm] %s failed (%s): %s: %s", backend_id, role, type(e).__name__, e)
        raise PluginCallError(f"LLM call failed: {type(e).__name__}: {e}") from e
    finally:
        lock.release()
    _log.info("[plugin llm] session=%s role=%s backend=%s chars=%d", session_id[:8], role, backend_id, len(text or ""))
    return text or ""


def table_info(rule_systems: frozenset, session_id: str) -> dict:
    """自分のルールシステムの卓の、プラグインが知ってよい少しの値（写し）。卓が無い・違うなら PluginCallError。

    - `campaign_id`: 卓を作ったときの続きものの ID（persistence の口。手番の口 `handle_request` には卓の ID
      しか来ないため、どの続きものの卓かをここで引く）。
    - `paused`: ホストが止めた（`/ai_pause`）か、口の失敗で止めた（`ai_paused`）。手番を自分で回す卓は、
      これが True の間は進めない。`plugin_error` は、口の失敗で止めたときだけ True。
    """
    session = _own_session(rule_systems, session_id)
    return {
        "session_id": session_id,
        "campaign_id": session.get("campaign_id") or None,
        "rulebook_id": session.get("trpg_rulebook") or "",
        "rule_system": session.get("trpg_rule_system") or "",
        "plugin_version": session.get("trpg_plugin_version") or "",
        "paused": bool(session.get("ai_paused")),
        "plugin_error": bool(session.get("plugin_error")),
    }


def emit(rule_systems: frozenset, session_id: str, event_type: str, payload: dict) -> None:
    """卓にイベントを出す。配るときに見せてよいものの境界を通る。"""
    from def_kari.gm.events import game_event_bus
    _own_session(rule_systems, session_id)
    if not isinstance(event_type, str) or not event_type:
        raise PluginCallError("event_type must be a non-empty string")
    if not isinstance(payload, dict):
        raise PluginCallError("payload must be a JSON object")
    game_event_bus.emit(session_id, event_type, payload)
