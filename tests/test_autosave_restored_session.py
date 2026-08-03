"""autosaveから復元された直後のセッション（ws_connections等の非シリアライズキーを
持たない状態）に対して各種処理を呼んでもKeyErrorにならないことのテスト。

_session_for_json() は "ws_connections"/"ai_task"/"idle_shutdown_task"/"ws_rate"/
"gen_rate"/"gen_inflight" をシリアライズ時に除外するため、復元直後のセッション
辞書はこれらのキーを持たない。session[...] のように .get() を使わず直接アクセス
している箇所があれば、復元直後のセッションに対する操作でKeyErrorになる
（TODO.md「session autosaveからの復元処理」の未検証項目）。
"""

import pytest


def _restored_session(session_id: str) -> dict:
    """_session_for_json() でシリアライズされた状態を模した、非シリアライズキーを
    一切持たないセッション辞書（実際の復元直後の状態）。"""
    return {
        "id": session_id,
        "initiative": ["char_a"],
        "players": {},
        "token_to_participant": {},
        "joined_participants": [],
        "invite_codes": {},
        "counters": {},
        "history": [],
        "turn": 0,
        "round": 1,
    }


def test_revoke_token_on_restored_session_does_not_raise():
    """ws_connectionsキーを持たない復元直後のセッションに対してrevoke_tokenを
    呼んでもKeyErrorにならないこと。"""
    from def_kari.api.routes.session import revoke_token, issue_player_jwt, _sessions, _revoked_jtis

    sid = "_restored_revoke_test"
    token = issue_player_jwt(sid, "player", "char_a")
    _sessions[sid] = _restored_session(sid)
    try:
        revoke_token(token)  # 例外を投げないこと自体がテスト
        from jose import jwt as _jwt
        from def_kari.settings import get_jwt_secret
        payload = _jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
        assert payload["jti"] in _revoked_jtis
    finally:
        _sessions.pop(sid, None)


@pytest.mark.asyncio
async def test_end_session_on_restored_session_does_not_raise():
    """ws_connections/ai_task/idle_shutdown_taskを持たない復元直後のセッションに
    対して _end_session を呼んでもKeyErrorにならないこと。"""
    from def_kari.api.routes.session import _end_session, _sessions

    sid = "_restored_end_test"
    _sessions[sid] = _restored_session(sid)
    try:
        await _end_session(sid)  # 例外を投げないこと自体がテスト
        assert sid not in _sessions
    finally:
        _sessions.pop(sid, None)
