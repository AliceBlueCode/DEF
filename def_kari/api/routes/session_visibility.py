"""見せてよいものの境界（visibility の口。差し込み口 5・6、要求仕様 S-801・S-803、基本設計書 11.4）。

`visibility` を持つルールシステムの卓では、外へ出る道は、相手ごとにこの口が一から作ったものだけを通す。
DEF の今の絞り方（`_PUBLIC_SESSION_KEYS`、`gm_only`）で後から削るのではない。口を持たない卓
（def_original など）は、今までどおりの処理のまま。

今この境界を通す道:
- WS のイベントの配信（`session_ws._ws_broadcast_handler`）と、接続のときの初期の配信（`ws_endpoint`）
- 状態の取得（`GET /api/session/{id}`、`session_gameplay.get_session`）
- イベントのログ（`GET /api/session/{id}/events`）
LLM の束・画像のプロンプトは prompt_context / image_prompt の口で、GM の呼び出しと一緒に足す。

相手（Audience）は JWT の中身から作る: `{"role": "host" | "gm" | "player" | "observer", "char_id": str}`。
口が失敗したら、閉じる側（配らない・返さない）に倒し、卓の進行を止める（B-027）。
"""

import copy

from def_kari.trpg import plugin_hooks

ROLES = ("host", "gm", "player", "observer")
SESSION_VIEW_EVENT = "SESSION_VIEW"


def audience_of(auth_payload: dict | None) -> dict:
    """JWT の中身から相手を作る。知らない役は、いちばん見せない observer にする。"""
    payload = auth_payload if isinstance(auth_payload, dict) else {}
    role = payload.get("role")
    if role not in ROLES:
        role = "observer"
    char_id = payload.get("char_id") if role == "player" else ""
    return {"role": role, "char_id": str(char_id or "")}


def uses_visibility(session: dict) -> bool:
    return plugin_hooks.has_capability(session, "visibility")


def _on_failure(session: dict, info: dict) -> None:
    from def_kari.api.routes.session_turn_engine import _pause_for_plugin_error
    _pause_for_plugin_error(session, info)


_CLOSED_SESSION_VIEW = {"plugin_error": True}


def _refuse(session: dict, method: str, why: str) -> None:
    """口が約束を破った（形が違う・トークンを混ぜた）。閉じる側に倒し、卓を止める（B-027）。"""
    import logging
    logging.getLogger("def.trpg").error("[visibility] %s of the table's rule system refused: %s", method, why)
    _on_failure(session, {"capability": "visibility", "method": method, "error": why})


def _has_session_token(session: dict, view: dict) -> bool:
    """口が作ったものに、この卓の認証トークンが混ざっていないか（守り1。WS・GET・/events の共通）。"""
    from def_kari.api.routes.session_ws import _contains_token, _session_tokens
    return _contains_token(view, _session_tokens(session))


def session_view(session: dict, audience: dict) -> dict:
    """この相手に返す状態。口が失敗した・dict でない・トークンを混ぜたときは、最小の知らせだけ。"""
    out = plugin_hooks.call(session, "visibility", "session_view", session, dict(audience), on_failure=_on_failure)
    if out == _CLOSED_SESSION_VIEW:
        return dict(_CLOSED_SESSION_VIEW)
    if not isinstance(out, dict):
        _refuse(session, "session_view", f"returned {type(out).__name__}, not a JSON object")
        return dict(_CLOSED_SESSION_VIEW)
    if _has_session_token(session, out):
        _refuse(session, "session_view", "the view contained a session token")
        return dict(_CLOSED_SESSION_VIEW)
    return out


def event_view(session: dict, event: dict, audience: dict) -> dict | None:
    """この相手に配るイベント。配らないなら None。形の正しくない返り値・トークンを混ぜたものも配らない。"""
    # 相手ごとに写しを渡す（口が書き換えても、ほかの相手と、ログに残る元のイベントに混ざらない）
    out = plugin_hooks.call(session, "visibility", "event_view", session, copy.deepcopy(event), dict(audience),
                            on_failure=_on_failure)
    if out is None:
        return None
    if not isinstance(out, dict) or not isinstance(out.get("type"), str):
        _refuse(session, "event_view", "returned something that is not an event ({type: str, ...})")
        return None
    if _has_session_token(session, out):
        _refuse(session, "event_view", "the event contained a session token")
        return None
    return out
