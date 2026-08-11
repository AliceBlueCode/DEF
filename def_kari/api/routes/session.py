"""Session API routes."""

import asyncio
import datetime
import hashlib
import json
import logging
import os
import random
import re
import secrets
import shutil
import threading
import time
import uuid as _uuid_mod
from collections import OrderedDict, deque
from pathlib import Path

_log = logging.getLogger("def.session")


def _resolve_model(backend_id: str, req_model: str = "") -> str:
    """バックエンドに対応するモデル名を解決する。

    優先順位: リクエスト指定 > 設定ファイル(llm_ext_model_{backend_id}) > バックエンドデフォルト
    """
    if req_model:
        return req_model
    try:
        from def_kari.settings import load_settings
        per_backend = load_settings().get(f"llm_ext_model_{backend_id}", "")
        if per_backend:
            return per_backend
    except Exception:
        pass
    from def_kari.llm.backend import LLM_BACKENDS
    return LLM_BACKENDS.get(backend_id, {}).get("default_model", "")

from fastapi import APIRouter, Body, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from def_kari.characters import load_profiles, get_character
from def_kari.history.store import save_session_mode, list_session_mode_files
from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.llm.client import generate_structured_reply  # vote/deliberate で直接使用
from def_kari.gm.player_agent import _player_agent
from def_kari.image_prompt.emotion_tags import apply_emotion_tags
from def_kari.settings import load_settings
from def_kari.safety.filters import character_rating_exceeds_invite
from def_kari.t2i.backend import generate_image as _generate_t2i_image
from def_kari.gm.context_builder import (
    load_trpg_rulebook as _load_trpg_rulebook,
    load_trpg_scenario as _load_trpg_scenario,
    build_trpg_context as _build_trpg_context,
    build_for_player as _build_for_player,
    build_session_context as _build_session_context,
    build_turn_instruction as _build_turn_instruction,
)
from def_kari.gm.gm_agent import _gm_agent
from def_kari.safety.character_audit import audit_character_json
from def_kari.safety.audit_log import (
    record_generation_event,
    record_rate_limit_violation,
    reset_violations as _reset_audit_violations,
)
from def_kari.safety.content_filter import contains_blocked_content

router = APIRouter()

# ローカル専用エンドポイント（デバッグ・セーブ/ロード）専用のルーター。
# `router`はpublic_main.pyに丸ごとマウントされるため、フル機能アプリ（main.py）専用の
# 操作をここに含めると外部公開されてしまう（8.8「session.router丸ごとマウントに起因する
# 無認証エンドポイントの公開漏れ」参照）。main.pyはrouterとlocal_routerの両方をマウントし、
# public_main.pyはrouterのみマウントする（3章「安全な部分だけ別ルーターに分離する」原則の
# session.py自身への適用）。
local_router = APIRouter()

_BASE_DATA = Path(__file__).parent.parent.parent.parent / "data"
_SESSION_PROMPTS_PATH = _BASE_DATA / "session_prompts.json"
_session_prompts_cache: dict = {}

def _load_session_prompts() -> dict:
    global _session_prompts_cache
    if _session_prompts_cache:
        return _session_prompts_cache
    try:
        with open(_SESSION_PROMPTS_PATH, encoding="utf-8") as f:
            _session_prompts_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return _session_prompts_cache

def _sp(key: str, lang: str) -> str:
    """session_prompts.json から言語別テキストを取得。"""
    entry = _load_session_prompts().get(key, {})
    return entry.get(lang) or entry.get("ja") or ""


_LANG_LABELS = {
    "ja": "日本語", "en": "English", "zh": "中文",
    "ko": "한국어", "es": "Español", "fr": "Français", "de": "Deutsch",
}




_MAX_SESSIONS = int(os.environ.get("DEF_MAX_SESSIONS", "1000"))
_sessions: OrderedDict[str, dict] = OrderedDict()
_last_session_debug: dict = {}

# シリアライズ不可能なフィールド（WebSocket/asyncio.Task/deque 等）
_NON_SERIALIZABLE_KEYS = frozenset({
    "ws_connections", "ai_task", "idle_shutdown_task", "ws_rate",
    "gen_rate", "gen_inflight",  # S-6: dict[str, deque] / set はJSON化できない
    "disconnect_skip_tasks",  # dict[str, asyncio.Task] はJSON化できない
})


def _session_for_json(session: dict) -> dict:
    """autosave用: シリアライズ不可能なフィールドを除いたコピーを返す。復元に必要な
    情報（host_token等）はすべて残す。外部レスポンスには使わないこと
    （`_session_for_public_json`参照）。"""
    return {k: v for k, v in session.items() if k not in _NON_SERIALIZABLE_KEYS}


# GET /{session_id}（無認証）で外部に公開してはいけない機密フィールド。
# _NON_SERIALIZABLE_KEYS（JSON化できるか）とは別軸の「公開してよいか」の判定。
# 2026-08-04の攻撃者視点監査で、host_token/invited_gm_token/players（{token: char_id}、
# キーが全参加者の認証トークン）/invite_codes/token_to_participant（{token: participant_id}）
# が無認証GETで丸ごと露出していたことが発覚した（8.1参照）。
_PUBLIC_EXCLUDED_KEYS = frozenset({
    "host_token", "invited_gm_token", "players", "invite_codes", "token_to_participant",
})


def _session_for_public_json(session: dict) -> dict:
    """GETレスポンス専用: `_session_for_json`に加えて認証トークン・招待コード等の
    機密フィールドも除外したコピーを返す。"""
    return {k: v for k, v in _session_for_json(session).items() if k not in _PUBLIC_EXCLUDED_KEYS}


def _handle_flag_updated(session_id: str, event: dict) -> None:
    """FLAG_UPDATED イベントを受けて player_knowledge を更新する。"""
    sess = _sessions.get(session_id)
    if not sess:
        return
    payload = event.get("payload", {})
    if payload.get("gm_only"):
        return
    key = payload.get("key", "")
    value = payload.get("value")
    if not key:
        return
    entry = f"フラグ「{key}」が更新された（値: {value}）"
    pk = sess.setdefault("player_knowledge", {})
    for char_id in sess.get("initiative", []):
        char_list = pk.setdefault(char_id, [])
        if entry not in char_list:
            char_list.append(entry)


from def_kari.gm.events import game_event_bus as _game_event_bus, FLAG_UPDATED as _FLAG_UPDATED
_game_event_bus.subscribe(_FLAG_UPDATED, _handle_flag_updated)


# ── WebSocket / マルチプレイ ──────────────────────────────────────────

# 接続ごとの送信ロック: 同一WSへの並列 send_json を防ぐ
_ws_send_locks: dict[str, asyncio.Lock] = {}

# asyncio メインループ（スレッドプールから broadcast するために保存）
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """lifespan 起動時に main.py から呼ぶ。スレッドセーフな broadcast に使用。"""
    global _main_loop
    _main_loop = loop


def _check_ws_rate(session_id: str, token: str, limit: int = 60, window: int = 60) -> bool:
    """True=許可、False=制限超過（60メッセージ/分）。

    rateデータはセッションデータ内に保持する（セッション終了で自動消滅）。
    """
    sess = _sessions.get(session_id)
    if not sess:
        return True
    ws_rate: dict[str, deque] = sess.setdefault("ws_rate", {})
    now = time.monotonic()
    q = ws_rate.setdefault(token, deque())
    q.append(now)
    while q and q[0] < now - window:
        q.popleft()
    return len(q) <= limit


def _check_generation_rate(session_id: str, key: str, limit: int = 6, window: int = 60) -> bool:
    """True=許可、False=制限超過。

    generate-image 等、実コスト（課金API呼び出し / GPU時間）を伴う生成系
    アクションに対するレート制限。`_check_ws_rate`（発言用、60回/分）とは
    独立したバケットで管理する。デフォルトは 1参加者あたり6回/分。
    """
    sess = _sessions.get(session_id)
    if not sess:
        return True
    gen_rate: dict[str, deque] = sess.setdefault("gen_rate", {})
    now = time.monotonic()
    q = gen_rate.setdefault(key, deque())
    q.append(now)
    while q and q[0] < now - window:
        q.popleft()
    return len(q) <= limit


def _check_daily_generation_limit(session_id: str) -> bool:
    """True=許可、False=本日のセッション単位上限に到達（9.2 Layer 2「コスト上限
    キルスイッチ」）。

    `_check_generation_rate`は1分単位のスライディングウィンドウで連打を防ぐが、
    「1日あたりの合計コスト」には上限が無かった。ホストが設定タブで
    `session_daily_generation_limit`（デフォルト0=無制限）を設定すると、
    そのセッションの生成系エンドポイント呼び出し回数が1日の上限に達した時点で
    以降を拒否するキルスイッチとして機能する。日付はサーバーのローカル日付
    （`date.today()`）で判定し、日付が変わればカウンターを自動リセットする。
    """
    from def_kari.settings import load_settings
    limit = int(load_settings().get("session_daily_generation_limit", 0) or 0)
    if limit <= 0:
        return True
    sess = _sessions.get(session_id)
    if not sess:
        return True
    today = datetime.date.today().isoformat()
    if sess.get("daily_gen_date") != today:
        sess["daily_gen_date"] = today
        sess["daily_gen_count"] = 0
    if sess.get("daily_gen_count", 0) >= limit:
        return False
    sess["daily_gen_count"] = sess.get("daily_gen_count", 0) + 1
    return True


def _check_circuit_breaker(session_id: str) -> bool:
    """True=生成許可、False=サーキットブレーカー作動中（9.3 Layer 3）。

    短時間に大量のレート制限違反（`audit_log.record_rate_limit_violation`が閾値超過を
    検知した場合）が発生したセッションは、ホストが明示的に解除するまで生成系エンドポイント
    全体を停止する。`_check_generation_rate`等の個別チェックより先に呼ぶことで、
    ブレーカー作動後は無駄にレート制限バケットへ記録すら行わせない。
    """
    sess = _sessions.get(session_id)
    if not sess:
        return True
    return not sess.get("circuit_broken", False)


def _record_violation_and_maybe_trip(event: str, session_id: str, ip: str, key: str) -> None:
    """レート制限違反を監査ログに記録し、閾値超過ならそのセッションのブレーカーを落とす。"""
    if record_rate_limit_violation(event, session_id, ip, key):
        sess = _sessions.get(session_id)
        if sess:
            sess["circuit_broken"] = True


def _try_acquire_generation_lock(session_id: str, key: str) -> bool:
    """同一参加者からの生成リクエストの多重実行（in-flight）を防ぐ。

    レート制限（回数/時間）だけでは、生成処理自体に数秒〜数十秒かかる場合、
    枠内で連続投入されると同時実行数が積み上がりGPU/APIを圧迫し得る。
    生成中は次のリクエストを受け付けない排他制御を別途行う。
    呼び出し元は必ず `finally` で `_release_generation_lock` を呼ぶこと。
    """
    sess = _sessions.get(session_id)
    if sess is None:
        return False
    inflight: set = sess.setdefault("gen_inflight", set())
    if key in inflight:
        return False
    inflight.add(key)
    return True


def _release_generation_lock(session_id: str, key: str) -> None:
    sess = _sessions.get(session_id)
    if sess:
        sess.get("gen_inflight", set()).discard(key)


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

    async def _do_broadcast() -> None:
        for token, ws in connections:
            asyncio.create_task(_safe_send(session_id, token, ws, event))

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_do_broadcast())
    except RuntimeError:
        if _main_loop and _main_loop.is_running():
            asyncio.run_coroutine_threadsafe(_do_broadcast(), _main_loop)


_game_event_bus.subscribe("*", _ws_broadcast_handler)


# ── JWT 認証 ─────────────────────────────────────────────────────────

from jose import jwt as _jwt, JWTError as _JWTError
import datetime as _dt

# jti(JWTのユニークID) → 失効理由の有効期限(exp、UTC unixタイムスタンプ)。
# 値はトークン自身のexpをそのまま流用する: exp到来後はverify_jwtのjose.decode自体が
# 期限切れとして拒否するため、それより後までブラックリストに残しておく意味がない。
_revoked_jtis: dict[str, float] = {}
_revoked_jtis_last_cleanup = {"t": 0.0}
_REVOKED_JTIS_CLEANUP_INTERVAL = 600.0  # 10分

# 招待コード生成
_INVITE_CHARS_ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # O・I除く
_INVITE_CHARS_NUM   = "23456789"                   # 0・1除く
_INVITE_RATINGS     = ["SFW", "R15", "R18", "UNL"]

# invite_code → session_id マッピング
_invite_registry: dict[str, str] = {}
# invite失敗カウント (ip → [timestamp, ...])
_invite_fail_rate: dict[str, deque] = {}
_invite_locked_until: dict[str, float] = {}


def _get_jwt_secret() -> str:
    from def_kari.settings import get_jwt_secret
    return get_jwt_secret()


def issue_player_jwt(session_id: str, role: str, char_id: str = "") -> str:
    jti = str(_uuid_mod.uuid4())
    payload = {
        "session_id": session_id,
        "role": role,
        "jti": jti,
        "exp": _dt.datetime.utcnow() + _dt.timedelta(hours=24),
    }
    if char_id:
        payload["char_id"] = char_id
    return _jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")


def _cleanup_expired_revoked_jtis() -> None:
    """期限切れのブラックリストエントリを間引く（_cleanup_invite_rate_stateと同じパターン）。

    以前は_end_session/_evict_oldest_session時にのみ「そのセッションでまだ生きている
    jti」をブラックリストから除外しようとしていたが、revoke_token()の時点で既にトークンは
    session["players"]からpopされた後だったため対象が常に空集合になり、実質的に
    revoked_jtisが一度追加したjtiを二度と削除しないno-opになっていた（join/leaveを
    繰り返すたびに無制限に増加するバグ）。expのタイムスタンプで判定する方式に変更。
    """
    now = time.time()
    if time.monotonic() - _revoked_jtis_last_cleanup["t"] < _REVOKED_JTIS_CLEANUP_INTERVAL:
        return
    _revoked_jtis_last_cleanup["t"] = time.monotonic()
    for jti in [j for j, exp in _revoked_jtis.items() if exp <= now]:
        del _revoked_jtis[jti]


def verify_jwt(token: str) -> dict:
    """JWTを検証して payloadを返す。失敗時は JWTError を raise する。"""
    _cleanup_expired_revoked_jtis()
    payload = _jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
    if payload.get("jti") in _revoked_jtis:
        raise _JWTError("Token revoked")
    return payload


def revoke_token(token: str) -> None:
    """退室・強制切断時に jti をブラックリストに追加する。"""
    try:
        payload = _jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
        exp = payload.get("exp")
        _revoked_jtis[payload["jti"]] = float(exp) if exp is not None else time.time() + 86400.0
        sess = _sessions.get(payload.get("session_id", ""))
        if sess:
            # autosaveから復元された直後のセッションは ws_connections キーを
            # 持たない（_session_for_json でシリアライズ時に除外されるため）。
            # 直接アクセスだとKeyErrorになるため .get() を使う。
            sess.get("ws_connections", {}).pop(token, None)
    except Exception:
        pass


def _is_human_char(session: dict, char_id: str, profiles: dict | None = None) -> bool:
    """セッション内で人間扱いかどうかを返す。

    human_char_ids（Phase 3以降）に含まれていれば人間。
    未設定の場合は profiles の player_type にフォールバック。
    """
    if char_id in session.get("human_char_ids", []):
        return True
    # guest_chars（持ち込みキャラ）も人間扱い
    if char_id in session.get("guest_chars", {}):
        return True
    if profiles is None:
        profiles = load_profiles()
    char = get_character(char_id, profiles)
    return bool(char and char.get("player_type") == "human")


def _generate_invite_code(rating: str) -> str:
    alpha = "".join(secrets.choice(_INVITE_CHARS_ALPHA) for _ in range(3))
    num   = "".join(secrets.choice(_INVITE_CHARS_NUM)   for _ in range(3))
    return f"{rating}-{alpha}-{num}"


# invite レート制限状態の最終クリーンアップ時刻（無制限のキー増加を防ぐ）
_invite_rate_last_cleanup: dict[str, float] = {"t": 0.0}
_INVITE_RATE_CLEANUP_INTERVAL = 300.0  # 5分ごと


def _cleanup_invite_rate_state() -> None:
    """失効した招待レート制限エントリを間引く。

    `_invite_fail_rate` / `_invite_locked_until` はキーを明示的に削除する
    処理がなかったため、長時間稼働・多数の異なるIPからのアクセスで
    辞書が際限なく増加し得た。呼び出し頻度の低いこの関数を
    `_check_invite_rate` の呼び出し経路に軽量にフックし、一定間隔でのみ
    実際の掃除を行う。
    """
    now = time.monotonic()
    if now - _invite_rate_last_cleanup["t"] < _INVITE_RATE_CLEANUP_INTERVAL:
        return
    _invite_rate_last_cleanup["t"] = now
    for ip in list(_invite_fail_rate.keys()):
        recent = [t for t in _invite_fail_rate[ip] if t > now - 60]
        if recent:
            _invite_fail_rate[ip] = deque(recent)
        else:
            del _invite_fail_rate[ip]
    for ip in list(_invite_locked_until.keys()):
        if _invite_locked_until[ip] <= now:
            del _invite_locked_until[ip]


def _check_invite_rate(client_ip: str) -> bool:
    """True=許可、False=ロック中 or 制限超過（10回/分、10回失敗で1時間ロック）"""
    _cleanup_invite_rate_state()
    now = time.monotonic()
    if _invite_locked_until.get(client_ip, 0) > now:
        return False
    q = _invite_fail_rate.setdefault(client_ip, deque())
    recent = [t for t in q if t > now - 60]
    _invite_fail_rate[client_ip] = deque(recent)
    if len(recent) >= 10:
        _invite_locked_until[client_ip] = now + 3600
        return False
    return True


def _record_invite_fail(client_ip: str) -> None:
    _invite_fail_rate.setdefault(client_ip, deque()).append(time.monotonic())


# セッション作成（/start）は無認証のため、IPベースの単純なスライディングウィンドウで
# レート制限する（8.5対策）。招待コードの「失敗」概念が無く_check_invite_rateとは
# 性質が違うため別バケットにする。友達数人とのオンラインセッション立ち上げでは
# 短時間に何度も叩くことは想定されないため、1分あたり20回で十分な余裕を持たせた。
_session_create_rate: dict[str, deque] = {}
_SESSION_CREATE_LIMIT = 20
_SESSION_CREATE_WINDOW = 60.0
_session_create_rate_last_cleanup: dict[str, float] = {"t": 0.0}
_SESSION_CREATE_RATE_CLEANUP_INTERVAL = 300.0


def _cleanup_session_create_rate_state() -> None:
    """失効したセッション作成レート制限エントリを間引く（_cleanup_invite_rate_stateと同じパターン）。"""
    now = time.monotonic()
    if now - _session_create_rate_last_cleanup["t"] < _SESSION_CREATE_RATE_CLEANUP_INTERVAL:
        return
    _session_create_rate_last_cleanup["t"] = now
    for ip in list(_session_create_rate.keys()):
        recent = [t for t in _session_create_rate[ip] if t > now - _SESSION_CREATE_WINDOW]
        if recent:
            _session_create_rate[ip] = deque(recent)
        else:
            del _session_create_rate[ip]


def _check_session_create_rate(client_ip: str) -> bool:
    """True=許可、False=制限超過（1分あたり20回）。"""
    _cleanup_session_create_rate_state()
    now = time.monotonic()
    q = _session_create_rate.setdefault(client_ip, deque())
    q.append(now)
    while q and q[0] < now - _SESSION_CREATE_WINDOW:
        q.popleft()
    return len(q) <= _SESSION_CREATE_LIMIT


def _evict_oldest_session() -> None:
    """`_MAX_SESSIONS`到達時、最も古いセッションを後片付けしながら追い出す（8.5対策）。

    以前は`_sessions.popitem(last=False)`で無条件に破棄しており、WS接続・
    バックグラウンドタスク（ai_task/idle_shutdown_task/disconnect_skip_tasks）・
    招待コードのグローバルレジストリが後片付けされないまま残っていた
    （進行中の正当なセッションが巻き込まれた場合、参加者は突然「セッションが
    見つかりません」になり、孤立したタスク・WS接続が残留する）。
    `_end_session`と同じ後片付けを行うが、本関数は同期コンテキスト
    （/start・/loadのハンドラ）から呼ばれるため、タスクキャンセル等
    同期的に完結する処理はここで即座に行い、WSクローズ（非同期処理）だけは
    `_ws_broadcast_handler`と同じパターンでバックグラウンドに委ねる。
    """
    session_id, session = _sessions.popitem(last=False)
    for key in ("ai_task", "idle_shutdown_task"):
        if (t := session.get(key)) and not t.done():
            t.cancel()
    for t in session.get("disconnect_skip_tasks", {}).values():
        if not t.done():
            t.cancel()
    for token in list(session.get("players", {}).keys()):
        _ws_send_locks.pop(token, None)
    for code in list(session.get("invite_codes", {}).keys()):
        _invite_registry.pop(code, None)

    connections = list(session.get("ws_connections", {}).values())
    if connections:
        async def _close_all() -> None:
            for ws in connections:
                try:
                    await ws.close(code=1001)  # 1001 = Going Away（サーバー都合の切断）
                except Exception:
                    pass
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_close_all())
        except RuntimeError:
            if _main_loop and _main_loop.is_running():
                asyncio.run_coroutine_threadsafe(_close_all(), _main_loop)


def _character_json_fingerprint(character_json: dict) -> str:
    """投票expelブラックリスト用のフィンガープリント（8.21対策）。

    以前はexpel可決時にトークン・接続は無効化していたが招待コード自体はブラック
    リスト化されず、オンラインセッションは同一招待コードの使い回しが仕様上OKなため、
    追放された本人が招待コードを覚えている限り新しいguest_idで即座に再参加できた。
    character_jsonの内容から決定的なハッシュを計算し、join_session側で同一の
    character_jsonでの再参加を拒否する（id/player_typeはjoin_session側でサーバーが
    後から付与するフィールドなので計算対象から除く）。character_jsonを少しでも
    書き換えれば回避できる不完全な対策だが、対応方針どおり「招待コード自体は
    失効させない（正当な再接続を巻き込まない）」範囲で塞げる限度として採用する。
    """
    payload = {k: v for k, v in character_json.items() if k not in ("id", "player_type")}
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _extract_content_policy_from_json(character_json: dict) -> dict:
    """flat形式・versioned形式（base_profile入れ子）の両方からcontent_policyを抽出する。

    _extract_audit_text（character_audit.py）と同じ両形式判定パターンを踏襲。
    アップロードされた生のcharacter_jsonが対象で、load_profiles()を経由していない
    ため、キャラクター側の_get_bp()は使えない（あちらは既にflat化済みの前提）。
    """
    if not isinstance(character_json, dict):
        return {}
    for v in character_json.values():
        if isinstance(v, dict) and isinstance(v.get("base_profile"), dict):
            return v["base_profile"].get("content_policy", {}) or {}
    return character_json.get("content_policy", {}) or {}


# ── FastAPI Dependency ────────────────────────────────────────────────

from fastapi import Header, HTTPException, Depends, Request


def _is_trusted_proxy_hop(request: Request) -> bool:
    """`CF-Connecting-IP` ヘッダーを信頼してよい接続か判定する。

    環境変数フラグだけでは、フラグをONにしたまま誤って `--host 0.0.0.0` で
    直接公開してしまった場合に、任意の第三者が `CF-Connecting-IP` ヘッダーを
    詐称してレート制限をバイパスできてしまう。そのため「cloudflared からの
    ローカル接続である」ことを TCPピア（127.0.0.1 / ::1）でも確認し、
    両方を満たす場合のみ信頼する。デフォルトOFF（環境変数を明示的に立てない
    限り従来通り `request.client.host` を使用する）。

    本判定はCloudflare Tunnelを公式デプロイ手段とする現行構成（dual_run.py、
    TCPソケットのみを使用しUnix Domain Socketは使わない）を前提としたもの。
    """
    if not os.environ.get("DEF_BEHIND_CLOUDFLARE_TUNNEL"):
        return False
    peer = request.client.host if request.client else ""
    return peer in ("127.0.0.1", "::1")


def _resolve_client_ip(request: Request) -> str:
    """レート制限のキーに使う実クライアントIPを解決する。

    `X-Forwarded-For` は複数プロキシ構成での解釈が難しく誤実装がそのまま
    ヘッダー詐称によるIP偽装に直結するため、意図的に採用しない。
    信頼できる場合のみ `CF-Connecting-IP`（Cloudflareが挿入する単一ヘッダー）
    を使用する。
    """
    if _is_trusted_proxy_hop(request):
        cf_ip = request.headers.get("cf-connecting-ip")
        if cf_ip:
            return cf_ip.strip()
    return request.client.host if request.client else "unknown"


def require_host(session_id: str, authorization: str = Header(...)) -> dict:
    """role == host かつ、そのJWTがこのsession_id用に発行されたものであることを両方チェックするDependency。

    `session_id`はURLパスパラメータ名と一致させることで、FastAPIが呼び出し元エンドポイントの
    パスパラメータをそのまま注入する。このDependencyを使う全ルートは`{session_id}`という
    パスパラメータを持つ前提（2026-08-04のBOLA監査でsession_idスコープ検証の欠如が発覚し、
    再発防止のためDependency自体に組み込んだ。個別エンドポイントでの`auth.get("session_id")
    != session_id`チェックはこの一本化に伴い削除済み）。
    """
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = verify_jwt(token)
    except _JWTError:
        raise HTTPException(401, "Invalid or expired token")
    if payload.get("role") != "host":
        raise HTTPException(403, "Host role required")
    if payload.get("session_id") != session_id:
        raise HTTPException(403, "Token session mismatch")
    return payload


def require_player(session_id: str, authorization: str = Header(...)) -> dict:
    """role == host / player / gm を通すDependency（observer は403）。session_idスコープも検証する（require_host参照）。"""
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = verify_jwt(token)
    except _JWTError:
        raise HTTPException(401, "Invalid or expired token")
    if payload.get("role") not in ("host", "player", "gm"):
        raise HTTPException(403, "Player role required")
    if payload.get("session_id") != session_id:
        raise HTTPException(403, "Token session mismatch")
    return payload


def require_keeper(session_id: str, authorization: str = Header(...)) -> dict:
    """role == host / gm を通すDependency（player / observer は403）。session_idスコープも検証する（require_host参照）。
    オンラインセッションで専任キーパー(gm)がゲーム進行を操作できるようにする。"""
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = verify_jwt(token)
    except _JWTError:
        raise HTTPException(401, "Invalid or expired token")
    if payload.get("role") not in ("host", "gm"):
        raise HTTPException(403, "Keeper role required")
    if payload.get("session_id") != session_id:
        raise HTTPException(403, "Token session mismatch")
    return payload


def require_participant(session_id: str, authorization: str = Header(...)) -> dict:
    """全ロール（host / player / gm / observer）を通す読み取り用Dependency。
    session_idスコープの検証と失効チェック（verify_jwt内のjti revoke）だけを行う。

    GET /{session_id} 用。以前は完全無認証で、session_idを知ってさえいれば
    退室・追放済みの元参加者や第三者でもセッション全体（history・npc_state等）を
    読み続けられた。observerは書き込み系（require_player）では拒否されるが、
    観戦という役割上、読み取りは正当なので通す。"""
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = verify_jwt(token)
    except _JWTError:
        raise HTTPException(401, "Invalid or expired token")
    if payload.get("role") not in ("host", "player", "gm", "observer"):
        raise HTTPException(403, "Participant role required")
    if payload.get("session_id") != session_id:
        raise HTTPException(403, "Token session mismatch")
    return payload


def _schedule_idle_shutdown(session_id: str, delay: int = 300) -> None:
    """全員切断後 delay 秒で AI タスクを停止する。再接続時はキャンセルする。"""
    async def _shutdown() -> None:
        await asyncio.sleep(delay)
        sess = _sessions.get(session_id)
        if not sess:
            return
        if (task := sess.get("ai_task")) and not task.done():
            task.cancel()

    sess = _sessions.get(session_id)
    if sess:
        sess["idle_shutdown_task"] = asyncio.create_task(_shutdown())


def _cancel_idle_shutdown(session_id: str) -> None:
    """再接続時に idle 停止タイマーをキャンセルする。"""
    sess = _sessions.get(session_id)
    if sess and (task := sess.get("idle_shutdown_task")) and not task.done():
        task.cancel()
        sess["idle_shutdown_task"] = None


# vram_lockは他の生成処理（LLM/T2I/TTS）と共有のグローバルシングルトン。取得元が
# 増えるほど「誰かが握ったまま長時間返ってこない」場合の影響範囲が広がるため、
# バックグラウンド生成系は無期限ブロックせずタイムアウトで諦める（fail-silent）。
# テスト環境でLLM呼び出しが未モックのままvram_lockを握り続け、後発のTTS取得が
# デッドロックした事例があったため導入（2026-08-02）。
# 環境変数で上書き可能にしているのはテスト実行時間の短縮用（モックし忘れを
# 60秒待たされず即座に検出できるようにするため）。本番の挙動自体は変えない。
_VRAM_LOCK_TIMEOUT_SECONDS = float(os.environ.get("DEF_VRAM_LOCK_TIMEOUT", "60"))


def _synthesize_turn_audio_sync(text: str, character_id: str, tts_backend: str) -> str:
    """テキストをTTS合成してassets/に保存し、配信用URLを返す（同期・fail-silent）。

    呼び出し元は必ずバックグラウンドスレッド（_generate_turn_audio /
    _synthesize_and_notify_audio）経由で呼ぶこと。リクエストハンドラから直接
    同期呼び出しすると、TTSバックエンドが無応答の場合にHTTPレスポンスごと
    ブロックされる（2026-08-02、human_turn_actionでの実装ミスで発覚）。
    """
    if not tts_backend or not text:
        return ""
    try:
        from def_kari.api.routes.tts import synthesize_and_save
        from def_kari.resources.vram_lock import get_vram_lock
        lock = get_vram_lock()
        if not lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
            _log.warning("vram_lock busy for over %.0fs, skipping TTS synthesis", _VRAM_LOCK_TIMEOUT_SECONDS)
            return ""
        try:
            return synthesize_and_save(text, character_id, tts_backend)
        finally:
            lock.release()
    except Exception:
        return ""


# ── サーバー自律AIターン ──────────────────────────────────────────

def _get_current_speaker(session: dict) -> str | None:
    """現在のターンのキャラIDを返す。ラウンド境界は % で吸収。"""
    initiative = session.get("initiative", [])
    if not initiative:
        return None
    turn = session.get("turn", 0)
    return initiative[turn % len(initiative)]


def _apply_skip(session_id: str, session: dict, char_id: str) -> dict:
    """指定キャラの現ターンをskip扱いで処理する（発言力+1・ターン進行・AIターン再開）。

    人間プレイヤー自身の自主skip（human_turn_action）と、切断タイムアウトによる
    自動skip（_schedule_disconnect_skip）の両方から呼ぶ共通ロジック。
    """
    name_map = session.get("name_map", {})
    char_name = name_map.get(char_id, char_id)
    counters = session.setdefault("counters", {})
    counters[char_id] = counters.get(char_id, 0) + 1
    session["turn"] = session.get("turn", 0) + 1
    session["action_count"] = 0
    _autosave(session_id)
    _game_event_bus.emit(session_id, "HUMAN_ACTION", {
        "character_id": char_id,
        "character_name": char_name,
        "text": "",
        "action": "skip",
        "counters": dict(counters),
    })
    _ai_task = session.get("ai_task")
    if not _ai_task or _ai_task.done():
        session["ai_task"] = asyncio.create_task(_run_ai_turns(session_id))
    return {
        "action": "skip",
        "character_id": char_id,
        "character_name": char_name,
        "round": session["round"],
        "counters": dict(counters),
    }


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


def _execute_ai_turn(session_id: str) -> dict:
    """AIターンを1回同期実行する（run_in_executor 用）。"""
    sess = _sessions.get(session_id)
    backend = sess.get("backend", DEFAULT_LLM_BACKEND) if sess else DEFAULT_LLM_BACKEND
    req = SessionNextRequest(session_id=session_id, backend=backend)
    return next_turn(req)


def _emit_waiting_for_human(session_id: str, session: dict) -> bool:
    """現在のターンが人間なら WAITING_FOR_HUMAN を emit して True を返す。

    _get_current_speaker は turn % len で折り返すが round/turn は更新しないため、
    ラウンド境界を越えていた場合はここで正規化する。
    """
    current = _get_current_speaker(session)
    if not current or not _is_human_char(session, current):
        return False
    _initiative = session.get("initiative", [])
    _raw_turn = session.get("turn", 0)
    if _initiative and _raw_turn >= len(_initiative):
        session["round"] = session.get("round", 1) + 1
        session["turn"] = _raw_turn % len(_initiative)
    _game_event_bus.emit(session_id, "WAITING_FOR_HUMAN", {
        "character_id": current,
        "character_name": session.get("name_map", {}).get(current, current),
        "round": session.get("round", 1),
        "counters": dict(session.get("counters", {})),
    })
    _maybe_schedule_disconnect_skip(session_id, session, current)
    return True


def _generate_turn_image(session_id: str, result: dict) -> None:
    """AIターン結果の image_prompt_en から挿絵をバックグラウンド生成し、TURN_IMAGE_READY をemitする（fail-silent）。

    従来は各クライアントが個別に POST /api/t2i/ を叩いていたが、それだと画像生成という
    重い操作を無認証で外部公開する必要が生じてしまう。サーバー側で1回だけ生成してWS配信する
    ことで、参加者側は読み取り専用の /api/t2i/image/{filename} だけで済むようにする。
    """
    try:
        image_prompt_en = result.get("image_prompt_en", "")
        if not image_prompt_en:
            return
        settings = load_settings()
        backend = settings.get("t2i_backend", "")
        if not backend:
            return
        model = settings.get(f"t2i_model_{backend}") or None
        from def_kari.resources.vram_lock import get_vram_lock
        lock = get_vram_lock()
        if not lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
            _log.warning("vram_lock busy for over %.0fs, skipping turn image generation", _VRAM_LOCK_TIMEOUT_SECONDS)
            return
        try:
            image_path = _generate_t2i_image(prompt=image_prompt_en, backend=backend, model=model)
        finally:
            lock.release()
        filename = Path(image_path).name
        url = f"/api/t2i/image/{filename}"
        _game_event_bus.emit(session_id, "TURN_IMAGE_READY", {
            "character_id": result.get("character_id", ""),
            "round": result.get("round"),
            "turn": result.get("turn"),
            "url": url,
        })
    except Exception as e:
        _log.warning("turn image generation failed for session=%s: %s", session_id, e)


def _generate_turn_audio(session_id: str, result: dict) -> None:
    """AIターン結果のテキストをバックグラウンドでTTS合成し、TURN_AUDIO_READY をemitする（fail-silent）。

    従来は各クライアントが個別に POST /api/tts/ → POST /api/tts/save を叩いていたが、
    それだと音声合成という重い操作を無認証で外部公開する必要が生じてしまう。
    サーバー側で1回だけ合成してWS配信する方式に統一した。

    tts_enabled設定がOFFの場合は生成自体をスキップする（以前は常に生成し
    クライアント側の再生可否のみで制御していたため、誰も聴かない音声を
    毎ターンvram_lockを使って合成し続ける無駄があった、2026-08-10発覚）。
    """
    try:
        settings = load_settings()
        if not settings.get("tts_enabled", True):
            return
        tts_backend = settings.get("tts_backend", "")
        url = _synthesize_turn_audio_sync(result.get("text", ""), result.get("character_id", ""), tts_backend)
        if not url:
            return
        _game_event_bus.emit(session_id, "TURN_AUDIO_READY", {
            "character_id": result.get("character_id", ""),
            "round": result.get("round"),
            "turn": result.get("turn"),
            "url": url,
        })
    except Exception as e:
        _log.warning("turn audio generation failed for session=%s: %s", session_id, e)


def _maybe_generate_turn_media(session_id: str, result: dict) -> None:
    """AIターン完了後の挿絵・TTSをそれぞれ独立したデーモンスレッドでバックグラウンド生成する。

    _run_ai_turns から AI_TURN_COMPLETED emit直後に呼ばれる。参加処理と同様、
    生成の成否に関わらずターン進行はブロックしない（fail-silent）。

    挿絵の自動生成はsession_auto_illustrate設定（デフォルトOFF）でオプトイン。
    OFF時は作画ボタン（generate_session_image、発言力消費・認証済み）のみで
    生成する。TTSは対象外（別軸のまま常時自動生成）。
    """
    if load_settings().get("session_auto_illustrate", False):
        threading.Thread(target=_generate_turn_image, args=(session_id, result), daemon=True).start()
    threading.Thread(target=_generate_turn_audio, args=(session_id, result), daemon=True).start()


def _synthesize_and_notify_audio(session_id: str, text: str, character_id: str, request_id: str) -> None:
    """バックグラウンドでTTS合成し、完了したら AUDIO_READY イベントをemitする（fail-silent）。

    human_turn_action（人間プレイヤー自己発言）・vote_deliberate（弁明ラウンド）が使う汎用版。
    AIターン自動読み上げ専用の _generate_turn_audio とは別に、character_id + request_id で
    紐付ける（呼び出し元ごとにレスポンス形状が異なり round/turn を持たないため）。
    """
    try:
        tts_backend = load_settings().get("tts_backend", "")
        url = _synthesize_turn_audio_sync(text, character_id, tts_backend)
        if not url:
            return
        _game_event_bus.emit(session_id, "AUDIO_READY", {
            "character_id": character_id,
            "request_id": request_id,
            "url": url,
        })
    except Exception as e:
        _log.warning("audio synth failed for session=%s: %s", session_id, e)


def _start_background_tts(session_id: str, text: str, character_id: str) -> str:
    """TTS合成をバックグラウンドスレッドで起動し、呼び出し元に返すrequest_idを発行する。

    人間プレイヤー自身の発言（human_turn_action・vote_deliberate・vote_proposal）に使う。
    text が空、tts_human_enabled設定がOFF（デフォルトOFF）、またはTTSバックエンド
    未設定の場合は空文字列を返しスレッドは起動しない
    （呼び出し元はaudio_request_idが空なら音声なしとして扱う）。
    """
    settings = load_settings()
    if not text or not settings.get("tts_human_enabled", False) or not settings.get("tts_backend", ""):
        return ""
    request_id = _uuid_mod.uuid4().hex[:12]
    threading.Thread(
        target=_synthesize_and_notify_audio,
        args=(session_id, text, character_id, request_id),
        daemon=True,
    ).start()
    return request_id


async def _run_ai_turns(session_id: str) -> None:
    """ai_resume で呼ばれる非同期タスク。現在のターンを1回だけ実行して停止する。
    連続進行（自動モード）はフロントエンドが AI_TURN_COMPLETED を受け取った後に
    再度 ai_resume を呼ぶことで実現する。"""
    session = _sessions.get(session_id)
    if not session:
        return
    try:
        if session.get("ai_paused"):
            return
        current = _get_current_speaker(session)
        if not current:
            return
        if _emit_waiting_for_human(session_id, session):
            return
        _skip_gen_snap = session.get("_skip_gen", 0)
        result = await asyncio.get_event_loop().run_in_executor(
            None, _execute_ai_turn, session_id
        )
        # executor 実行中に keeper_skip が入った場合は結果を捨てる。
        # skip_turn が新しいタスクを作成するのでここでは再実行不要。
        if session.get("_skip_gen", 0) != _skip_gen_snap:
            return
        if result.get("error"):
            # 生成エラー時は自動進行を止め、全タブに状態を同期する
            if session.get("auto_advance"):
                session["auto_advance"] = False
                _game_event_bus.emit(session_id, "AUTO_ADVANCE_CHANGED", {"enabled": False})
            _game_event_bus.emit(session_id, "AI_ERROR", {"error": result["error"]})
            return
        if result.get("waiting_for_human"):
            _game_event_bus.emit(session_id, "WAITING_FOR_HUMAN", {
                "character_id": result.get("character_id", ""),
                "character_name": result.get("character_name", ""),
                "round": result.get("round", 1),
                "counters": dict(result.get("counters", session.get("counters", {}))),
            })
            if result.get("character_id"):
                _maybe_schedule_disconnect_skip(session_id, session, result["character_id"])
            return
        _game_event_bus.emit(session_id, "AI_TURN_COMPLETED", result)
        _maybe_generate_turn_media(session_id, result)
        # 次のターンが人間なら ai_resume の往復を待たずに即通知する。
        # ai_resume は require_keeper のためプレイヤータブは連鎖を駆動できず、
        # ここで通知しないと人間ターン直前で進行が止まる。
        _emit_waiting_for_human(session_id, session)
        await asyncio.sleep(0)  # event loop に yield
    except asyncio.CancelledError:
        raise
    except Exception as e:
        _log.error("[ai_turns] session=%s error=%s", session_id, e)


async def _end_session(session_id: str) -> None:
    """セッション終了: AIタスク停止・WS切断・JTIクリーンアップ・メモリ解放。"""
    session = _sessions.pop(session_id, None)
    if not session:
        return
    tasks_to_cancel = []
    for key in ("ai_task", "idle_shutdown_task"):
        if (t := session.get(key)) and not t.done():
            t.cancel()
            tasks_to_cancel.append(t)
    for t in session.get("disconnect_skip_tasks", {}).values():
        if not t.done():
            t.cancel()
            tasks_to_cancel.append(t)
    if tasks_to_cancel:
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
    for ws in list(session.get("ws_connections", {}).values()):
        try:
            await ws.close(code=1000)
        except Exception:
            pass
    # 復元直後のセッションは ws_connections キーを持たない可能性があるため .get() を使う
    session.get("ws_connections", {}).clear()
    for token in list(session.get("players", {}).keys()):
        _ws_send_locks.pop(token, None)
    # 招待コードのグローバルレジストリからも削除
    for code in list(session.get("invite_codes", {}).keys()):
        _invite_registry.pop(code, None)


def _save_session_episodic(session_id: str, session: dict) -> None:
    """セッション終了時に各キャラクターの episodic memory を書き込む。"""
    try:
        from def_kari.gm.memory import save_episodic
    except ImportError:
        return

    history = session.get("history", [])
    name_map = session.get("name_map", {})
    topic = session.get("topic", "")
    round_count = session.get("round", 1)
    all_char_ids = session.get("initiative", [])
    ts = datetime.datetime.now().isoformat()

    for char_id in all_char_ids:
        # このキャラの assistant 発言から key_moments を抽出（最後の3件）
        char_lines = [
            h["content"].split(": ", 1)[-1]
            for h in history
            if h.get("role") == "assistant" and h.get("character_id") == char_id
        ]
        key_moments = char_lines[-3:] if char_lines else []

        # 最後の感情状態
        emotion_at_end = next(
            (h.get("emotion", "neutral") for h in reversed(history)
             if h.get("character_id") == char_id and h.get("emotion")),
            "neutral",
        )

        entry = {
            "session_id": session_id,
            "date": ts,
            "topic": topic,
            "round_count": round_count,
            "participants": [name_map.get(c, c) for c in all_char_ids if c != char_id],
            "key_moments": key_moments,
            "emotion_at_end": emotion_at_end,
        }
        save_episodic(char_id, entry)


def _build_initial_npc_state(scenario_id: str) -> dict:
    """シナリオの静的NPC定義から npc_state を初期化する。

    npc_state = {
        npc_id: {
            "knowledge": [str, ...],       # セッション中に獲得した情報
            "relationship": {              # PC/NPC との関係値（動的更新）
                char_id: {"trust": int, "hostility": int}
            }
        }
    }
    静的なデフォルト値（goal / description など）は scenario JSON を直接参照し、
    セッション中の変更分のみ npc_state に保持する。
    """
    if not scenario_id:
        return {}
    scenario = _load_trpg_scenario(scenario_id)
    npc_state = {}
    for npc in scenario.get("npcs", []):
        nid = npc.get("id")
        if not nid:
            continue
        npc_state[nid] = {
            "knowledge": list(npc.get("knowledge", [])),
            "relationship": {
                k: dict(v) for k, v in npc.get("relationship", {}).items()
            },
        }
    return npc_state


_BASE = Path(__file__).parent.parent.parent.parent
_RULE_DIRS = [
    _BASE / "data" / "public" / "session_rules",
    _BASE / "data" / "private" / "session_rules",
]
# 無認証の公開ポート（public_main.py）向けの探索範囲。data/private/session_rulesを含まない。
# GET /rules・/rules/{rule_id}は招待コードのみで参加するゲストの画面でも呼ばれるため
# local_routerには移せない（読み取り自体は許可する）が、私有・NSFWルールセットの
# フルコンテンツまで無認証で読めてしまっていたため、探索範囲を分離した。
_PUBLIC_RULE_DIRS = [
    _BASE / "data" / "public" / "session_rules",
]
_DIRECTIVE_DIRS = [
    _BASE / "data" / "public" / "action_directives",
    _BASE / "data" / "private" / "action_directives",
]
# 同上（アクションディレクティブ版）。
_PUBLIC_DIRECTIVE_DIRS = [
    _BASE / "data" / "public" / "action_directives",
]
_SESSION_HISTORY_DIRS = [
    _BASE / "data" / "public" / "session_history",
    _BASE / "data" / "private" / "session_history",
]
_AUTOSAVE_DIR = _BASE / "data" / "private" / "session_autosave"
_VISITORS_DIR = _BASE / "data" / "visitors"
_VISITORS_MAX_FILES = 5000  # 新規ディレクトリ作成時のみ判定。既存の上書き更新は無制限
_SAFE_FILENAME_RE = re.compile(r'^[A-Za-z0-9_\-]+\.json$')


def _autosave_visitors(session: dict) -> None:
    """guest_chars（持ち込みキャラ）を data/visitors/{char_id}/profile.json に書き出す。

    join直後と _autosave() の両方から呼ばれる（べき等・上書き）。ディレクトリ形式にしているのは
    def_kari/gm/memory.py の _char_base_dir() がそのまま visitors/{char_id}/ を認識できるようにするため
    （episodic memory 対応、guest_id は毎回使い捨てなので次回セッションへの引き継ぎはされない）。
    """
    guest_chars = session.get("guest_chars", {})
    if not guest_chars:
        return
    try:
        _VISITORS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    existing_count = None  # 新規ディレクトリ作成が発生したときだけ遅延評価する
    skill_values = session.get("skill_values", {})
    runtime_stats = session.get("runtime_stats", {})
    counters = session.get("counters", {})
    for char_id, char_data in guest_chars.items():
        char_dir = _VISITORS_DIR / char_id
        if not char_dir.exists():
            if existing_count is None:
                existing_count = sum(1 for _ in _VISITORS_DIR.iterdir() if _.is_dir())
            if existing_count >= _VISITORS_MAX_FILES:
                _log.warning("visitors/ cap (%d) reached, skipping new visitor dir for %s", _VISITORS_MAX_FILES, char_id)
                continue
            existing_count += 1
        snapshot = dict(char_data)
        if char_id in skill_values:
            snapshot["_session_skill_values"] = skill_values[char_id]
        if char_id in runtime_stats:
            snapshot["_session_runtime_stats"] = runtime_stats[char_id]
        if char_id in counters:
            snapshot["_session_counter"] = counters[char_id]
        try:
            char_dir.mkdir(parents=True, exist_ok=True)
            (char_dir / "profile.json").write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass


def _extract_appearance_tags(character_json: dict) -> str:
    """flat形式・versioned形式（base_profile入れ子）の両方から appearance_tags（無ければ features）を取り出す。"""
    if not isinstance(character_json, dict):
        return ""
    for v in character_json.values():
        if isinstance(v, dict) and isinstance(v.get("base_profile"), dict):
            bp = v["base_profile"]
            vr = bp.get("visual_references") or {}
            return bp.get("appearance_tags") or vr.get("appearance_tags") or vr.get("features") or ""
    vr = character_json.get("visual_references") or {}
    return character_json.get("appearance_tags") or vr.get("appearance_tags") or vr.get("features") or ""


def _generate_visitor_images(session_id: str, char_id: str, character_json: dict) -> None:
    """持ち込みキャラのアイコン・立ち絵をバックグラウンドで生成する（fail-silent）。

    join_session からデーモンスレッドで起動され、参加処理の完了はこれを待たない。
    生成完了時に VISITOR_ICON_READY をemitし、フロントにアイコン再取得を促す
    （画像配信は _NO_CACHE_HEADERS 済みなので、フロント側は同URLを再フェッチするだけでよい）。
    """
    try:
        appearance_tags = _extract_appearance_tags(character_json)
        if not appearance_tags:
            return
        settings = load_settings()
        backend = settings.get("t2i_backend", "")
        if not backend:
            return
        model = settings.get(f"t2i_model_{backend}") or None
        char_dir = _VISITORS_DIR / char_id
        char_dir.mkdir(parents=True, exist_ok=True)

        from def_kari.resources.vram_lock import get_vram_lock
        lock = get_vram_lock()

        icon_prompt = f"portrait, face close-up, {appearance_tags}, white background, simple background"
        if not lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
            _log.warning("vram_lock busy for over %.0fs, skipping visitor icon generation", _VRAM_LOCK_TIMEOUT_SECONDS)
            return
        try:
            icon_path = _generate_t2i_image(prompt=icon_prompt, backend=backend, model=model, width=512, height=512)
        finally:
            lock.release()
        shutil.copy2(icon_path, char_dir / "icon.png")

        standing_prompt = f"full body, standing, {appearance_tags}, white background, simple background"
        if not lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
            _log.warning("vram_lock busy for over %.0fs, skipping visitor standing generation", _VRAM_LOCK_TIMEOUT_SECONDS)
            return
        try:
            standing_path = _generate_t2i_image(prompt=standing_prompt, backend=backend, model=model, width=832, height=1216)
        finally:
            lock.release()
        shutil.copy2(standing_path, char_dir / "standing.png")

        _game_event_bus.emit(session_id, "VISITOR_ICON_READY", {"character_id": char_id})
    except Exception as e:
        _log.warning("visitor image generation failed for %s: %s", char_id, e)


def _autosave(session_id: str) -> None:
    session = _sessions.get(session_id)
    if not session:
        return
    try:
        _AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
        (_AUTOSAVE_DIR / f"{session_id}.json").write_text(
            json.dumps(_session_for_json(session), ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass
    _autosave_visitors(session)
    _cleanup_stale_autosaves()


def _delete_autosave(session_id: str) -> None:
    try:
        (_AUTOSAVE_DIR / f"{session_id}.json").unlink(missing_ok=True)
    except Exception:
        pass


# autosaveファイルのTTL（この期間以上更新がなければ放置されたセッションとみなす）。
# _delete_autosave() はセッション正常終了時（/end 等）にしか呼ばれないため、プロセスの
# 異常終了やホストが /end を呼ばずに放置した場合、ファイルが際限なく溜まり続けていた
# （実測1752個）。
_AUTOSAVE_TTL_SEC = 7 * 24 * 3600.0  # 7日
_AUTOSAVE_CLEANUP_INTERVAL_SEC = 3600.0  # 稼働中の定期掃除の間隔（1時間）
_autosave_last_cleanup: dict[str, float] = {"t": 0.0}


def _cleanup_stale_autosaves() -> None:
    """_sessions に存在しない（＝終了済み・復元されなかった）セッションのうち、
    最終更新からTTLを超えたautosaveファイルを間引く。呼び出し頻度の高い
    _autosave() に軽量にフックし、一定間隔でのみ実際の掃除を行う
    （S-3の _cleanup_invite_rate_state と同じパターン）。
    """
    now = time.monotonic()
    if now - _autosave_last_cleanup["t"] < _AUTOSAVE_CLEANUP_INTERVAL_SEC:
        return
    _autosave_last_cleanup["t"] = now
    try:
        if not _AUTOSAVE_DIR.is_dir():
            return
        wall_now = time.time()
        for _f in _AUTOSAVE_DIR.iterdir():
            if _f.suffix != ".json" or _f.stem in _sessions:
                continue
            try:
                if wall_now - _f.stat().st_mtime > _AUTOSAVE_TTL_SEC:
                    _f.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


# ── 起動時に進行中セッションを復元 ──────────────────────────────
try:
    if _AUTOSAVE_DIR.is_dir():
        _wall_now = time.time()
        for _f in sorted(_AUTOSAVE_DIR.iterdir()):
            if _f.suffix == ".json":
                try:
                    # TTLを超えて放置されたファイルは復元せず削除する
                    if _wall_now - _f.stat().st_mtime > _AUTOSAVE_TTL_SEC:
                        _f.unlink(missing_ok=True)
                        continue
                    _restored = json.loads(_f.read_text(encoding="utf-8"))
                    if isinstance(_restored, dict) and _restored.get("id"):
                        _sessions[_restored["id"]] = _restored
                except Exception:
                    pass
except Exception:
    pass


def _apply_char_tags(prompt: str, char_id: str | None, profiles: dict | None = None) -> str:
    """appearance_tags・image_name_tags・LoRA をプロンプトに適用する。
    name_tags を先頭、appearance_tags を追加、LoRA 構文を末尾に付加。"""
    if not char_id:
        return prompt
    if profiles is None:
        profiles = load_profiles()
    _char = get_character(char_id, profiles)
    _app_tags = _char.get("appearance_tags", "").strip()
    _name_tags = _char.get("image_name_tags", "").strip()
    _lora = _char.get("lora") or []

    _clean = re.sub(r'<lora:[^>]+>', '', prompt).strip().strip(',').strip()
    _existing = [t.strip() for t in _clean.split(',') if t.strip()]
    _existing_lower = {t.lower() for t in _existing}

    _prefix_raw = [t.strip() for t in (_name_tags + ',' + _app_tags).split(',') if t.strip()]
    _prefix = [t for t in _prefix_raw if t.lower() not in _existing_lower]

    from def_kari.characters import build_lora_prompt
    _lora_str = build_lora_prompt(_lora)

    result = ', '.join(_prefix + _existing)
    if _lora_str:
        result = (result + ' ' + _lora_str).strip()
    return result


def _clean_history_for_retake(history: list, remove: int) -> tuple[list, int]:
    """履歴末尾から assistant エントリを remove 件削除する。
    _scene_image エントリ（role なし）はカウントせずスキップして削除する。"""
    new_history = list(history)
    removed = 0
    while new_history:
        entry = new_history[-1]
        if entry.get("character_id") == "_scene_image":
            new_history.pop()
            continue
        if removed < remove and entry.get("role") == "assistant":
            new_history.pop()
            removed += 1
        else:
            break
    return new_history, removed


def _load_action_directives(public_only: bool = False) -> dict:
    directives: dict = {}
    for d in (_PUBLIC_DIRECTIVE_DIRS if public_only else _DIRECTIVE_DIRS):
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix == ".json" and f.name != ".gitkeep":
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        did = data.get("id", f.stem)
                        directives[did] = data
                    except (json.JSONDecodeError, OSError):
                        pass
    if "none" not in directives:
        directives["none"] = {"id": "none", "label": "指示なし（キャラクターに任せる）", "directives": {}}
    return directives


def _ai_action_select(
    backend_id: str,
    model: str,
    char: dict,
    char_id: str,
    counter: int,
    round_num: int,
    history: list[dict],
    initiative: list[str],
    name_map: dict,
    speaker_name: str,
    lang: str,
) -> dict:
    """TRPGモード Round>=2 でAIが取るアクションをLLMに選ばせる。失敗時は {"action": "none"} を返す。"""
    _default: dict = {"action": "none", "target_name": "", "vote_type": "", "vote_detail": "", "reason": ""}
    if backend_id not in LLM_BACKENDS:
        return _default

    other_names = [name_map.get(c, c) for c in initiative if name_map.get(c, c) != speaker_name]
    recent_lines = [h.get("content", "")[:80] for h in history[-3:]]
    recent_text = "\n".join(recent_lines)

    available = ["none", "skip"]
    if counter >= 1:
        available += ["extend", "designate"]
    if counter >= 3:
        available.append("vote")

    # 直前にダイスを振っていたら自発スキップ禁止
    _last_char_entry = next(
        (h for h in reversed(history) if h.get("character_id") == char_id),
        None,
    )
    if _last_char_entry and _last_char_entry.get("judgment"):
        available = [a for a in available if a != "skip"]

    # 利用可能なアクションの説明だけ生成（マイナスになる選択肢は説明ごと除外）
    if lang == "en":
        _descs: list[str] = [
            "- none: speak normally (cost 0)",
            "- skip: voluntary skip, speech power +1",
        ]
        if "extend" in available:
            _descs.append(f"- extend: emphatic speech, cost -1 (current {counter} → {counter - 1})")
        if "designate" in available:
            _descs.append(f"- designate: designate next speaker, cost -1 (current {counter} → {counter - 1}), set target_name to one of {other_names}")
        if "vote" in available:
            _descs.append(f"- vote: propose vote, consumes all speech power (current {counter} → 0), set vote_type(topic_change/expel/end_session) and vote_detail")
        system_msg = (char.get("persona_description") or f"You are {speaker_name}.")[:300]
        user_msg = (
            f"[TRPG Action Selection]\nRound {round_num}, your turn as {speaker_name}.\n"
            f"Speech Power: {counter}\nParticipants: {', '.join(other_names)}\n"
            f"Recent:\n{recent_text}\n\n"
            f"Choose ONE action from: {available}\n"
            + "\n".join(_descs) + "\n\n"
            'Respond with JSON only: {"action":"...","target_name":"","vote_type":"","vote_detail":"","reason":""}'
        )
    else:
        _descs = [
            "- none: 通常発言（コスト0）",
            "- skip: 自発的スキップ、発言力+1",
        ]
        if "extend" in available:
            _descs.append(f"- extend: 力強い発言、発言力-1（現在{counter} → {counter - 1}）")
        if "designate" in available:
            _descs.append(f"- designate: 次の発言者を指名、発言力-1（現在{counter} → {counter - 1}）、target_nameに{other_names}から選んで指定")
        if "vote" in available:
            _descs.append(f"- vote: 投票発議、発言力を全て消費（現在{counter} → 0）、vote_type(topic_change/expel/end_session)とvote_detailを指定")
        system_msg = (char.get("persona_description") or f"あなたは{speaker_name}です。")[:300]
        user_msg = (
            f"[TRPGアクション選択]\nラウンド{round_num}、{speaker_name}のターンです。\n"
            f"発言力: {counter}\n参加者: {', '.join(other_names)}\n"
            f"直近の会話:\n{recent_text}\n\n"
            f"以下から1つ選んでください: {available}\n"
            + "\n".join(_descs) + "\n\n"
            '{"action":"...","target_name":"","vote_type":"","vote_detail":"","reason":""}のJSONのみで返してください'
        )

    chat_fn = LLM_BACKENDS[backend_id]["chat"]
    messages_payload = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]
    from def_kari.resources.vram_lock import get_vram_lock as _get_vl
    _vl = _get_vl()
    _vl.acquire()
    try:
        raw = chat_fn(messages_payload, model, json_mode=True, options={"num_predict": 80})
    except Exception:
        return _default
    finally:
        _vl.release()

    if not raw:
        return _default

    # thinkingタグ除去
    raw = re.sub(r'<think(?:ing)?[^>]*>.*?</think(?:ing)?>', '', raw, flags=re.DOTALL).strip()
    # JSONブロック抽出
    m = re.search(r'\{[^{}]+\}', raw, re.DOTALL)
    raw_json = m.group() if m else raw
    try:
        parsed = json.loads(raw_json)
    except Exception:
        return _default

    action = str(parsed.get("action", "none"))
    if action not in available:
        action = "none"
    parsed["action"] = action
    return {**_default, **{k: str(v) for k, v in parsed.items()}}


def _is_public_request(request: Request) -> bool:
    """呼び出し元がpublic_app（無認証で外部公開されるポート）経由かを判定する。

    session.router はmain.py（ローカル、フル機能）とpublic_main.py（Cloudflare Tunnel等
    での公開用）の両方に同一インスタンスがマウントされている。dual_run.pyは両アプリを
    同一プロセスに同居させるため、モジュールレベルのグローバル変数では区別できない。
    request.app.state に public_main.py 側だけが立てるフラグを見て判定する。
    """
    return bool(getattr(request.app.state, "is_public_port", False))


@router.get("/action-directives")
def get_action_directives(request: Request):
    directives = _load_action_directives(public_only=_is_public_request(request))
    return {
        "directives": [
            {"id": did, "label": d.get("label", did), "rating": d.get("rating", "general"), "recommended_for": d.get("recommended_for", [])}
            for did, d in directives.items()
        ]
    }


def _load_session_rules(public_only: bool = False) -> dict:
    rules = {}
    for d in (_PUBLIC_RULE_DIRS if public_only else _RULE_DIRS):
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix == ".json":
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        rid = data.get("id", f.stem)
                        rules[rid] = data
                    except (json.JSONDecodeError, OSError):
                        pass
    if not rules:
        rules["none"] = {"id": "none", "label": "ルールなし", "rules": []}
    return rules


@router.get("/rules")
def get_session_rules(request: Request):
    rules = _load_session_rules(public_only=_is_public_request(request))
    return {
        "rules": [
            {"id": rid, "label": r.get("label", rid)}
            for rid, r in rules.items()
        ]
    }


@router.get("/rules/{rule_id}")
def get_session_rule_detail(rule_id: str, request: Request):
    if not re.match(r'^[A-Za-z0-9_\-]+$', rule_id):
        return {"error": "Invalid rule ID"}
    dirs = _PUBLIC_RULE_DIRS if _is_public_request(request) else _RULE_DIRS
    for d in dirs:
        path = d / f"{rule_id}.json"
        if path.exists():
            try:
                return {"content": path.read_text(encoding="utf-8"), "id": rule_id}
            except OSError as e:
                return {"error": str(e)}
    return {"error": f"Rule '{rule_id}' not found"}


class SaveRuleRequest(BaseModel):
    content: str


@local_router.put("/rules/{rule_id}")
def save_session_rule(rule_id: str, req: SaveRuleRequest):
    if not re.match(r'^[A-Za-z0-9_\-]+$', rule_id):
        return {"error": "Invalid rule ID"}
    try:
        data = json.loads(req.content)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}
    target: Path | None = None
    for d in _RULE_DIRS:
        path = d / f"{rule_id}.json"
        if path.exists():
            target = path
            break
    if target is None:
        _RULE_DIRS[0].mkdir(parents=True, exist_ok=True)
        target = _RULE_DIRS[0] / f"{rule_id}.json"
    tmp = str(target) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(target))
    return {"status": "ok", "id": rule_id}


class SessionStartRequest(BaseModel):
    character_ids: list[str]
    topic: str = ""
    backend: str = DEFAULT_LLM_BACKEND
    rule_set: str = "default"
    actions_per_turn: int = 0
    action_directive_set: str = ""
    char_backends: dict[str, str] = {}
    trpg_mode: bool = False
    trpg_rulebook: str = ""
    trpg_scenario: str = ""
    char_game_sheets: dict[str, str] = {}
    keeper_char_id: str = ""
    human_keeper: bool = False
    online_mode: bool = False  # オンラインセッション: キャラなしで開始し参加者が持ち込む


class SessionNextRequest(BaseModel):
    session_id: str
    backend: str = DEFAULT_LLM_BACKEND
    model: str = ""


class KeeperMessageRequest(BaseModel):
    text: str


@router.post("/start")
def start_session(req: SessionStartRequest, request: Request):
    client_ip = _resolve_client_ip(request)
    if not _check_session_create_rate(client_ip):
        raise HTTPException(429, "Too many session creation requests")
    if contains_blocked_content(req.topic):
        raise HTTPException(400, "This topic cannot be used.")

    from def_kari.settings import load_settings as _load_s
    _s = _load_s()
    apt = req.actions_per_turn or _s.get("session_actions_per_turn", 2)
    directive_set_id = req.action_directive_set or _s.get("session_action_directive_set", "default")

    session_id = secrets.token_urlsafe(16)
    profiles = load_profiles()
    if not req.online_mode:
        for cid in req.character_ids:
            char = get_character(cid, profiles)
            if char and char.get("entity_type") == "base_entity":
                raise HTTPException(400, f"base_entity '{cid}' はセッションに参加できません")
    all_name_map = {}
    for cid in req.character_ids:
        char = get_character(cid, profiles)
        all_name_map[cid] = char.get("name", cid) if char else cid
    keeper_char_id = req.keeper_char_id if req.keeper_char_id in req.character_ids else ""
    player_ids = [c for c in req.character_ids if c != keeper_char_id]
    initiative = [] if req.online_mode else random.sample(player_ids, len(player_ids))
    name_map = {cid: all_name_map[cid] for cid in player_ids}

    if len(_sessions) >= _MAX_SESSIONS:
        _evict_oldest_session()
    _rule_data = _load_session_rules().get(req.rule_set, {})
    rules = _rule_data.get("rules", [])
    scene = _rule_data.get("scene", "")
    rule_style = _rule_data.get("style", "discussion")
    rule_max_chars = _rule_data.get("max_chars", 0)
    rule_max_rounds = _rule_data.get("max_rounds", 0)
    char_backends = {
        cid: bid
        for cid, bid in req.char_backends.items()
        if cid in req.character_ids and bid in LLM_BACKENDS
    }
    _skill_pool_init = 0
    if req.trpg_mode and req.trpg_rulebook:
        _rb = _load_trpg_rulebook(req.trpg_rulebook)
        _skill_pool_init = int(_rb.get("skill_point_pool", 0))

    _sessions[session_id] = {
        "id": session_id,
        "initiative": initiative,
        "name_map": name_map,
        "topic": req.topic,
        "backend": req.backend,
        "char_backends": char_backends,
        "rule_set": req.rule_set,
        "rules": rules,
        "style": rule_style,
        "max_chars": rule_max_chars,
        "max_rounds": rule_max_rounds,
        "scene": scene,
        "round": 1,
        "turn": 0,
        "action_count": 0,
        "actions_per_turn": apt,
        "action_directive_set": directive_set_id,
        "history": [],
        "counters": {},
        "designated_next": None,
        "trpg_mode": req.trpg_mode,
        "trpg_rulebook": req.trpg_rulebook,
        "trpg_scenario": req.trpg_scenario,
        "char_game_sheets": req.char_game_sheets,
        "current_scene_index": 0,
        "scene_round_start": 0,
        "player_knowledge": {cid: [] for cid in player_ids},
        "npc_state": _build_initial_npc_state(req.trpg_scenario),
        "skill_pool": {cid: _skill_pool_init for cid in player_ids},
        "skill_values": {cid: {} for cid in player_ids},
        "keeper_char_id": keeper_char_id,
        "keeper_char_name": all_name_map.get(keeper_char_id, "") if keeper_char_id else "",
        "human_keeper": req.human_keeper,
        # ── Phase 2: マルチプレイフィールド ──
        "players": {},              # token → char_id（参加者マップ）
        "host_token": "",           # ホストのJWT（発行後に上書き）
        "ws_connections": {},       # token → WebSocket
        "ai_task": None,            # asyncio.Task | None
        "idle_shutdown_task": None, # asyncio.Task | None
        "invite_codes": {},         # invite_code → {"rating": str, "used": bool}
        # ── Phase 2/3: マルチプレイ運用データ ──
        "ws_rate": {},          # token → deque（WS rate limit。セッション終了で自動消滅）
        # ── Phase 3: 複数人間プレイヤー対応 ──
        "human_char_ids": [
            cid for cid in player_ids
            if (get_character(cid, profiles) or {}).get("player_type") == "human"
        ],
        "online_mode": req.online_mode,
        "lobby_active": req.online_mode,  # Trueの間はターン進行をブロック
        "host_keeper_mode": bool(req.online_mode),  # オンラインはデフォルトでキーパー専任（ロビーPATCHで変更可）
        "max_players": 4 if req.online_mode else 0,  # オンライン: UIデフォルトと同じ4。ロビー設定・開始時lobby_configで上書き
        "invited_gm_token": "", # 招待GMのtoken（1人まで）
    }

    # ホストトークンを発行して sessions に書き込む
    host_token = issue_player_jwt(session_id, "host")
    _sessions[session_id]["host_token"] = host_token
    _sessions[session_id]["players"][host_token] = ""  # ホストはキャラなし（既存仕組みを維持）

    order = [name_map.get(c, c) for c in initiative]

    # オンラインモードは招待コードを自動発行（ホストが手動発行する必要をなくす）
    invite_code_auto = ""
    if req.online_mode:
        invite_code_auto = _generate_invite_code("SFW")
        _invite_registry[invite_code_auto] = session_id
        _sessions[session_id]["invite_codes"][invite_code_auto] = {"rating": "SFW", "used": False}

    _autosave(session_id)
    return {
        "session_id": session_id,
        "initiative": initiative,
        "order": order,
        "human_keeper": req.human_keeper,
        "host_token": host_token,
        "invite_code": invite_code_auto,
    }


class InviteRequest(BaseModel):
    rating: str = "SFW"


@router.post("/{session_id}/invite")
def create_invite(session_id: str, req: InviteRequest, auth: dict = Depends(require_host)):
    """招待コードを発行する（ホストのみ）。"""
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    rating = req.rating if req.rating in _INVITE_RATINGS else "SFW"
    # 衝突を避けながら生成
    for _ in range(10):
        code = _generate_invite_code(rating)
        if code not in _invite_registry:
            break
    _invite_registry[code] = session_id
    sess["invite_codes"][code] = {"rating": rating, "used": False}
    return {"invite_code": code, "rating": rating, "session_id": session_id}


class AvailableSlotsRequest(BaseModel):
    invite_code: str


@router.post("/available-slots")
def get_available_slots(req: AvailableSlotsRequest, request: Request):
    """招待コードで入れるセッションの人間スロット一覧を返す（参加前プレビュー）。

    招待コードの正誤を判定するオラクルとして機能するため、join_session同様に
    _check_invite_rate/_record_invite_failでレート制限する（8.4対策。以前はここが
    無防備で、_check_invite_rateを経由せず本エンドポイントだけを連打すればS-1の
    ブルートフォース対策を完全にバイパスできた）。
    """
    client_ip = _resolve_client_ip(request)
    if not _check_invite_rate(client_ip):
        raise HTTPException(429, "Too many failed attempts")

    code = req.invite_code.strip().upper()
    session_id = _invite_registry.get(code)
    if not session_id:
        _record_invite_fail(client_ip)
        raise HTTPException(404, "Invalid invite code")
    sess = _sessions.get(session_id)
    if not sess:
        _record_invite_fail(client_ip)
        raise HTTPException(404, "Session not found")
    invite_info = sess["invite_codes"].get(code, {})
    if invite_info.get("used") and not sess.get("online_mode"):
        raise HTTPException(409, "Invite code already used")

    human_ids = set(sess.get("human_char_ids", []))
    claimed = {v for v in sess.get("players", {}).values() if v}
    name_map = sess.get("name_map", {})
    initiative = sess.get("initiative", [])

    slots = [
        {
            "char_id": cid,
            "char_name": name_map.get(cid, cid),
            "available": cid not in claimed,
        }
        for cid in initiative
        if cid in human_ids
    ]
    return {
        "session_id": session_id,
        "human_slots": slots,
        "online_mode": sess.get("online_mode", False),
        "gm_taken": bool(sess.get("invited_gm_token")) or sess.get("host_keeper_mode", False),
        "waiting_for_gm": sess.get("waiting_for_gm", False),
        "trpg_mode": sess.get("trpg_mode", False),
    }


class JoinRequest(BaseModel):
    invite_code: str
    claim_char_id: str = ""   # 既存人間スロットを引き継ぐ
    character_json: dict = {} # オンラインセッション: キャラJSON持ち込み
    join_as_gm: bool = False  # オンラインセッション: GM/キーパーとして参加


@router.post("/join")
def join_session(req: JoinRequest, request: Request):
    """招待コードでセッションに参加し、player JWT を返す。"""
    client_ip = _resolve_client_ip(request)
    if not _check_invite_rate(client_ip):
        raise HTTPException(429, "Too many failed attempts")

    code = req.invite_code.strip().upper()
    session_id = _invite_registry.get(code)
    if not session_id:
        _record_invite_fail(client_ip)
        raise HTTPException(404, "Invalid invite code")

    sess = _sessions.get(session_id)
    if not sess:
        _record_invite_fail(client_ip)
        raise HTTPException(404, "Session not found")

    invite_info = sess["invite_codes"].get(code, {})
    # オンラインセッションでは同じコードを複数人が使えるようにする
    if invite_info.get("used") and not sess.get("online_mode"):
        raise HTTPException(409, "Invite code already used")

    session_rating = invite_info.get("rating", "SFW")

    char_id = ""
    role = "observer"
    display_name = "Observer"

    # 参加人数チェック（オブザーバー・GMは対象外）
    if req.character_json and sess.get("online_mode"):
        # オンラインロビー: initiative = AIスロット + 参加済みプレイヤーのゲストキャラ。
        # ロビーUIのスロット表示（aiSlots + playerSlots）と同じ基準で判定する。
        # ※ホストのプレイヤー参加枠は開始時（lobby_config）までinitiativeに入らないため
        #   ここではカウントされない（ホストは自セッションのため定員外とする）
        max_p = sess.get("max_players", 0)
        current_p = len(sess.get("initiative", []))
        if max_p > 0 and current_p >= max_p:
            raise HTTPException(409, f"Session is full ({current_p}/{max_p})")
    elif req.claim_char_id:
        # オフライン形式のスロット引き継ぎ: 既存人間スロットへの割り当てなので
        # 実質の定員はスロット数で制限済み（Slot already taken で拒否）
        max_p = sess.get("max_players", 0)
        if max_p > 0:
            host_token = sess.get("host_token", "")
            current_p = sum(
                1 for tok, cid in sess.get("players", {}).items()
                if tok == host_token or cid
            )
            if current_p >= max_p:
                raise HTTPException(409, f"Session is full ({current_p}/{max_p})")

    if req.join_as_gm:
        # GM/キーパーとして参加（1人まで）; ホストがキーパー専任の場合も拒否
        if sess.get("invited_gm_token") or sess.get("host_keeper_mode"):
            raise HTTPException(409, "GM slot is already taken")
        role = "gm"
        char_id = ""
        display_name = "キーパー"
    elif req.claim_char_id:
        # 既存人間スロットを引き継ぐ
        human_ids = set(sess.get("human_char_ids", []))
        claimed = {v for v in sess.get("players", {}).values() if v}
        if req.claim_char_id not in sess.get("initiative", []):
            raise HTTPException(400, "Character not in initiative")
        if req.claim_char_id not in human_ids:
            raise HTTPException(400, "Character is not a human slot")
        if req.claim_char_id in claimed:
            raise HTTPException(409, "Slot already taken")
        # 招待コードのレーティング上限とキャラクター自身の申告レーティングを照合する
        # （マルチプレイ設計書§3.2の期待挙動: R18キャラはSFWセッションで拒否）。
        _claim_char = get_character(req.claim_char_id, load_profiles())
        if character_rating_exceeds_invite(_claim_char.get("content_policy", {}), session_rating):
            raise HTTPException(400, "This character's rating exceeds the invite code's rating")
        role = "player"
        char_id = req.claim_char_id
        display_name = sess.get("name_map", {}).get(char_id, char_id)
    elif req.character_json:
        # オンラインセッション: 参加者がキャラJSONを持ち込む
        # T2I生成（アイコン+立ち絵、2回/回）を伴うため連打をレート制限する（8.11対策）。
        # _check_invite_rateは招待コード「失敗」時のみカウントするため、正しい招待コードでの
        # 参加成功には何のブレーキも無く、_generate_visitor_imagesを連打できてしまっていた。
        if not _check_generation_rate(session_id, f"ip:{client_ip}", limit=5):
            raise HTTPException(429, "Too many join requests from this network. Please wait a moment.")

        # 投票expelで追放されたキャラと同一character_jsonでの再参加を拒否する（8.21対策）
        if _character_json_fingerprint(req.character_json) in sess.get("expelled_char_fingerprints", []):
            raise HTTPException(403, "This character has been removed from the session")

        role = "player"
        char_id = f"guest_{_uuid_mod.uuid4().hex[:8]}"

        # 招待コードのレーティング上限とキャラクター自身の申告レーティングを照合する
        # （マルチプレイ設計書§3.2の期待挙動: R18キャラはSFWセッションで拒否）。
        # LLM審査より先に行う軽量・決定論的なチェックのため、審査のLLM呼び出しより前に置く。
        _brought_content_policy = _extract_content_policy_from_json(req.character_json)
        if character_rating_exceeds_invite(_brought_content_policy, session_rating):
            raise HTTPException(400, "This character's rating exceeds the invite code's rating")

        # LLM審査（jailbreak/プロンプトインジェクション対策、多層防御の1枚。fail-open）
        audit_result = audit_character_json(
            req.character_json, session_rating, sess.get("backend", DEFAULT_LLM_BACKEND)
        )
        if not audit_result.passed:
            _log.warning("join rejected by character audit: session=%s reason=%s", session_id, audit_result.reason)
            raise HTTPException(400, f"Character content rejected: {audit_result.reason}")
        if audit_result.fail_open:
            # 審査自体が実行できず通過扱いになったケース。ホストに可視化し、
            # 「気づけない自動回避」を防ぐ（S-4）。
            _log.warning(
                "character audit fail-open: session=%s char_id=%s reason=%s",
                session_id, char_id, audit_result.reason,
            )
            _game_event_bus.emit(session_id, "CHARACTER_AUDIT_SKIPPED", {
                "character_id": char_id,
                "reason": audit_result.reason,
            })

        char_data = dict(req.character_json)
        char_data["id"] = char_id
        char_data["player_type"] = "human"
        sess.setdefault("guest_chars", {})[char_id] = char_data
        # このキャラが参加を許された時点のレーティング上限を記録しておく。同一セッションが
        # レーティングの異なる複数の招待コードを発行できる仕様のため、セッション全体で
        # 一つの上限に決め打ちできない（3.2節参照）。セッション内T2I生成時にこの上限を
        # 再度参照する（_generate_session_image_impl参照）。guest_chars本体に混ぜて持たせると
        # _character_json_fingerprint（追放後の再参加ブロック判定）の計算対象に混入してしまう
        # ため（id/player_typeしか除外していない）、別辞書として持つ。
        sess.setdefault("guest_char_ratings", {})[char_id] = session_rating
        _autosave_visitors(sess)
        # アイコン・立ち絵をバックグラウンドで生成（参加処理はこれを待たない。fail-silent）
        threading.Thread(
            target=_generate_visitor_images,
            args=(session_id, char_id, req.character_json),
            daemon=True,
        ).start()
        # DEFキャラJSON形式: {version: {base_profile: {name: ...}}} または フラット {name: ...}
        _cj = req.character_json
        display_name = _cj.get("name") or next(
            (v["base_profile"]["name"] for v in _cj.values()
             if isinstance(v, dict) and isinstance(v.get("base_profile"), dict) and v["base_profile"].get("name")),
            "Guest"
        )
        # イニシアティブと名前マップに追加（オンラインセッションで参加者が埋めていく）
        if char_id not in sess["initiative"]:
            sess["initiative"].append(char_id)
        sess["name_map"][char_id] = display_name

    player_token = issue_player_jwt(session_id, role, char_id)
    sess["players"][player_token] = char_id
    if role == "player" and char_id and char_id not in sess.get("human_char_ids", []):
        sess.setdefault("human_char_ids", []).append(char_id)
    if role == "gm":
        sess["invited_gm_token"] = player_token
    # オンラインセッションは使い回しを許可（複数参加者が同じコードを使う）
    if not sess.get("online_mode"):
        invite_info["used"] = True

    import uuid as _uuid_join
    participant_id = char_id if char_id else f"_{role}_{_uuid_join.uuid4().hex[:8]}"
    pinfo = {
        "character_id": char_id,
        "participant_id": participant_id,
        "display_name": display_name,
        "role": role,
        "claimed_char_id": char_id if req.claim_char_id else "",
    }
    sess.setdefault("joined_participants", []).append(pinfo)
    # token → participant_id の逆引き（サーバー内部限定。joined_participants はそのまま
    # クライアントに配信されるため token をそこに含めてはいけない）
    sess.setdefault("token_to_participant", {})[player_token] = participant_id
    _game_event_bus.emit(session_id, "PLAYER_JOINED", pinfo)

    return {
        "player_token": player_token,
        "session_id": session_id,
        "character_id": char_id,
        "display_name": display_name,
        "session_rating": session_rating,
        "role": role,
        "lobby_active": sess.get("lobby_active", False),
    }


@router.post("/{session_id}/leave")
async def leave_session(session_id: str, authorization: str = Header(...)):
    """非ホスト参加者(player/gm/observer)の明示的退室。

    参加者データを除去し PLAYER_LEFT を全タブに配信する。切断（通信途絶）とは区別し、
    タイムアウトによる自動スキップの対象にはしない（設計書 §3.7 参照）。
    """
    token = authorization.removeprefix("Bearer ").strip()

    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")

    # 冪等化: 連打や再送で同じトークンが二重に処理されても一度しか除去・emitしない。
    # revoke_token() 済みトークンでの再送も verify_jwt の 401 より先にここで拾う。
    if token not in sess.get("players", {}):
        return {"status": "already_left"}

    try:
        payload = verify_jwt(token)
    except _JWTError:
        raise HTTPException(401, "Invalid or expired token")
    if payload.get("session_id") != session_id:
        raise HTTPException(403, "Token session mismatch")
    if payload.get("role") == "host":
        raise HTTPException(400, "Host cannot leave a session it owns; use /end instead")

    char_id = sess["players"].pop(token, "")
    if char_id:
        _cancel_disconnect_skip(session_id, char_id)
    participant_id = sess.get("token_to_participant", {}).pop(token, char_id or None)
    if payload.get("role") == "gm" and sess.get("invited_gm_token") == token:
        sess["invited_gm_token"] = None
    sess["joined_participants"] = [
        p for p in sess.get("joined_participants", [])
        if p.get("participant_id") != participant_id
    ]
    ws = sess.get("ws_connections", {}).pop(token, None)
    _ws_send_locks.pop(token, None)
    if ws:
        try:
            await ws.close(code=1000)
        except Exception:
            pass
    revoke_token(token)

    _game_event_bus.emit(session_id, "PLAYER_LEFT", {
        "participant_id": participant_id,
        "character_id": char_id,
    })
    return {"status": "ok"}


class AiTakeoverRequest(BaseModel):
    character_id: str


@router.post("/{session_id}/ai_takeover")
def ai_takeover(session_id: str, req: AiTakeoverRequest, auth: dict = Depends(require_host)):
    """退室したプレイヤーのキャラ枠を AI に引き継ぐ（ホストのみ）。"""
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    if req.character_id not in sess.get("initiative", []):
        raise HTTPException(404, "Character not in session")
    human_ids: list = sess.setdefault("human_char_ids", [])
    if req.character_id not in human_ids:
        raise HTTPException(409, "Character is already AI-controlled")
    human_ids.remove(req.character_id)
    return {"status": "ok", "character_id": req.character_id, "human_char_ids": human_ids}


def next_turn(req: SessionNextRequest):
    """AIターンを1回進める内部ロジック。以前は`POST /api/session/next`として無認証で
    公開されており、session_idさえ分かればkeeper権限を経ずにLLM呼び出しを無制限に
    実行できてしまっていた（8.8参照）。フロントからは未使用だったためエンドポイントは
    廃止したが、`_execute_ai_turn`が内部関数として直接呼び出すためこの関数自体は残す。
    """
    session = _sessions.get(req.session_id)
    if not session:
        return {"error": "Session not found"}

    initiative = session["initiative"]
    turn = session["turn"]
    _skip_gen_before = session.get("_skip_gen", 0)  # keeper_skip 競合検出用
    if turn >= len(initiative):
        session["round"] += 1
        session["turn"] = 0
        turn = 0

    # 指名があれば優先
    designated = session.pop("designated_next", None)
    if designated and designated in initiative:
        return_turn = session.pop("designated_return_turn", None)
        if return_turn is not None:
            session["_designated_return_turn"] = return_turn
        turn = initiative.index(designated)
        session["turn"] = turn
        session["action_count"] = 0

    current_char_id = initiative[turn]
    name_map = session["name_map"]

    # 発言力がマイナスなら自動スキップ
    counters = session.setdefault("counters", {})
    _ctr_now = counters.get(current_char_id, 0)
    _log.info("[counter] %s = %d (Round %d)", name_map.get(current_char_id, current_char_id), _ctr_now, session["round"])
    if _ctr_now < 0:
        counters[current_char_id] = _ctr_now + 1
        session["turn"] = turn + 1
        session["action_count"] = 0
        _autosave(req.session_id)
        _log.info("[forced_skip] %s: %d → %d", name_map.get(current_char_id, current_char_id), _ctr_now, _ctr_now + 1)
        return {
            "skipped": True,
            "counter_before": _ctr_now,
            "character_id": current_char_id,
            "character_name": name_map.get(current_char_id, current_char_id),
            "round": session["round"],
            "counters": dict(counters),
        }

    profiles = load_profiles()
    char = get_character(current_char_id, profiles)

    # 人間プレイヤーのターンは LLM を呼ばず入力待ちを返す
    if _is_human_char(session, current_char_id, profiles):
        return {
            "waiting_for_human": True,
            "character_id": current_char_id,
            "character_name": name_map.get(current_char_id, current_char_id),
            "round": session["round"],
            "counters": dict(counters),
        }

    char_backends = session.get("char_backends", {})
    backend_id = char_backends.get(current_char_id) or req.backend or session.get("backend", DEFAULT_LLM_BACKEND)
    if backend_id not in LLM_BACKENDS:
        backend_id = DEFAULT_LLM_BACKEND
    model = _resolve_model(backend_id, req.model)

    # performative系（漫才・落語等）は「直近のネタ/演目」に集中させたいのと、履歴が
    # 育つほど応答が長文化していく傾向を抑えるため、discussion系より短い窓に絞る
    # （2026-08-10）。
    _history_window = 8 if session.get("style") == "performative" else 20
    history = []
    for h in session["history"][-_history_window:]:
        raw_content = h["content"]
        h_role = h.get("role", "user")
        h_char_id = h.get("character_id")
        if h_role == "assistant" and h_char_id:
            # "Name: text" → strip prefix
            text = raw_content.split(": ", 1)[-1] if ": " in raw_content else raw_content
            if h_char_id == current_char_id:
                history.append({"role": "assistant", "content": text})
            else:
                other_name = name_map.get(h_char_id, h_char_id)
                history.append({"role": "user", "content": f"[{other_name}] {text}"})
        else:
            history.append({"role": h_role, "content": raw_content})

    _settings = load_settings()
    _user_lang = _settings.get("user_language", "ja") or "ja"
    _allowed_sexual = _settings.get("allowed_rating_sexual", ["general"])
    _allowed_violence = _settings.get("allowed_rating_violence", ["general"])

    rules = session.get("rules", [])
    speaker_name = name_map.get(current_char_id, current_char_id)
    topic = session.get("topic", "")
    action_count = session.get("action_count", 0)
    other_names = [name_map.get(c, c) for c in initiative if name_map.get(c, c) != speaker_name]

    # --- 挿入点①: TRPGモード Round>=2 の AI 行動選択 ---
    _ai_action: dict = {"action": "none"}
    _designated_target_name = ""
    if session.get("trpg_mode") and session["round"] >= 2:
        _ai_action = _ai_action_select(
            backend_id, model, char,
            current_char_id,
            counters.get(current_char_id, 0),
            session["round"], session["history"],
            initiative, name_map, speaker_name, _user_lang,
        )
        _log.info("[action] %s chose: %s", speaker_name, _ai_action.get("action"))

    if _ai_action["action"] == "skip":
        _ctr_before_skip = counters.get(current_char_id, 0)
        counters[current_char_id] = _ctr_before_skip + 1
        session["turn"] = turn + 1
        session["action_count"] = 0
        _autosave(req.session_id)
        return {
            "skipped": True,
            "voluntary": True,
            "counter_before": _ctr_before_skip,
            "character_id": current_char_id,
            "character_name": name_map.get(current_char_id, current_char_id),
            "round": session["round"],
            "counters": dict(counters),
        }

    if _ai_action["action"] == "vote":
        _cur = counters.get(current_char_id, 0)
        if _cur >= 3:
            counters[current_char_id] = 0
            _autosave(req.session_id)
            return {
                "action": "vote_proposal",
                "character_id": current_char_id,
                "character_name": name_map.get(current_char_id, current_char_id),
                "vote_type": _ai_action.get("vote_type", "topic_change"),
                "vote_detail": _ai_action.get("vote_detail", ""),
                "proposer_text": _ai_action.get("reason", ""),
                "round": session["round"],
                "counters": dict(counters),
            }
        else:
            _ai_action["action"] = "none"

    if _ai_action["action"] == "designate":
        _target_name = _ai_action.get("target_name", "")
        _target_id = next((c for c in initiative if name_map.get(c, c) == _target_name), None)
        _cur = counters.get(current_char_id, 0)
        if _target_id and _target_id != current_char_id and _cur >= 1:
            counters[current_char_id] = _cur - 1
            session["designated_next"] = _target_id
            _designated_target_name = _target_name
        else:
            _ai_action["action"] = "none"

    if _ai_action["action"] == "extend":
        _cur = counters.get(current_char_id, 0)
        if _cur >= 1:
            counters[current_char_id] = _cur - 1
        else:
            _ai_action["action"] = "none"

    directive_set_id = session.get("action_directive_set", "default")
    _directives = _load_action_directives().get(directive_set_id, {}).get("directives", {})

    _trpg_ctx = ""
    _scenario = None
    if session.get("trpg_mode"):
        _rulebook = _load_trpg_rulebook(session.get("trpg_rulebook", ""))
        _scenario = _load_trpg_scenario(session.get("trpg_scenario", ""))
        _trpg_ctx = _build_for_player(
            current_char_id, char, _rulebook, _scenario or None, session, _user_lang
        )

    effective_topic = (
        _scenario.get("title", topic) if session.get("trpg_mode") and _scenario else topic
    )
    session_ctx = _build_session_context(
        effective_topic, rules, initiative, name_map, speaker_name, _user_lang,
        trpg_context=_trpg_ctx,
    )

    # 同基底衝突処理: 同一 base_entity_id を持つキャラが複数参加している場合にアンカー文注入
    _base_entity_groups: dict[str, list[tuple[str, str]]] = {}
    for _cid in initiative:
        _c = get_character(_cid, profiles)
        if not _c:
            continue
        _beid = _c.get("base_entity_id")
        if not _beid:
            continue
        _cname = name_map.get(_cid, _cid)
        _core = (_c.get("character_constitution") or {}).get("core", "")
        _base_entity_groups.setdefault(_beid, []).append((_cname, _core))
    for _beid, _group in _base_entity_groups.items():
        if len(_group) < 2:
            continue
        if _user_lang == "ja":
            _anchor_lines = "\n".join(
                f"- {_n}：{_k}" if _k else f"- {_n}"
                for _n, _k in _group
            )
            session_ctx += (
                f"\n\n【重要：共通表現参照キャラクター】"
                f"以下のキャラクターは共通の表現参照（{_beid}）を持ちますが、"
                "それぞれ完全に独立したアイデンティティを持ちます。"
                "互いの人格・価値観・口調を混同・継承してはなりません。\n"
                f"{_anchor_lines}"
            )
        else:
            _anchor_lines = "\n".join(
                f"- {_n}: {_k}" if _k else f"- {_n}"
                for _n, _k in _group
            )
            session_ctx += (
                f"\n\n[IMPORTANT: Shared Expression Reference] "
                f"The following characters share a common expression reference ({_beid}), "
                "but are completely independent identities. "
                "They must NOT inherit or borrow personality, values, or speech patterns from each other.\n"
                f"{_anchor_lines}"
            )

    # 死者視点：runtime_statsでステータスが0になっているキャラは死者として発言させる
    _runtime_stats = session.get("runtime_stats", {}).get(current_char_id, {})
    _is_dead = bool(_runtime_stats) and any(v <= 0 for v in _runtime_stats.values())
    if _is_dead:
        if _user_lang == "ja":
            session_ctx += (
                "\n\n【重要：死者視点】"
                f"あなた（{speaker_name}）はこのセッションで死亡しています。"
                "肉体はなく、霊・残留思念・記憶の断片として存在しています。"
                "生存者に直接触れることはできませんが、その場の空気・気配・走馬灯として存在感を示してください。"
                "必ず死者の視点から発言し、自分が死んでいることを自覚した言動を取ること。"
            )
        else:
            session_ctx += (
                "\n\n[IMPORTANT: Dead Character Perspective]"
                f"You ({speaker_name}) have died in this session."
                "You exist as a spirit, lingering memory, or echo of your past self."
                "You cannot physically interact with survivors, but you may manifest as atmosphere, sensation, or ghostly whisper."
                "Always speak from the perspective of the dead, fully aware that you have died."
            )

    user_text = _build_turn_instruction(
        action_count, speaker_name, other_names, effective_topic,
        session["history"], current_char_id, session, _directives, _user_lang,
    )

    prev_emotion = next(
        (h.get("emotion", "neutral") for h in reversed(session["history"])
         if h.get("character_id") == current_char_id),
        "neutral",
    )
    if isinstance(prev_emotion, list):
        prev_emotion = ", ".join(prev_emotion)

    global _last_session_debug
    from def_kari.resources.vram_lock import get_vram_lock
    _vram_lock = get_vram_lock()
    if not _vram_lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
        err = f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s"
        _last_session_debug = {"error": err, "success": False, "attempts": [], "character_id": current_char_id, "backend": backend_id, "topic": topic, "round": session["round"], "user_text": user_text}
        return {"error": err, "character_id": current_char_id, "character_name": name_map.get(current_char_id, current_char_id), "text": f"(error: {err})", "emotion": "neutral", "round": session["round"], "turn": turn + 1, "counters": dict(session.get("counters", {}))}
    try:
        _narrate_kwargs = dict(
            character=char,
            user_text=user_text,
            history=history,
            model=model,
            backend=backend_id,
            session_context=session_ctx,
            allowed_sexual=_allowed_sexual,
            allowed_violence=_allowed_violence,
            current_emotion=prev_emotion,
            char_id=current_char_id,
        )
        result = _player_agent.narrate(**_narrate_kwargs)
        if not result.get("success"):
            import time as _time
            _time.sleep(1)
            result = _player_agent.narrate(**_narrate_kwargs)
    except Exception as e:
        _last_session_debug = {"error": str(e), "success": False, "attempts": [], "character_id": current_char_id, "backend": backend_id, "topic": topic, "round": session["round"], "user_text": user_text}
        return {"error": str(e), "character_id": current_char_id, "character_name": name_map.get(current_char_id, current_char_id), "text": f"(error: {e})", "emotion": "neutral", "round": session["round"], "turn": turn + 1, "counters": dict(session.get("counters", {}))}
    finally:
        _vram_lock.release()

    text = ""
    emotion = "neutral"
    tags: list[str] = []
    image_prompt_en = ""
    if result.get("success") and result.get("result"):
        parsed = result["result"]
        text = parsed.get("dialogue", "")
        if _is_dead and text:
            text = f"『行動不能』{text}"
        emotion = parsed.get("emotion", "neutral")
        raw_tags = parsed.get("tags", [])
        tags = raw_tags if isinstance(raw_tags, list) else []
        image_prompt_en = parsed.get("image_prompt_en", "")
        image_prompt_en = apply_emotion_tags(image_prompt_en, emotion)
        _last_session_debug = {
            "success": True,
            "character_id": current_char_id,
            "character_name": name_map.get(current_char_id, current_char_id),
            "backend": backend_id,
            "topic": topic,
            "round": session["round"],
            "text": text,
            "emotion": emotion,
            "tags": tags,
            "image_prompt_en": image_prompt_en,
            "raw": result.get("attempts", [{}])[-1].get("raw", "") if result.get("attempts") else "",
            "attempts": result.get("attempts", []),
            "user_text": user_text,
        }
    else:
        attempts = result.get("attempts", [])
        errors = "; ".join(e for a in attempts for e in a.get("errors", []))
        text = f"(generation failed: {errors})" if errors else "(generation failed)"
        _last_session_debug = {
            "success": False,
            "character_id": current_char_id,
            "character_name": name_map.get(current_char_id, current_char_id),
            "backend": backend_id,
            "topic": topic,
            "round": session["round"],
            "raw": attempts[-1]["raw"] if attempts else "",
            "attempts": attempts,
            "user_text": user_text,
        }

    session["history"].append({
        "role": "assistant",
        "content": f"{name_map.get(current_char_id, current_char_id)}: {text}",
        "character_id": current_char_id,
        "emotion": emotion,
        "tags": tags,
    })

    # A6 リピートペナルティ
    from def_kari.settings import load_settings as _load_settings
    _s = _load_settings()
    _repeat_threshold = int(_s.get("session_repeat_penalty_count", 3))
    _lang = _s.get("user_language", "ja")
    _char_contents = []
    penalty_message = ""
    if _repeat_threshold > 0:
        _char_contents = [
            h["content"] for h in session["history"]
            if h.get("character_id") == current_char_id and h.get("role") == "assistant"
        ][-_repeat_threshold:]
    if _char_contents and len(_char_contents) >= _repeat_threshold and len(set(_char_contents)) == 1:
            counters[current_char_id] = counters.get(current_char_id, 0) - 1
            _char_label = name_map.get(current_char_id, current_char_id)
            penalty_message = (
                f"⚠ {_char_label} repeated the same message {_repeat_threshold} times [speech power -1]"
                if _lang == "en" else
                f"⚠ {_char_label} が同一発言を{_repeat_threshold}回繰り返した [発言力-1]"
            )

    actions_per_turn = session.get("actions_per_turn", 2)
    action_count = session.get("action_count", 0) + 1
    if action_count >= actions_per_turn:
        return_turn = session.pop("_designated_return_turn", None)
        if return_turn is not None:
            next_t = return_turn % len(initiative) if initiative else 0
        else:
            next_t = turn + 1
        # LLM 実行中に keeper_skip が入った場合は turn を上書きしない
        if session.get("_skip_gen", 0) == _skip_gen_before:
            session["turn"] = next_t
        session["action_count"] = 0
    else:
        session["action_count"] = action_count

    _autosave(req.session_id)
    _char_name = name_map.get(current_char_id, current_char_id)
    _log.info("[next] Round %d | Turn %d | %s (%s) | %d chars | action=%s",
              session["round"], turn + 1, _char_name, backend_id, len(text), _ai_action.get("action", "none"))
    return {
        "character_id": current_char_id,
        "character_name": _char_name,
        "text": text,
        "emotion": emotion,
        "tags": tags,
        "image_prompt_en": image_prompt_en,
        "round": session["round"],
        "turn": turn + 1,
        "counters": dict(counters),
        "penalty_message": penalty_message,
        "ai_action": _ai_action.get("action", "none"),
        "designated_name": _designated_target_name or None,
    }


@router.post("/{session_id}/retake")
def retake_turn(session_id: str, _auth: dict = Depends(require_keeper)):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    action_count = session.get("action_count", 0)
    actions_per_turn = session.get("actions_per_turn", 2)
    turn = session.get("turn", 0)
    history = session.get("history", [])

    if action_count > 0:
        # 現キャラが途中まで発言済み → その分を巻き戻す
        remove = action_count
        session["action_count"] = 0
    else:
        # 直前のキャラのターンが完了してしまっている → 1つ前のキャラに戻る
        if turn == 0 and session.get("round", 1) <= 1:
            return {"error": "Cannot retake: at the beginning"}
        if turn == 0:
            session["round"] -= 1
            session["turn"] = len(session["initiative"])
            turn = session["turn"]
        session["turn"] = turn - 1
        remove = actions_per_turn
        session["action_count"] = 0

    session["history"], removed = _clean_history_for_retake(history, remove)

    # 巻き戻し後にai_taskを再起動（WS経由でフロントに通知される）
    ai_task = session.get("ai_task")
    if not ai_task or ai_task.done():
        session["ai_task"] = asyncio.create_task(_run_ai_turns(session_id))

    _autosave(session_id)
    return {"removed": removed}


@router.post("/{session_id}/ai_resume")
async def ai_resume(session_id: str, _auth: dict = Depends(require_keeper)):
    """ai_task が停止している時に再起動する（retake・keeper・判定後など）。"""
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    if sess.get("lobby_active"):
        return {"status": "lobby"}
    sess["ai_paused"] = False
    ai_task = sess.get("ai_task")
    if not ai_task or ai_task.done():
        sess["ai_task"] = asyncio.create_task(_run_ai_turns(session_id))
    return {"status": "ok"}


@router.post("/{session_id}/ai_pause")
async def ai_pause(session_id: str, _auth: dict = Depends(require_keeper)):
    """自動進行を一時停止する（現在生成中のターンが完了してから止まる）。"""
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    sess["ai_paused"] = True
    return {"status": "ok"}


@router.post("/{session_id}/circuit_breaker/reset")
def reset_circuit_breaker(session_id: str, auth: dict = Depends(require_host)):
    """9.3 Layer 3: サーキットブレーカーが作動したセッションを、ホストの明示的な操作で
    再開する（`_check_circuit_breaker`参照）。作動中は誰が操作しているか分からない
    異常な連打の最中である可能性があるため、ホストが監査ログ（`data/private/logs/audit.log`）
    を確認した上で意図的に解除する運用を前提とする。keeperではなくhostのみに限定。
    """
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    sess["circuit_broken"] = False
    _reset_audit_violations(session_id)
    return {"status": "ok"}


class AutoAdvanceRequest(BaseModel):
    enabled: bool


@router.patch("/{session_id}/auto_advance")
async def set_auto_advance(session_id: str, req: AutoAdvanceRequest, _auth: dict = Depends(require_keeper)):
    """自動進行モードをセッション状態として切り替え、AUTO_ADVANCE_CHANGED を全参加者に配信する。

    進行権限は常に一人: 人間キーパー（gm）参加中はgmのみ、AIキーパー構成では
    ホストのみ（プレイヤー参加・観戦中でもJWTロールは host のまま通る）。
    プレイヤー/観戦者タブは受信して表示を同期するだけで進行の駆動には関与しない。
    """
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    # 人間キーパー（gm）参加中は進行権限をgmに一本化し、ホストの切替は拒否する
    if _auth.get("role") == "host" and sess.get("invited_gm_token"):
        raise HTTPException(403, "Auto advance is controlled by the joined keeper")
    sess["auto_advance"] = req.enabled
    _game_event_bus.emit(session_id, "AUTO_ADVANCE_CHANGED", {"enabled": req.enabled})
    if req.enabled:
        sess["ai_paused"] = False
        if not sess.get("lobby_active"):
            # 現在が人間ターンの場合はタスクを起動しない（WAITING_FOR_HUMAN の
            # 再emitで入力欄が再オープンされ、スキップ送信と競合するのを防ぐ）
            current = _get_current_speaker(sess)
            if current and not _is_human_char(sess, current):
                ai_task = sess.get("ai_task")
                if not ai_task or ai_task.done():
                    sess["ai_task"] = asyncio.create_task(_run_ai_turns(session_id))
    else:
        sess["ai_paused"] = True
    return {"auto_advance": req.enabled}


@router.post("/{session_id}/end")
async def end_session_by_host(session_id: str, auth: dict = Depends(require_host)):
    """ホストがセッションを明示的に終了する。参加者全員に SESSION_ENDED を通知してから後片付けする。"""
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    # 冪等化: _end_session の猶予期間中に /end が再度呼ばれても後片付けを繰り返さない
    # （SESSION_ENDED ブロードキャストを受けたクライアントが /end を再POSTするループで
    # episodic memory が同一セッション分だけ多重書き込みされるのを防ぐ）
    if sess.get("_ending"):
        return {"status": "ending"}
    sess["_ending"] = True
    from def_kari.gm.events import game_event_bus, SESSION_ENDED
    game_event_bus.emit(session_id, SESSION_ENDED, {})
    _save_session_episodic(session_id, sess)
    _delete_autosave(session_id)
    game_event_bus.clear_log(session_id)
    # ブロードキャストタスクが WS 送信を完了してから接続を閉じる
    await asyncio.sleep(0.3)
    asyncio.create_task(_end_session(session_id))
    return {"status": "ok"}


class LobbyConfigRequest(BaseModel):
    max_players: int = 0       # 0 = 無制限
    host_char_id: str = ""     # ホストがプレイヤー参加する場合のキャラID


@router.patch("/{session_id}/host_role")
def update_host_role(session_id: str, is_keeper: bool, auth: dict = Depends(require_host)):
    """ロビー中にホストの役割（キーパー専任 or プレイヤー）をリアルタイム更新する。"""
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    sess["host_keeper_mode"] = is_keeper
    return {"ok": True, "host_keeper_mode": is_keeper}


@router.post("/{session_id}/lobby_config")
def set_lobby_config(session_id: str, req: LobbyConfigRequest, auth: dict = Depends(require_host)):
    """ロビー設定を更新する（最大プレイヤー数・ホストキャラ）。セッション開始前にホストが呼ぶ。"""
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    sess["max_players"] = req.max_players
    # host_keeper_mode は update_host_role で設定済み。キャラがある場合だけ上書き（プレイヤー参加確定）。
    if req.host_char_id:
        sess["host_keeper_mode"] = False
    # ホストキャラをイニシアティブに追加（プレイヤー参加時）
    if req.host_char_id and req.host_char_id not in sess["initiative"]:
        profiles = load_profiles()
        char = get_character(req.host_char_id, profiles)
        if char:
            sess["initiative"].append(req.host_char_id)
            sess["name_map"][req.host_char_id] = char.get("name", req.host_char_id)
            if char.get("player_type") == "human":
                sess.setdefault("human_char_ids", []).append(req.host_char_id)
    # ロビー解除 → 参加者全員に通知
    sess["lobby_active"] = False
    from def_kari.gm.events import game_event_bus, SESSION_STARTED
    game_event_bus.emit(session_id, SESSION_STARTED, {
        "initiative": sess["initiative"],
        "name_map": sess.get("name_map", {}),
        "participants": sess.get("joined_participants", []),
    })
    # 最初のターンが人間なら WAITING_FOR_HUMAN を即時通知（_run_ai_turns を経由しないため）
    _first = _get_current_speaker(sess)
    if _first and _is_human_char(sess, _first):
        _game_event_bus.emit(session_id, "WAITING_FOR_HUMAN", {
            "character_id": _first,
            "character_name": sess.get("name_map", {}).get(_first, _first),
            "round": sess.get("round", 1),
            "counters": dict(sess.get("counters", {})),
        })
        _maybe_schedule_disconnect_skip(session_id, sess, _first)
    return {
        "status": "ok",
        "max_players": sess["max_players"],
        "initiative": sess["initiative"],
    }


class LobbyModeRequest(BaseModel):
    trpg_mode: bool


@router.patch("/{session_id}/lobby/mode")
def set_lobby_trpg_mode(session_id: str, req: LobbyModeRequest, auth: dict = Depends(require_host)):
    """ロビー中にセッションモード（通常/TRPG）を切り替える。"""
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    if not sess.get("lobby_active"):
        raise HTTPException(409, "Session already started")
    sess["trpg_mode"] = req.trpg_mode
    return {"trpg_mode": req.trpg_mode}


class LobbyKeeperSourceRequest(BaseModel):
    waiting_for_gm: bool


@router.patch("/{session_id}/lobby/keeper_source")
def set_lobby_keeper_source(session_id: str, req: LobbyKeeperSourceRequest, auth: dict = Depends(require_host)):
    """ロビー中にキーパー担当をAI自動進行か人間参加待ちかに切り替える。"""
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    if not sess.get("lobby_active"):
        raise HTTPException(409, "Session already started")
    sess["waiting_for_gm"] = req.waiting_for_gm
    return {"waiting_for_gm": req.waiting_for_gm}


class LobbySettingsRequest(BaseModel):
    topic: str | None = None
    rule_set: str | None = None
    trpg_rulebook: str | None = None
    trpg_scenario: str | None = None
    max_players: int | None = None


@router.patch("/{session_id}/lobby/settings")
def set_lobby_settings(session_id: str, req: LobbySettingsRequest, auth: dict = Depends(require_host)):
    """ロビー中にセッション設定（お題・ルールセット・ルールブック・シナリオ）を変更する。

    /start 時に確定する派生データ（rules/scene・skill_pool・npc_state）もここで再構築する。
    省略されたフィールドは変更しない。ロビー解除後は 409。
    """
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    if not sess.get("lobby_active"):
        raise HTTPException(409, "Session already started")
    if req.topic is not None:
        sess["topic"] = req.topic
    if req.rule_set is not None:
        sess["rule_set"] = req.rule_set
        _rule_data = _load_session_rules().get(req.rule_set, {})
        sess["rules"] = _rule_data.get("rules", [])
        sess["style"] = _rule_data.get("style", "discussion")
        sess["max_chars"] = _rule_data.get("max_chars", 0)
        sess["max_rounds"] = _rule_data.get("max_rounds", 0)
        sess["scene"] = _rule_data.get("scene", "")
    if req.trpg_rulebook is not None:
        sess["trpg_rulebook"] = req.trpg_rulebook
        _rb = _load_trpg_rulebook(req.trpg_rulebook) if req.trpg_rulebook else {}
        _pool = int(_rb.get("skill_point_pool", 0))
        # 開始前なので既存参加者の技能ポイントプールも新ルールブック値でリセットする
        sess["skill_pool"] = {cid: _pool for cid in sess.get("skill_pool", {})}
    if req.trpg_scenario is not None:
        sess["trpg_scenario"] = req.trpg_scenario
        sess["npc_state"] = _build_initial_npc_state(req.trpg_scenario)
    if req.max_players is not None:
        sess["max_players"] = max(1, min(8, req.max_players))
    return {
        "topic": sess.get("topic", ""),
        "rule_set": sess.get("rule_set", ""),
        "trpg_rulebook": sess.get("trpg_rulebook", ""),
        "trpg_scenario": sess.get("trpg_scenario", ""),
        "max_players": sess.get("max_players", 0),
    }


class LobbyAIRequest(BaseModel):
    character_id: str
    game_sheet_id: str = ""  # 任意。TRPGモードでプレイするゲームキャラ（キャラシート）を指定
    backend_id: str = ""  # 任意。未指定なら設定タブのデフォルトに従う


@router.post("/{session_id}/lobby/add_ai")
def lobby_add_ai(session_id: str, req: LobbyAIRequest, auth: dict = Depends(require_host)):
    """ロビーに AI キャラクターを追加する（ホストのみ）。"""
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    if not sess.get("lobby_active"):
        raise HTTPException(409, "Session already started")
    char_id = req.character_id
    if char_id in sess["initiative"]:
        raise HTTPException(409, "Already in initiative")
    if char_id and char_id == sess.get("keeper_char_id"):
        raise HTTPException(409, "Character already assigned to keeper")
    profiles = load_profiles()
    char = get_character(char_id, profiles)
    if not char:
        raise HTTPException(404, "Character not found")
    if char.get("player_type") == "human":
        raise HTTPException(400, "Cannot add human character as AI slot")
    sess["initiative"].append(char_id)
    sess["name_map"][char_id] = char.get("name", char_id)
    if req.game_sheet_id:
        sess.setdefault("char_game_sheets", {})[char_id] = req.game_sheet_id
    if req.backend_id:
        sess.setdefault("char_backends", {})[char_id] = req.backend_id
    _autosave(session_id)
    _game_event_bus.emit(session_id, "LOBBY_UPDATE", {
        "initiative": sess["initiative"],
        "name_map": dict(sess["name_map"]),
    })
    return {"status": "ok", "initiative": sess["initiative"], "name_map": dict(sess["name_map"])}


class LobbyKeeperCharRequest(BaseModel):
    character_id: str  # 空文字列 = 解除（無名AIキーパーに戻す）
    backend_id: str = ""  # 任意。未指定なら設定タブのデフォルトに従う


@router.post("/{session_id}/lobby/set_keeper_char")
def lobby_set_keeper_char(session_id: str, req: LobbyKeeperCharRequest, auth: dict = Depends(require_host)):
    """ロビー中にAIキーパー役のキャラクターを割り付ける/解除する（ホストのみ）。

    character_id が空文字列なら解除。解除しても無名AIキーパー（汎用「🎩 Keeper」表示）として
    自動進行は継続する（TRPGモードの ai_keeper_narrate 参照）。
    """
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    if not sess.get("lobby_active"):
        raise HTTPException(409, "Session already started")
    char_id = req.character_id
    if not char_id:
        sess["keeper_char_id"] = ""
        sess["keeper_char_name"] = ""
        _game_event_bus.emit(session_id, "LOBBY_UPDATE", {
            "keeper_char_id": "",
            "keeper_char_name": "",
        })
        return {"status": "ok", "keeper_char_id": "", "keeper_char_name": ""}
    if char_id in sess["initiative"]:
        raise HTTPException(409, "Character already assigned to a player slot")
    profiles = load_profiles()
    char = get_character(char_id, profiles)
    if not char:
        raise HTTPException(404, "Character not found")
    if char.get("player_type") == "human":
        raise HTTPException(400, "Cannot assign human character as AI keeper")
    sess["keeper_char_id"] = char_id
    sess["keeper_char_name"] = char.get("name", char_id)
    if req.backend_id:
        sess.setdefault("char_backends", {})[char_id] = req.backend_id
    _autosave(session_id)
    _game_event_bus.emit(session_id, "LOBBY_UPDATE", {
        "keeper_char_id": char_id,
        "keeper_char_name": sess["keeper_char_name"],
    })
    return {"status": "ok", "keeper_char_id": char_id, "keeper_char_name": sess["keeper_char_name"]}


@router.post("/{session_id}/lobby/remove_ai")
def lobby_remove_ai(session_id: str, req: LobbyAIRequest, auth: dict = Depends(require_host)):
    """ロビーから AI キャラクターを削除する（ホストのみ）。"""
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    if not sess.get("lobby_active"):
        raise HTTPException(409, "Session already started")
    char_id = req.character_id
    if char_id in sess.get("human_char_ids", []) or char_id in sess.get("guest_chars", {}):
        raise HTTPException(400, "Cannot remove human player character")
    if char_id in sess["initiative"]:
        sess["initiative"].remove(char_id)
        sess["name_map"].pop(char_id, None)
        _autosave(session_id)
    _game_event_bus.emit(session_id, "LOBBY_UPDATE", {
        "initiative": sess["initiative"],
        "name_map": dict(sess["name_map"]),
    })
    return {"status": "ok", "initiative": sess["initiative"], "name_map": dict(sess["name_map"])}


@router.post("/{session_id}/keeper")
def inject_keeper_message(session_id: str, req: KeeperMessageRequest, _auth: dict = Depends(require_keeper)):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    content = f"[GM] {req.text}"
    session["history"].append({
        "role": "user",
        "content": content,
        "character_id": "_keeper",
    })
    _autosave(session_id)
    _game_event_bus.emit(session_id, "HUMAN_ACTION", {
        "character_id": "_keeper",
        "character_name": "🎩 Keeper",
        "text": req.text,
        "action": "keeper",
        "sender_role": _auth.get("role", "host"),
    })
    return {"status": "ok"}


class AIKeeperRequest(BaseModel):
    backend: str = DEFAULT_LLM_BACKEND
    inject_history: bool = True


@router.post("/{session_id}/ai_keeper")
def ai_keeper_narrate(session_id: str, req: AIKeeperRequest, _auth: dict = Depends(require_player)):
    """AIキーパー（無個性モード）: シナリオ・ルールブック・履歴からGM発言を生成する。"""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    if not session.get("trpg_mode"):
        return {"error": "Not in TRPG mode"}
    if session.get("human_keeper"):
        return {"error": "Human keeper mode: use POST /keeper endpoint instead"}

    _keeper_char_id = session.get("keeper_char_id", "")
    _char_backends_map = session.get("char_backends", {})
    _effective_backend = (
        _char_backends_map.get(_keeper_char_id) or req.backend or DEFAULT_LLM_BACKEND
        if _keeper_char_id
        else req.backend or DEFAULT_LLM_BACKEND
    )

    from def_kari.resources.vram_lock import get_vram_lock as _get_vram_lock
    _keeper_lock = _get_vram_lock()
    if not _keeper_lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
        return {"error": f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s"}
    try:
        result = _gm_agent.narrate(
            session=session,
            backend_id=_effective_backend,
            inject_history=req.inject_history,
            session_id=session_id,
        )
    finally:
        _keeper_lock.release()
    if result.get("error"):
        _log.error("[keeper] error: %s", result["error"])
        return {"error": result["error"]}
    _judgments = result.get("judgments", [])
    _log.info("[keeper] Round %d | %d chars | %d judgments | text: %.60s",
              session.get("round", 0), len(result["text"]), len(_judgments),
              result["text"].replace("\n", " "))
    if _judgments:
        for _j in _judgments:
            _log.info("[keeper]   judgment: %s → %s", _j.get("character_name", "?"), _j.get("stat", "?"))
    if req.inject_history and result["text"]:
        _autosave(session_id)

    # シーン自動進行判定
    _scene_advanced_info = None
    _should_advance = result.get("advance_scene", False)
    if not _should_advance:
        # フォールバック: scene_round >= recommended_rounds * 1.5
        _scenario = _load_trpg_scenario(session.get("trpg_scenario", ""))
        _scenes = _scenario.get("scenes", [])
        _cur_idx = session.get("current_scene_index", 0)
        if _cur_idx < len(_scenes) - 1:
            _rec = (_scenes[_cur_idx] if _cur_idx < len(_scenes) else {}).get("recommended_rounds")
            if _rec:
                _scene_rounds = session.get("round", 0) - session.get("scene_round_start", 0)
                if _scene_rounds >= _rec * 1.5:
                    _should_advance = True
    if _should_advance:
        _scene_advanced_info = advance_scene(session_id)
        if _scene_advanced_info.get("error"):
            _scene_advanced_info = None

    _keeper_display = session.get("keeper_char_name", "")
    resp: dict = {
        "text": result["text"],
        "character_id": "_keeper",
        "character_name": f"🎩 {_keeper_display}" if _keeper_display else "🎩 Keeper",
        "judgments": result["judgments"],
    }
    if _scene_advanced_info:
        resp["scene_advanced"] = True
        resp["new_scene_index"] = _scene_advanced_info.get("current_scene_index")
        resp["new_scene_id"] = _scene_advanced_info.get("scene_id", "")
        resp["new_scene_title"] = _scene_advanced_info.get("scene_title", "")
        resp["new_chapter_id"] = _scene_advanced_info.get("chapter_id")
        resp["new_chapter_title"] = _scene_advanced_info.get("chapter_title")
    if result.get("propose_end"):
        resp["propose_end"] = True
    return resp


@router.post("/{session_id}/skip")
async def skip_turn(session_id: str, _auth: dict = Depends(require_keeper)):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    initiative = session["initiative"]
    turn = session["turn"]
    if turn >= len(initiative):
        session["round"] += 1
        session["turn"] = 0
        turn = 0
    char_id = initiative[turn]
    char_name = session["name_map"].get(char_id, char_id)
    counters = session.setdefault("counters", {})
    counters[char_id] = counters.get(char_id, 0) + 1
    # _skip_gen を先にインクリメント → next_turn の turn 書き戻しを防止
    session["_skip_gen"] = session.get("_skip_gen", 0) + 1
    session["turn"] = turn + 1
    session["action_count"] = 0
    if session["turn"] >= len(initiative):
        session["round"] += 1
        session["turn"] = 0
    _autosave(session_id)
    _game_event_bus.emit(session_id, "HUMAN_ACTION", {
        "character_id": char_id,
        "character_name": char_name,
        "text": "",
        "action": "keeper_skip",
        "sender_role": _auth.get("role", "host"),
        "counters": dict(counters),
    })
    # 実行中の ai_task をキャンセルしてスキップ位置から再起動
    _ai_task = session.get("ai_task")
    if _ai_task and not _ai_task.done():
        _ai_task.cancel()
    session["ai_task"] = asyncio.create_task(_run_ai_turns(session_id))
    return {
        "character_id": char_id,
        "character_name": char_name,
        "round": session["round"],
        "counters": dict(counters),
    }


class SessionDiceRollRequest(BaseModel):
    notation: str
    skill_value: int = 0
    rulebook_id: str = ""
    character_id: str = ""
    stat_name: str = ""
    is_skill: bool = False
    is_stat: bool = False


@router.post("/{session_id}/dice")
def session_dice_roll(session_id: str, req: SessionDiceRollRequest, _auth: dict = Depends(require_player)):
    """TRPGモードのダイス判定（require_player）。セッション履歴への注入・WS配信を行う。

    判定計算そのものは trpg.py の compute_dice_judgment を共有する。無認証の
    `POST /api/trpg/dice` はセッション状態を変更しない汎用計算専用として別途残っている
    （こちらは `session_id` を知っているだけの第三者が他人のセッション履歴を
    改ざんできてしまう問題があったための分離、2026-08-02）。
    """
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    from def_kari.api.routes.trpg import compute_dice_judgment
    try:
        computed = compute_dice_judgment(req.notation, req.skill_value, req.rulebook_id, req.is_skill, req.is_stat)
    except ValueError as e:
        return {"error": str(e)}
    result = computed["result"]
    judgment = computed["judgment"]

    if req.character_id:
        name_map = session.get("name_map", {})
        cname = name_map.get(req.character_id, req.character_id)
        stat_part = f"【{req.stat_name}】" if req.stat_name else ""
        j = judgment or {}
        jv = j.get("judgment_value", req.skill_value)
        if j.get("critical"):
            outcome = "クリティカル！"
        elif j.get("fumble"):
            outcome = "ファンブル…"
        elif j.get("success"):
            outcome = "成功"
        elif j:
            outcome = "失敗"
        else:
            outcome = ""
        msg = f"🎲 {cname}{stat_part} {result['total']} / {jv}"
        if outcome:
            msg += f" → {outcome}"
        session["history"].append({
            "role": "user",
            "content": msg,
            "character_id": req.character_id,
        })
        _autosave(session_id)

    if judgment:
        from def_kari.gm.events import JUDGMENT_RESOLVED
        _game_event_bus.emit(session_id, JUDGMENT_RESOLVED, {
            "character_id": req.character_id,
            "stat_name": req.stat_name,
            "notation": result["notation"],
            "roll": result["total"],
            "judgment_value": judgment.get("judgment_value"),
            "success": judgment.get("success"),
            "critical": judgment.get("critical"),
            "fumble": judgment.get("fumble"),
        })

    return {
        "notation": result["notation"],
        "rolls": result["rolls"],
        "total": result["total"],
        "modifier": result["modifier"],
        "judgment": judgment,
    }


@router.post("/{session_id}/scene/advance")
def advance_scene(session_id: str, _auth: dict = Depends(require_keeper)):
    """現在のシーンを次のシーンへ進める。"""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    scenario = _load_trpg_scenario(session.get("trpg_scenario", ""))
    scenes = scenario.get("scenes", [])
    current_idx = session.get("current_scene_index", 0)
    if current_idx >= len(scenes) - 1:
        return {"error": "Already at last scene", "current_scene_index": current_idx}
    session["current_scene_index"] = current_idx + 1
    session["scene_round_start"] = session.get("round", 0)
    new_idx = session["current_scene_index"]
    new_scene = scenes[new_idx] if new_idx < len(scenes) else {}
    chapter = None
    for ch in scenario.get("chapters", []):
        if new_scene.get("id", "") in ch.get("scene_ids", []):
            chapter = ch
            break
    _autosave(session_id)
    return {
        "current_scene_index": new_idx,
        "scene_id": new_scene.get("id", ""),
        "scene_title": new_scene.get("title", ""),
        "chapter_id": chapter.get("id", "") if chapter else None,
        "chapter_title": chapter.get("title", "") if chapter else None,
    }


@router.post("/{session_id}/chapter/advance")
def advance_chapter(session_id: str, _auth: dict = Depends(require_keeper)):
    """次のチャプターの最初のシーンへ進める。"""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    scenario = _load_trpg_scenario(session.get("trpg_scenario", ""))
    scenes = scenario.get("scenes", [])
    chapters = scenario.get("chapters", [])
    if not chapters:
        return advance_scene(session_id)
    current_idx = session.get("current_scene_index", 0)
    current_scene_id = scenes[current_idx].get("id", "") if current_idx < len(scenes) else ""
    current_ch_idx = next(
        (i for i, c in enumerate(chapters) if current_scene_id in c.get("scene_ids", [])),
        -1,
    )
    if current_ch_idx < 0 or current_ch_idx >= len(chapters) - 1:
        return {"error": "Already at last chapter", "current_scene_index": current_idx}
    next_ch = chapters[current_ch_idx + 1]
    if not next_ch.get("scene_ids"):
        return {"error": "Next chapter has no scenes"}
    first_scene_id = next_ch["scene_ids"][0]
    new_idx = next((i for i, s in enumerate(scenes) if s.get("id") == first_scene_id), -1)
    if new_idx < 0:
        return {"error": f"Scene {first_scene_id} not found in scenario"}
    session["current_scene_index"] = new_idx
    new_scene = scenes[new_idx]
    _autosave(session_id)
    return {
        "current_scene_index": new_idx,
        "scene_id": new_scene.get("id", ""),
        "scene_title": new_scene.get("title", ""),
        "chapter_id": next_ch.get("id", ""),
        "chapter_title": next_ch.get("title", ""),
    }


class DesignateRequest(BaseModel):
    target_id: str


@router.post("/{session_id}/designate")
def designate_next(session_id: str, req: DesignateRequest, _auth: dict = Depends(require_player)):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    if req.target_id not in session["initiative"]:
        return {"error": "Character not in initiative"}
    initiative = session["initiative"]
    current_turn = session.get("turn", 0)
    # 指名発言後に戻るべきターン位置を保存（指名キャラの次）
    session["designated_next"] = req.target_id
    session["designated_return_turn"] = (current_turn + 1) % len(initiative) if initiative else 0
    _autosave(session_id)
    name_map = session.get("name_map", {})
    _current = _get_current_speaker(session)
    _game_event_bus.emit(session_id, "HUMAN_ACTION", {
        "character_id": _current or "",
        "character_name": name_map.get(_current, _current) if _current else "",
        "text": "",
        "action": "designate",
        "designated_id": req.target_id,
        "designated_name": name_map.get(req.target_id, req.target_id),
        "counters": dict(session.get("counters", {})),
    })
    return {"status": "ok"}


class CounterAdjustRequest(BaseModel):
    delta: int


@router.post("/{session_id}/counter/{char_id}")
def adjust_counter(session_id: str, char_id: str, req: CounterAdjustRequest, _auth: dict = Depends(require_keeper)):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    counters = session.setdefault("counters", {})
    counters[char_id] = counters.get(char_id, 0) + req.delta
    _autosave(session_id)
    _game_event_bus.emit(session_id, "HUMAN_ACTION", {
        "character_id": char_id,
        "character_name": session.get("name_map", {}).get(char_id, char_id),
        "text": "",
        "action": "counter_adjust",
        "counters": dict(counters),
    })
    return {"counters": dict(counters)}


class VoteRequest(BaseModel):
    vote_type: str
    detail: str = ""
    target_id: str = ""
    proposer_id: str = ""  # 人間プレイヤーが発議した場合、カウンターを0にする
    proposer_text: str = ""  # 人間プレイヤーの弁明テキスト


class VoteCommitRequest(BaseModel):
    keeper_vote: bool


class HumanTurnRequest(BaseModel):
    action: str  # "send" | "extend" | "skip" | "interrupt" | "generate_image"
    text: str = ""
    character_id: str = ""  # interrupt 時に発言者IDを指定
    # send/skip の多重送信対策(2026-08-08)。クライアントは直近に受け取った
    # WAITING_FOR_HUMAN イベントの round をそのまま送り返す。デフォルト値(-1)は
    # 実在のroundと一致しないため、対応していない/未取得のクライアントは
    # send/skipで常に拒否される(下のhuman_turn_action参照)。
    expected_round: int = -1

    from pydantic import validator as _pv

    @_pv("action")
    @classmethod
    def _validate_action(cls, v: str) -> str:
        valid = {"send", "extend", "skip", "interrupt", "generate_image"}
        if v not in valid:
            raise ValueError(f"action must be one of {sorted(valid)}")
        return v


@router.post("/{session_id}/human_turn")
async def human_turn_action(session_id: str, req: HumanTurnRequest, _auth: dict = Depends(require_player)):
    """人間プレイヤーのターンアクション（send / extend / skip）。

    TTS合成（_start_background_tts）を伴うが、HTTP POST経由のため_check_ws_rate
    （WebSocketメッセージ専用）の対象外でレート制限が無かった（8.10対策）。WS発言と
    同じ基準（60回/分）を適用する。1ターン中に複数回のアクション（積む→送信等）を
    行う通常のゲームプレイを妨げないよう、生成系専用のより厳しい制限
    （_check_generation_rate、6回/分）ではなくこちらを使う。
    """
    gen_key = _auth.get("jti") or str(_auth)
    if not _check_ws_rate(session_id, gen_key):
        raise HTTPException(429, "Too many requests. Please wait a moment.")
    if req.text and contains_blocked_content(req.text):
        raise HTTPException(400, "This message cannot be sent.")

    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    if session.get("lobby_active"):
        raise HTTPException(409, "Session has not started yet")

    initiative = session["initiative"]
    turn = session["turn"]
    if turn >= len(initiative):
        return {"error": "invalid turn"}

    current_char_id = initiative[turn]
    name_map = session["name_map"]
    counters = session.setdefault("counters", {})
    char_name = name_map.get(current_char_id, current_char_id)

    # ── ターン所有権チェック(2026-08-08修正) ────────────────────────
    # send/extend/skip は「今まさに initiative[turn] の人間キャラの番である」ことを
    # 前提に session["turn"] を進める。だが従来はcurrent_char_idが本当に人間枠か・
    # 呼び出しトークンがそのキャラ本人かを一切検証していなかった。そのため同一
    # クライアントからの二重送信(ネットワーク再試行・連打・スクリプトでの連打)が
    # 後続の別キャラ(他プレイヤーやAI含む)のターンまで次々と消費してしまっていた
    # (frontend/e2e/ai_turn_dedup.js で実証。8並列送信→4件処理されRoundが進む)。
    #
    # 当初「turnの読み取りから書き戻しまでの間に割り込まれるTOCTOU」と誤診断していたが、
    # human_turn_action は async def ながら本体に await が一切無く、asyncioの協調
    # スケジューリング上この関数は呼ばれたら他コルーチンに横入りされず単一
    # イベントループ上でアトミックに完走する。実体はレースではなく、この認可漏れ
    # そのものだった(重複送信は真の並行処理ではなく、逐次的に全件処理されていた)。
    #
    # host/gm はゲームマスターとして人間キャラを兼任する場合があるが、トークン発行時に
    # char_idを持たない(issue_player_jwt呼び出し側を参照)ため、ここでは対象外のまま
    # 維持する(host_tokenでの人間ターン送信は従来通り許可＝既存テスト・挙動を壊さない)。
    # host/gmが他人の人間キャラのターンを送信できてしまう点は既知の残課題としてTODO.mdへ。
    if req.action in ("send", "extend", "skip"):
        if current_char_id not in session.get("human_char_ids", []):
            raise HTTPException(409, "It is not currently a human player's turn")
        if _auth.get("role") == "player" and _auth.get("char_id") != current_char_id:
            raise HTTPException(409, "It is not your turn")
        # ── ターンの多重完了ガード(2026-08-08修正) ────────────────────
        # send/skip はターン(引いてはround)を進める「確定」操作。上のオーナーシップ
        # チェックだけでは、initiativeに人間が1人しかいない(AI不在の)セッションで
        # 同一クライアントが同じ送信を連打した場合を防げない: _run_ai_turns側の
        # 巻き戻り(turn>=len(initiative)時にround+1・turn=0)はLLM呼び出しを伴わず
        # 同一イベントループtick内で即座に完了し、次の巻き戻り後もcurrent_char_idは
        # 依然として同じ本人のキャラのままなので、オーナーシップは何度でも一致して
        # しまう(frontend/e2e/ai_turn_dedup.js で実証)。
        #
        # そこでWAITING_FOR_HUMANイベントで配布したroundをクライアントに送り返させ、
        # サーバー側の現在roundと一致する場合のみ「確定」操作を許可する。1件目の
        # send/skipが処理された時点でroundは進む(または次のWAITING_FOR_HUMANで
        # 新しいroundが配布されるまでは)ため、同じexpected_roundを使った残りの
        # 重複リクエストは以後すべて不一致で拒否される。extendはターンを進めない
        # 「積む」操作で、1ターン中に複数回呼ばれるのが正規の使い方のためチェック対象外。
        #
        # 既知の残課題: designated_next(GM指名による割り込み)で同一roundのまま
        # current_char_idが同じ人間キャラに再度回ってくる稀なケースはこのroundだけの
        # 比較では区別できない。実害は小さいためTODO.mdへ別途記録する。
        if req.action in ("send", "skip") and req.expected_round != session["round"]:
            raise HTTPException(409, "This turn has already been completed (stale request)")

    if req.action == "interrupt":
        if not req.text.strip():
            return {"error": "text required"}
        # 割り込み発言者は current_char_id ではなく req.character_id（人間キャラ）
        interrupter_id = req.character_id if req.character_id else current_char_id
        interrupter_name = name_map.get(interrupter_id, interrupter_id)
        counters[interrupter_id] = counters.get(interrupter_id, 0) - 2
        session["history"].append({
            "role": "assistant",
            "content": f"{interrupter_name}: {req.text}",
            "character_id": interrupter_id,
            "emotion": "neutral",
            "tags": [],
        })
        _autosave(session_id)
        _game_event_bus.emit(session_id, "HUMAN_ACTION", {
            "character_id": interrupter_id,
            "character_name": interrupter_name,
            "text": req.text,
            "action": "interrupt",
            "counters": dict(counters),
        })
        return {
            "action": "interrupt",
            "character_id": interrupter_id,
            "character_name": interrupter_name,
            "text": req.text,
            "round": session["round"],
            "counters": dict(counters),
        }

    if req.action == "generate_image":
        char_id = req.character_id if req.character_id else current_char_id
        counters[char_id] = counters.get(char_id, 0) - 1
        _autosave(session_id)
        _game_event_bus.emit(session_id, "HUMAN_ACTION", {
            "character_id": char_id,
            "character_name": name_map.get(char_id, char_id),
            "text": "",
            "action": "generate_image",
            "counters": dict(counters),
        })
        return {
            "action": "generate_image",
            "counters": dict(counters),
            "round": session["round"],
        }

    if req.action == "skip":
        _cancel_disconnect_skip(session_id, current_char_id)
        return _apply_skip(session_id, session, current_char_id)

    if not req.text.strip():
        return {"error": "text required"}

    session["history"].append({
        "role": "assistant",
        "content": f"{char_name}: {req.text}",
        "character_id": current_char_id,
        "emotion": "neutral",
        "tags": [],
    })

    # 人間プレイヤー自身の発言読み上げ。他参加者には配信しない（HUMAN_ACTION は元々
    # 「自分以外」専用のイベントで、本人はこのレスポンスから直接処理する設計のため）。
    # バックグラウンドで合成し、完了したら AUDIO_READY(character_id + request_id) で通知する
    # （同期呼び出しだとTTSバックエンド無応答時にHTTPレスポンスごとブロックされるため、2026-08-02修正）。
    audio_request_id = _start_background_tts(session_id, req.text, current_char_id)

    if req.action == "extend":
        counters[current_char_id] = counters.get(current_char_id, 0) - 1
        _autosave(session_id)
        _game_event_bus.emit(session_id, "HUMAN_ACTION", {
            "character_id": current_char_id,
            "character_name": char_name,
            "text": req.text,
            "action": "extend",
            "counters": dict(counters),
        })
        return {
            "action": "extend",
            "character_id": current_char_id,
            "character_name": char_name,
            "text": req.text,
            "round": session["round"],
            "counters": dict(counters),
            "audio_request_id": audio_request_id,
        }
    else:  # "send"
        # 人間プレイヤーは「積む→発言完」が1ターン完了とみなす（actions_per_turn に関わらず即時進行）
        session["turn"] = turn + 1
        session["action_count"] = 0
        _autosave(session_id)
        _game_event_bus.emit(session_id, "HUMAN_ACTION", {
            "character_id": current_char_id,
            "character_name": char_name,
            "text": req.text,
            "action": "send",
            "counters": dict(counters),
        })
        # AIタスク起動（二重起動防止）
        _ai_task = session.get("ai_task")
        if not _ai_task or _ai_task.done():
            session["ai_task"] = asyncio.create_task(_run_ai_turns(session_id))
        return {
            "action": "send",
            "turn_advanced": True,
            "character_id": current_char_id,
            "character_name": char_name,
            "text": req.text,
            "round": session["round"],
            "counters": dict(counters),
            "audio_request_id": audio_request_id,
        }


@router.post("/{session_id}/vote/deliberate")
def vote_deliberate(session_id: str, req: VoteRequest, request: Request, _auth: dict = Depends(require_player)):
    """弁明ラウンド: 全 AI キャラが意見を述べてセッションに保存し、結果を返す。

    initiative内の全AIキャラ分のLLM呼び出しを伴うため、generate-image（S-6）と
    同じレート制限パターンを適用する（8.9対策。以前はこのエンドポイントに
    レート制限が無く、AIキャラがN人いるセッションなら1回の連打でN倍のLLM呼び出しが
    発生しうった）。
    """
    gen_key = _auth.get("jti") or str(_auth)
    client_ip = _resolve_client_ip(request)
    if not _check_circuit_breaker(session_id):
        raise HTTPException(423, "Generation for this session is paused due to unusual activity. Ask the host to review the audit log and reset it.")
    if not _check_generation_rate(session_id, gen_key):
        _record_violation_and_maybe_trip("vote_deliberate", session_id, client_ip, gen_key)
        raise HTTPException(429, "Too many vote requests. Please wait a moment.")
    if not _check_generation_rate(session_id, f"ip:{client_ip}", limit=20):
        _record_violation_and_maybe_trip("vote_deliberate", session_id, client_ip, gen_key)
        raise HTTPException(429, "Too many vote requests from this network. Please wait a moment.")
    if not _check_daily_generation_limit(session_id):
        raise HTTPException(429, "This session has reached its daily generation limit.")
    record_generation_event("vote_deliberate", session_id, client_ip, gen_key)

    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    initiative = session["initiative"]
    name_map = session["name_map"]
    char_backends = session.get("char_backends", {})
    default_backend = session.get("backend", DEFAULT_LLM_BACKEND)
    profiles = load_profiles()

    from def_kari.settings import load_settings as _load_settings_v
    _vlang = _load_settings_v().get("user_language", "ja")
    vote_labels = {
        "topic_change": "Change Topic" if _vlang == "en" else "お題変更",
        "expel": "Expel Participant" if _vlang == "en" else "参加者退場",
        "end_session": "End Session" if _vlang == "en" else "セッション終了",
    }
    vote_label = vote_labels.get(req.vote_type, req.vote_type)
    detail_text = f" — {req.detail}" if req.detail else ""

    # ターン位置を保存 (commit 時に復元する)
    session["_pending_vote"] = {
        "vote_type": req.vote_type,
        "detail": req.detail,
        "target_id": req.target_id,
        "proposer_id": req.proposer_id,
        "vote_label": vote_label,
        "detail_text": detail_text,
        "saved_turn": session["turn"],
        "saved_round": session["round"],
        "saved_action_count": session.get("action_count", 0),
        "deliberation_texts": {},
    }

    counters = session.setdefault("counters", {})
    if req.proposer_id:
        counters[req.proposer_id] = 0

    deliberations: list[dict] = []

    vote_announce = (
        f"[Vote Proposal] {vote_label}{detail_text}\nAll participants are asked for their opinion."
        if _vlang == "en" else
        f"[投票提案] {vote_label}{detail_text}\n参加者全員に意見を求めます。"
    )
    session["history"].append({
        "role": "user",
        "content": vote_announce,
        "character_id": "_keeper",
    })
    deliberations.append({
        "character_id": "_keeper",
        "character_name": "キーパー",
        "text": vote_announce,
        "emotion": "neutral",
    })

    if req.proposer_id and req.proposer_text.strip():
        proposer_name = name_map.get(req.proposer_id, req.proposer_id)
        session["history"].append({
            "role": "assistant",
            "content": f"{proposer_name}: {req.proposer_text}",
            "character_id": req.proposer_id,
            "emotion": "neutral",
            "tags": [],
        })
        deliberations.append({
            "character_id": req.proposer_id,
            "character_name": proposer_name,
            "text": req.proposer_text,
            "emotion": "neutral",
            "audio_request_id": _start_background_tts(session_id, req.proposer_text, req.proposer_id),
        })
        session["_pending_vote"]["deliberation_texts"][req.proposer_id] = req.proposer_text

    _v_settings = load_settings()
    _v_lang = _v_settings.get("user_language", "ja") or "ja"
    _v_allowed_sexual = _v_settings.get("allowed_rating_sexual", ["general"])
    _v_allowed_violence = _v_settings.get("allowed_rating_violence", ["general"])

    for char_id in initiative:
        char = get_character(char_id, profiles)
        char_name = name_map.get(char_id, char_id)

        # 人間プレイヤーは LLM 生成をスキップ
        if _is_human_char(session, char_id, profiles):
            continue

        bid = char_backends.get(char_id) or default_backend
        if bid not in LLM_BACKENDS:
            bid = DEFAULT_LLM_BACKEND
        model = _resolve_model(bid)

        deliberation_prompt = _sp("deliberation_prompt", _v_lang).format(
            vote_label=vote_label, detail_text=detail_text
        )

        _v_prev_emotion = next(
            (h.get("emotion", "neutral") for h in reversed(session["history"])
             if h.get("character_id") == char_id),
            "neutral",
        )
        if isinstance(_v_prev_emotion, list):
            _v_prev_emotion = ", ".join(_v_prev_emotion)
        _v_session_ctx = _build_session_context(
            session.get("topic", ""), session.get("rules", []),
            initiative, name_map, char_name, _v_lang,
        )
        _v_history = []
        for h in session["history"][-20:]:
            _raw = h["content"]
            _h_role = h.get("role", "user")
            _h_cid = h.get("character_id")
            if _h_role == "assistant" and _h_cid:
                _text = _raw.split(": ", 1)[-1] if ": " in _raw else _raw
                if _h_cid == char_id:
                    _v_history.append({"role": "assistant", "content": _text})
                else:
                    _oname = name_map.get(_h_cid, _h_cid)
                    _v_history.append({"role": "user", "content": f"[{_oname}] {_text}"})
            else:
                _v_history.append({"role": _h_role, "content": _raw})
        try:
            from def_kari.resources.vram_lock import get_vram_lock as _get_vl
            _delib_lock = _get_vl()
            if not _delib_lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
                # 外側のexceptにフォールスルーさせ、既存の「弁明なし」処理に乗せる
                raise RuntimeError(f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s")
            try:
                from def_kari.models.t2i_profiles import get_current_tag_format as _get_tag_fmt
                result = generate_structured_reply(
                    user_text=deliberation_prompt,
                    history=_v_history,
                    model=model,
                    character=char,
                    backend=bid,
                    allowed_sexual=_v_allowed_sexual,
                    allowed_violence=_v_allowed_violence,
                    current_emotion=_v_prev_emotion,
                    session_context=_v_session_ctx,
                    tag_format=_get_tag_fmt(),
                )
            finally:
                _delib_lock.release()
            dialogue = ""
            emotion = "neutral"
            tags: list = []
            had_dialogue = False
            if result.get("success") and result.get("result"):
                parsed = result["result"]
                dialogue = parsed.get("dialogue", "")
                emotion = parsed.get("emotion", "neutral")
                tags = parsed.get("tags", []) or []
            if dialogue:
                had_dialogue = True
            else:
                dialogue = _sp("no_deliberation", _v_lang) or "(弁明なし)"
        except Exception:
            dialogue = _sp("no_deliberation", _v_lang) or "(弁明なし)"
            emotion = "neutral"
            tags = []
            had_dialogue = False

        session["history"].append({
            "role": "assistant",
            "content": f"{char_name}: {dialogue}",
            "character_id": char_id,
            "emotion": emotion,
            "tags": tags,
        })
        deliberations.append({
            "character_id": char_id,
            "character_name": char_name,
            "text": dialogue,
            "emotion": emotion,
            "tags": tags,
            "audio_request_id": _start_background_tts(session_id, dialogue, char_id) if had_dialogue else "",
        })
        session["_pending_vote"]["deliberation_texts"][char_id] = dialogue

    _autosave(session_id)
    return {"deliberations": deliberations, "counters": dict(counters)}


@router.post("/{session_id}/vote/commit")
async def vote_commit(session_id: str, req: VoteCommitRequest, request: Request, _auth: dict = Depends(require_keeper)):
    """キーパー票を受け取り、AI票と合算して集計・効果適用する。

    全AIキャラの投票判定でLLM呼び出しを伴うため、vote_deliberateと同じレート制限を
    適用する（8.9対策）。require_keeper化（8.19）により招待ゲストからは呼べなくなったが、
    念のため軽めの上限を残す。
    """
    gen_key = _auth.get("jti") or str(_auth)
    client_ip = _resolve_client_ip(request)
    if not _check_circuit_breaker(session_id):
        raise HTTPException(423, "Generation for this session is paused due to unusual activity. Ask the host to review the audit log and reset it.")
    if not _check_generation_rate(session_id, gen_key):
        _record_violation_and_maybe_trip("vote_commit", session_id, client_ip, gen_key)
        raise HTTPException(429, "Too many vote requests. Please wait a moment.")
    if not _check_generation_rate(session_id, f"ip:{client_ip}", limit=20):
        _record_violation_and_maybe_trip("vote_commit", session_id, client_ip, gen_key)
        raise HTTPException(429, "Too many vote requests from this network. Please wait a moment.")
    if not _check_daily_generation_limit(session_id):
        raise HTTPException(429, "This session has reached its daily generation limit.")
    record_generation_event("vote_commit", session_id, client_ip, gen_key)

    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    pending = session.get("_pending_vote")
    if not pending:
        return {"error": "No pending vote"}

    initiative = session["initiative"]
    name_map = session["name_map"]
    char_backends = session.get("char_backends", {})
    default_backend = session.get("backend", DEFAULT_LLM_BACKEND)
    profiles = load_profiles()

    vote_type = pending["vote_type"]
    vote_label = pending["vote_label"]
    detail_text = pending["detail_text"]
    detail = pending["detail"]
    target_id = pending["target_id"]
    deliberation_texts = pending["deliberation_texts"]

    from def_kari.resources.vram_lock import get_vram_lock
    from def_kari.settings import load_settings as _load_settings
    _vram_lock = get_vram_lock()
    _force_approve = bool(_load_settings().get("vote_force_approve", False))

    proposer_id = pending.get("proposer_id", "")
    _v_lang = _load_settings().get("user_language", "ja") or "ja"

    results: dict[str, bool] = {}
    for char_id in initiative:
        char = get_character(char_id, profiles)

        # 人間プレイヤーは LLM 判定せず keeper_vote（ボタンクリック）を直接使う
        if _is_human_char(session, char_id, profiles):
            results[char_id] = req.keeper_vote
            continue

        bid = char_backends.get(char_id) or default_backend
        if bid not in LLM_BACKENDS:
            bid = DEFAULT_LLM_BACKEND
        model = _resolve_model(bid)
        dialogue = deliberation_texts.get(char_id, "")

        if _force_approve:
            results[char_id] = True
            continue

        judge_prompt = _sp("judge_prompt", _v_lang).format(
            dialogue=dialogue, vote_label=vote_label, detail_text=detail_text,
            yes_word=_sp("yes_word", _v_lang), no_word=_sp("no_word", _v_lang),
        )
        try:
            chat_fn = LLM_BACKENDS[bid]["chat"]
            messages = [
                {"role": "system", "content": char.get("persona_description", "")},
                {"role": "user", "content": judge_prompt},
            ]
            if not _vram_lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
                raise RuntimeError(f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s")
            try:
                reply = chat_fn(messages, model, json_mode=False, options={"num_predict": 32})
            finally:
                _vram_lock.release()
            results[char_id] = _sp("yes_word", _v_lang) in reply or "yes" in reply.lower()
        except Exception:
            results[char_id] = True

    if proposer_id and proposer_id != "_keeper":
        # 人間キャラが発議: LLM がキーパーとして追加投票
        bid = default_backend if default_backend in LLM_BACKENDS else DEFAULT_LLM_BACKEND
        model = _resolve_model(bid)
        if _force_approve:
            results["_keeper"] = True
        else:
            all_texts = "\n".join(
                f"{name_map.get(cid, cid)}: {text}"
                for cid, text in deliberation_texts.items()
                if text
            )
            keeper_judge_prompt = _sp("keeper_judge_prompt", _v_lang).format(
                vote_label=vote_label, detail_text=detail_text, all_texts=all_texts,
                yes_word=_sp("yes_word", _v_lang), no_word=_sp("no_word", _v_lang),
            )
            try:
                chat_fn = LLM_BACKENDS[bid]["chat"]
                keeper_msgs = [
                    {"role": "system", "content": _sp("keeper_system", _v_lang) or "あなたはセッションのキーパー（GM・司会者）です。"},
                    {"role": "user", "content": keeper_judge_prompt},
                ]
                if not _vram_lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
                    raise RuntimeError(f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s")
                try:
                    reply = chat_fn(keeper_msgs, model, json_mode=False, options={"num_predict": 32})
                finally:
                    _vram_lock.release()
                results["_keeper"] = _sp("yes_word", _v_lang) in reply or "yes" in reply.lower()
            except Exception:
                results["_keeper"] = True
    else:
        # 人間キャラなし: キーパー票はボタンクリックで決まる
        results["_keeper"] = req.keeper_vote

    yes_count = sum(1 for v in results.values() if v)
    no_count = len(results) - yes_count
    passed = yes_count > no_count

    _expelled_participant_id = ""
    _keeper_handed_off = False
    if passed:
        if vote_type == "topic_change" and detail:
            session["topic"] = detail
        elif vote_type == "expel" and target_id:
            session["initiative"] = [c for c in initiative if c != target_id]
            if target_id == session.get("keeper_char_id"):
                # 自治規約62行目: 「キーパーが退場した場合はAIキーパーへ交代してセッションを
                # 継続する」。空文字列にするとai_keeper_narrate()が自動的に汎用の
                # 無名AIキーパー（🎩 Keeper）にフォールバックする（lobby_set_keeper_charの
                # 解除と同じ仕組み）ため、他に配線は不要。
                session["keeper_char_id"] = ""
                session["keeper_char_name"] = ""
                _keeper_handed_off = True
            # 対象が人間プレイヤーの場合、initiativeから外すだけでは接続・トークンが
            # 生きたまま残り続ける（leave_session相当の後始末が漏れていた）。
            # char_id→tokenを逆引きし、players/ws_connections/token_to_participant
            # から完全に除去し、JWTも無効化する。
            _expelled_token = next(
                (t for t, c in list(session.get("players", {}).items()) if c == target_id), None
            )
            if _expelled_token:
                session["players"].pop(_expelled_token, None)
                _cancel_disconnect_skip(session_id, target_id)
                _expelled_participant_id = session.get("token_to_participant", {}).pop(
                    _expelled_token, target_id
                )
                session["joined_participants"] = [
                    p for p in session.get("joined_participants", [])
                    if p.get("participant_id") != _expelled_participant_id
                ]
                _expelled_ws = session.get("ws_connections", {}).pop(_expelled_token, None)
                _ws_send_locks.pop(_expelled_token, None)
                if _expelled_ws:
                    try:
                        await _expelled_ws.close(code=1000)
                    except Exception:
                        pass
                revoke_token(_expelled_token)
            # 追放されたキャラのcharacter_jsonをブラックリストに記録し、同じ招待コードで
            # 同一character_jsonの再参加を拒否できるようにする（8.21対策）。guest_charsに
            # 存在しない対象（既存人間スロットのclaim_char_id等）は元々character_json持ち込み
            # ではないため対象外。
            _expelled_char_data = session.get("guest_chars", {}).get(target_id)
            if _expelled_char_data:
                _fp = _character_json_fingerprint(_expelled_char_data)
                session.setdefault("expelled_char_fingerprints", []).append(_fp)

    # イベントバス通知（vote結果をゲームロジックレイヤーへ伝播）
    if passed:
        from def_kari.gm.events import game_event_bus, TOPIC_CHANGED, SESSION_ENDED
        if vote_type == "topic_change" and detail:
            game_event_bus.emit(session_id, TOPIC_CHANGED, {"new_topic": detail})
        elif vote_type == "end_session":
            game_event_bus.emit(session_id, SESSION_ENDED, {})

    # ターン位置を復元
    session["turn"] = pending["saved_turn"]
    session["round"] = pending["saved_round"]
    session["action_count"] = pending["saved_action_count"]

    # expel 可決時: 退場者が saved_turn より前にいた場合は turn を -1 してからクランプ
    if passed and vote_type == "expel" and target_id:
        new_init = session["initiative"]
        expelled_idx = initiative.index(target_id) if target_id in initiative else -1
        if expelled_idx >= 0 and expelled_idx < session["turn"]:
            session["turn"] -= 1
        if len(new_init) > 0 and session["turn"] >= len(new_init):
            session["turn"] = len(new_init) - 1
        elif len(new_init) == 0:
            session["turn"] = 0

    vote_for_label = _sp("vote_for", _v_lang) or "賛成"
    vote_against_label = _sp("vote_against", _v_lang) or "反対"
    keeper_label = _sp("keeper_label", _v_lang) or "キーパー"
    human_vote_label = vote_for_label if req.keeper_vote else vote_against_label
    keeper_llm_label = vote_for_label if results.get("_keeper") else vote_against_label
    if proposer_id and proposer_id != "_keeper":
        vote_detail_str = (
            f"{name_map.get(proposer_id, proposer_id)}: {human_vote_label}, "
            f"{keeper_label}: {keeper_llm_label}"
        )
    else:
        vote_detail_str = f"{keeper_label}: {human_vote_label}"
    outcome = _sp("vote_passed" if passed else "vote_rejected", _v_lang) or ("✅ 可決" if passed else "❌ 否決")
    result_text = (_sp("vote_result", _v_lang) or "🗳 {vote_label}{detail_text} — {yes_count}/{no_count}（{vote_detail_str}） → {outcome}").format(
        vote_label=vote_label, detail_text=detail_text,
        yes_count=yes_count, no_count=no_count,
        vote_detail_str=vote_detail_str, outcome=outcome,
    )
    if _keeper_handed_off:
        result_text += "\n" + _sp("keeper_handoff_notice", _v_lang)
    session["history"].append({
        "role": "user",
        "content": result_text,
        "character_id": "_keeper",
    })

    session.pop("_pending_vote", None)

    # 投票結果を全タブへ配信
    _game_event_bus.emit(session_id, "HUMAN_ACTION", {
        "character_id": "_keeper",
        "character_name": "🗳 Vote",
        "text": result_text,
        "action": "vote_result",
        "counters": dict(session.get("counters", {})),
    })

    if _expelled_participant_id:
        # 参加者パネル（PLAYER_LEFTで participant_id を照合して除去するUI）にも
        # 反映されるよう、leave_session と同じイベントを発行する。
        _game_event_bus.emit(session_id, "PLAYER_LEFT", {
            "participant_id": _expelled_participant_id,
            "character_id": target_id,
        })

    ended = passed and vote_type == "end_session"
    if ended and not session.get("_ending"):
        session["_ending"] = True
        _save_session_episodic(session_id, session)
        _delete_autosave(session_id)
        from def_kari.gm.events import game_event_bus
        game_event_bus.clear_log(session_id)
        asyncio.create_task(_end_session(session_id))
    else:
        _autosave(session_id)
    return {
        "results": {name_map.get(k, k) if k != "_keeper" else keeper_label: v for k, v in results.items()},
        "yes_count": yes_count,
        "no_count": no_count,
        "passed": passed,
        "result_text": result_text,
        "vote_type": vote_type,
        "ended": ended,
        "initiative": session["initiative"],
        "topic": session.get("topic", ""),
    }


@router.get("/{session_id}/events")
def get_session_events(session_id: str, _auth: dict = Depends(require_keeper)):
    """セッションのゲームロジックイベントログを返す（Observer Agent用）。

    FLAG_UPDATED等、gm_only: trueが付くイベントを含みうるため、require_keeperで
    保護する（8.12対策。以前は無認証で、正規に招待コードで参加した一般プレイヤーが
    GM専用の隠し情報を覗けてしまっていた）。フロントからは現状未使用。
    """
    from def_kari.gm.events import game_event_bus
    return {"session_id": session_id, "events": game_event_bus.get_log(session_id)}


class NpcKnowledgeRequest(BaseModel):
    entry: str


class NpcRelationshipRequest(BaseModel):
    char_id: str
    trust: int | None = None
    hostility: int | None = None


@router.post("/{session_id}/npc/{npc_id}/knowledge")
def add_npc_knowledge(session_id: str, npc_id: str, req: NpcKnowledgeRequest, _auth: dict = Depends(require_keeper)):
    """NPC が新たな情報を獲得したとき knowledge に追加する。

    GM または自動ゲームロジックから呼び出す。
    """
    session = _sessions.get(session_id)
    if not session:
        return {"error": "session not found"}
    npc_state = session.setdefault("npc_state", {})
    npc = npc_state.setdefault(npc_id, {"knowledge": [], "relationship": {}})
    if req.entry and req.entry not in npc["knowledge"]:
        npc["knowledge"].append(req.entry)
        from def_kari.gm.events import game_event_bus, FLAG_UPDATED
        game_event_bus.emit(session_id, FLAG_UPDATED, {
            "key": f"npc_{npc_id}_knowledge",
            "value": req.entry,
            "gm_only": True,
        })
    return {"npc_id": npc_id, "knowledge": npc["knowledge"]}


@router.post("/{session_id}/npc/{npc_id}/relationship")
def update_npc_relationship(session_id: str, npc_id: str, req: NpcRelationshipRequest, _auth: dict = Depends(require_keeper)):
    """NPC の特定キャラクターへの関係値を更新する。

    trust / hostility は None を渡すと変更しない（部分更新）。
    """
    session = _sessions.get(session_id)
    if not session:
        return {"error": "session not found"}
    npc_state = session.setdefault("npc_state", {})
    npc = npc_state.setdefault(npc_id, {"knowledge": [], "relationship": {}})
    rel = npc["relationship"].setdefault(req.char_id, {"trust": 50, "hostility": 0})
    if req.trust is not None:
        rel["trust"] = max(0, min(100, req.trust))
    if req.hostility is not None:
        rel["hostility"] = max(0, min(100, req.hostility))
    return {"npc_id": npc_id, "char_id": req.char_id, "relationship": rel}


@router.get("/{session_id}/npc/{npc_id}/state")
def get_npc_state(session_id: str, npc_id: str, _auth: dict = Depends(require_keeper)):
    """NPC の現在の動的状態を返す（GM確認用）。

    require_keeperで保護する（8.12対策。以前は無認証で、正規に招待コードで参加した
    一般プレイヤーがNPCの意図・関係値等のGM専用情報をTRPGのゲーム性を壊す形で
    覗けてしまっていた）。フロントからは現状未使用。
    """
    session = _sessions.get(session_id)
    if not session:
        return {"error": "session not found"}
    npc_state = session.get("npc_state", {})
    return {"npc_id": npc_id, "state": npc_state.get(npc_id, {"knowledge": [], "relationship": {}})}


@local_router.get("/debug")
def get_session_debug():
    return _last_session_debug


@local_router.get("/saved")
def list_saved_sessions():
    files = list_session_mode_files()
    _rule_sets = _load_session_rules()
    result = []
    for f in files:
        meta = f.get("metadata", {})
        _rule_set_id = meta.get("rule_set", "")
        result.append({
            "filename": Path(f["path"]).name,
            "session_id": f["session_id"],
            "topic": meta.get("topic", ""),
            "saved_at": meta.get("saved_at", ""),
            "round": meta.get("round", 1),
            "character_names": list(meta.get("name_map", {}).values()),
            "trpg_scenario_title": meta.get("trpg_scenario_title", ""),
            "private": f.get("private", False),
            "rule_set": _rule_set_id,
            "rule_set_label": _rule_sets.get(_rule_set_id, {}).get("label", _rule_set_id),
            "online_mode": meta.get("online_mode", False),
        })
    result.sort(key=lambda x: x["saved_at"], reverse=True)
    return {"sessions": result}


class SessionLoadRequest(BaseModel):
    filename: str


@local_router.delete("/saved/{filename}")
def delete_saved_session(filename: str):
    if not _SAFE_FILENAME_RE.match(filename):
        return {"error": "Invalid filename"}
    for d in _SESSION_HISTORY_DIRS:
        path = d / filename
        if path.exists():
            try:
                path.unlink()
                return {"status": "ok"}
            except OSError as e:
                return {"error": str(e)}
    return {"error": "File not found"}


@local_router.post("/load")
def load_session(req: SessionLoadRequest):
    if not _SAFE_FILENAME_RE.match(req.filename):
        return {"error": "Invalid filename"}
    data = None
    for d in _SESSION_HISTORY_DIRS:
        path = d / req.filename
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                break
            except (json.JSONDecodeError, OSError):
                pass
    if data is None:
        return {"error": "File not found"}
    meta = data.get("metadata", {})
    new_id = secrets.token_urlsafe(16)
    session = {
        "id": new_id,
        "initiative": meta.get("initiative", data.get("participants", [])),
        "name_map": meta.get("name_map", {}),
        "topic": meta.get("topic", ""),
        "backend": meta.get("backend", DEFAULT_LLM_BACKEND),
        "rule_set": meta.get("rule_set", "default"),
        "rules": meta.get("rules", []),
        "round": meta.get("round", 1),
        "turn": meta.get("turn", 0),
        "actions_per_turn": meta.get("actions_per_turn", 2),
        "action_count": 0,
        "history": data.get("history", []),
        "trpg_mode": meta.get("trpg_mode", False),
        "trpg_rulebook": meta.get("trpg_rulebook", ""),
        "trpg_scenario": meta.get("trpg_scenario", ""),
        "char_game_sheets": meta.get("char_game_sheets", {}),
        "current_scene_index": meta.get("current_scene_index", 0),
        "runtime_stats": meta.get("runtime_stats", {}),
        "skill_pool": meta.get("skill_pool", {}),
        "skill_values": meta.get("skill_values", {}),
        "keeper_char_id": meta.get("keeper_char_id", ""),
        "keeper_char_name": meta.get("keeper_char_name", ""),
        "human_keeper": meta.get("human_keeper", False),
        # ── Phase 2: マルチプレイフィールド（ロード時は空で初期化）──
        "players": {},
        "host_token": "",
        "ws_connections": {},
        "ai_task": None,
        "idle_shutdown_task": None,
        "invite_codes": {},
        "ws_rate": {},
        "human_char_ids": meta.get("human_char_ids", []),
    }
    # ロードで復元されたセッションにも /start と同様にホストトークンを発行する。
    # 以前は host_token="" のままトークンを一切発行しておらず、GET /{session_id} の
    # 認証必須化（require_participant）でロード直後の履歴取得が401になるほか、
    # そもそも require_keeper/require_player 保護のセッション操作系（keeper発言・
    # ダイス等）にロード済みセッションから到達する手段が無かった。
    host_token = issue_player_jwt(new_id, "host")
    session["host_token"] = host_token
    session["players"][host_token] = ""  # ホストはキャラなし（/startと同じ扱い）
    if len(_sessions) >= _MAX_SESSIONS:
        _evict_oldest_session()
    _sessions[new_id] = session
    return {
        "session_id": new_id,
        "host_token": host_token,
        "initiative": session["initiative"],
        "round": session["round"],
        "topic": session["topic"],
        "name_map": session["name_map"],
        "history": session["history"],
        "actions_per_turn": session["actions_per_turn"],
        "trpg_mode": session["trpg_mode"],
        "trpg_rulebook": session.get("trpg_rulebook", ""),
        "char_game_sheets": session["char_game_sheets"],
        "runtime_stats": session["runtime_stats"],
        "current_scene_index": session.get("current_scene_index", 0),
        "human_keeper": session.get("human_keeper", False),
    }


class SaveSessionMediaItem(BaseModel):
    index: int
    image_url: str = ""
    audio_url: str = ""

    from pydantic import validator as _pv

    @_pv("image_url", "audio_url")
    @classmethod
    def _validate_media_url(cls, v: str) -> str:
        """8.20対策: image_url/audio_urlは自サーバーの配信エンドポイントのみ許可する。

        以前はURL形式・オリジンの検証が一切無く、フロント（ChatTab.tsx/SessionTab.tsx）が
        <img src>/<audio src>にそのまま使うため、外部URLを仕込まれると読み込み時点で
        閲覧者のIPアドレス・User-Agentが漏れる。GM/ホスト権限（require_keeper）を持つ
        参加者（あるいはそのトークンを奪われた場合）が他の全参加者に仕込める経路だった。
        """
        if v and not v.startswith(("/api/t2i/image/", "/api/tts/audio/")):
            raise ValueError("image_url/audio_url must point to this server's own media endpoints")
        return v

class SaveSessionRequest(BaseModel):
    media: list[SaveSessionMediaItem] = []

@router.post("/{session_id}/save")
def save_session(session_id: str, req: SaveSessionRequest = Body(default=SaveSessionRequest()), _auth: dict = Depends(require_keeper)):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    history = session.get("history", [])
    for item in req.media:
        if 0 <= item.index < len(history):
            if item.image_url:
                history[item.index]["image_url"] = item.image_url
            if item.audio_url:
                history[item.index]["audio_url"] = item.audio_url

    metadata = {
        "topic": session.get("topic", ""),
        "backend": session.get("backend", ""),
        "rule_set": session.get("rule_set", ""),
        "online_mode": session.get("online_mode", False),
        "rules": session.get("rules", []),
        "round": session.get("round", 1),
        "turn": session.get("turn", 0),
        "initiative": session.get("initiative", []),
        "name_map": session.get("name_map", {}),
        "actions_per_turn": session.get("actions_per_turn", 2),
        "saved_at": datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
        "trpg_mode": session.get("trpg_mode", False),
        "trpg_rulebook": session.get("trpg_rulebook", ""),
        "trpg_scenario": session.get("trpg_scenario", ""),
        "trpg_scenario_title": _load_trpg_scenario(session.get("trpg_scenario", "")).get("title", "") if session.get("trpg_scenario") else "",
        "char_game_sheets": session.get("char_game_sheets", {}),
        "current_scene_index": session.get("current_scene_index", 0),
        "runtime_stats": session.get("runtime_stats", {}),
        "skill_pool": session.get("skill_pool", {}),
        "skill_values": session.get("skill_values", {}),
        "keeper_char_id": session.get("keeper_char_id", ""),
        "keeper_char_name": session.get("keeper_char_name", ""),
        "human_keeper": session.get("human_keeper", False),
    }
    save_session_mode(
        session_id=session_id,
        participants=session.get("initiative", []),
        history=history,
        metadata=metadata,
    )
    _delete_autosave(session_id)
    return {"status": "ok"}


class SessionGenerateImageRequest(BaseModel):
    backend: str = DEFAULT_LLM_BACKEND
    t2i_backend: str = ""
    t2i_model: str = ""
    t2i_prompt_mode: str = ""


@router.post("/{session_id}/generate-image")
def generate_session_image(session_id: str, req: SessionGenerateImageRequest, request: Request, _auth: dict = Depends(require_player)):
    """レート制限＋in-flight排他制御を課した上で実際の生成処理へ委譲する。

    generate-image は課金API呼び出し・GPU時間を消費する実コストの高い
    操作であるため、WS発言用の `_check_ws_rate` とは別の専用バケットで
    頻度を制限し（1参加者あたり6回/分）、加えて同一参加者からの
    多重同時実行（in-flight）を防ぐ。

    jti単位の制限に加えてIPベースの制限も併用する（8.6対策）。/joinは同一招待コードの
    使い回しがオンラインセッションの仕様上OKで、そのたびに新しいjtiのトークンが
    発行されるため、jti単位の制限だけでは正規の招待コード保持者がjoinを繰り返して
    使い捨てトークンで際限なく回避できてしまう。IP単位の上限（1分あたり20回、
    jti単位より緩め）を素通りできないバケットとして併設し、jti単位のバイパスを防ぐ。
    """
    gen_key = _auth.get("jti") or str(_auth)
    client_ip = _resolve_client_ip(request)
    if not _check_circuit_breaker(session_id):
        raise HTTPException(423, "Generation for this session is paused due to unusual activity. Ask the host to review the audit log and reset it.")
    if not _check_generation_rate(session_id, gen_key):
        _record_violation_and_maybe_trip("generate_session_image", session_id, client_ip, gen_key)
        raise HTTPException(429, "Too many image generation requests. Please wait a moment.")
    if not _check_generation_rate(session_id, f"ip:{client_ip}", limit=20):
        _record_violation_and_maybe_trip("generate_session_image", session_id, client_ip, gen_key)
        raise HTTPException(429, "Too many image generation requests from this network. Please wait a moment.")
    if not _check_daily_generation_limit(session_id):
        raise HTTPException(429, "This session has reached its daily generation limit.")
    if not _try_acquire_generation_lock(session_id, gen_key):
        raise HTTPException(429, "An image is already being generated for you. Please wait for it to finish.")
    record_generation_event("generate_session_image", session_id, client_ip, gen_key)
    try:
        return _generate_session_image_impl(session_id, req)
    finally:
        _release_generation_lock(session_id, gen_key)


def _generate_session_image_impl(session_id: str, req: SessionGenerateImageRequest):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    history = session.get("history", [])
    initiative = session.get("initiative", [])
    actions_per_turn = session.get("actions_per_turn", 2)
    name_map = session.get("name_map", {})
    topic = session.get("topic", "")
    scene = session.get("scene", "")

    # 直近ラウンドの発言を取得
    round_size = max(len(initiative) * actions_per_turn, 1)
    last_round = [h for h in history[-round_size * 2:] if h.get("role") == "assistant"][-round_size:]

    from def_kari.settings import load_settings as _load_settings
    _settings = _load_settings()
    t2i_prompt_mode = req.t2i_prompt_mode or _settings.get("t2i_prompt_mode", "current")
    from def_kari.models.t2i_profiles import get_current_tag_format as _get_tag_fmt
    _tag_format = _get_tag_fmt()
    _is_tag_based = _tag_format in ("danbooru", "e621")
    _fmt_label = {"danbooru": "Danbooru", "e621": "e621", "natural": "natural language", "other": "English"}.get(_tag_format, "Danbooru")

    def _dedup_tags(prompt: str, max_tags: int = 256) -> str:
        raw = [t.strip() for t in prompt.split(',') if t.strip()]
        seen: set[str] = set()
        unique: list[str] = []
        for t in raw:
            k = t.lower()
            if k not in seen:
                seen.add(k)
                unique.append(t)
        return ', '.join(unique[:max_tags])

    # TRPGモード: initiative からランダム1人 / 通常: 最後の発言者
    import random as _random
    _pc_ids = [cid for cid in initiative if not cid.startswith("_")]
    if session.get("trpg_mode") and _pc_ids:
        _scene_char_id = _random.choice(_pc_ids)
    else:
        _scene_char_id = last_round[-1].get("character_id") if last_round else None

    # 持ち込みキャラ(guest_chars)については、参加時に許可された招待コードの
    # レーティング上限をセッション内T2I生成でも引き続き適用する（join_session参照）。
    # ロスターキャラ（ホストが用意した既存キャラ）は対象外——ホストが自ら
    # 選んだキャラのため、ここでは持ち込みキャラの取り込み経路のみを塞ぐ。
    _guest_char_data = session.get("guest_chars", {}).get(_scene_char_id)
    if _guest_char_data:
        _scene_content_policy = _extract_content_policy_from_json(_guest_char_data)
        _scene_session_rating = session.get("guest_char_ratings", {}).get(_scene_char_id, "SFW")
        if character_rating_exceeds_invite(_scene_content_policy, _scene_session_rating):
            return {"error": "Image generation blocked: this character's rating exceeds the rating it joined under"}

    if t2i_prompt_mode == "passthrough":
        # LLM不使用: history の image_prompt_en を直接流用
        try:
            _ip_parts = [h.get("image_prompt_en", "") for h in last_round if h.get("image_prompt_en")]
            image_prompt = ", ".join(_ip_parts)
            if not image_prompt and scene:
                image_prompt = scene
            image_prompt = _apply_char_tags(image_prompt, _scene_char_id)
            image_prompt = _dedup_tags(image_prompt)
        except Exception as e:
            return {"error": f"image prompt (passthrough) failed: {e}"}

    else:
        # current / dedicated: LLM経由でタグ生成
        dialogue_block = "\n".join(
            f"{name_map.get(h.get('character_id', ''), h.get('character_id', ''))}: "
            f"{h.get('content', '').split(': ', 1)[-1]}"
            for h in last_round
        ) if last_round else ""

        scene_line = f"Base scene: {scene}" if scene else ""
        topic_line = f"Session topic: {topic}" if topic else ""
        dialogue_line = f"Recent dialogue (for character count and mood):\n{dialogue_block}" if dialogue_block else ""

        if t2i_prompt_mode == "dedicated":
            # dedicated: 出力制約を強化（thinkingモデル対策）
            if _is_tag_based:
                system_prompt = (
                    f"Scene tag generator for Stable Diffusion. Output comma-separated {_fmt_label} tags ONLY. "
                    "CHARACTER APPEARANCE IS ALREADY SET — DO NOT output hair color, eye color, clothing, body type. "
                    "Output ONLY: setting, background, weather, time of day, lighting, composition, camera angle, "
                    "character count, pose, action, expression/emotion. "
                    "Start with the first tag immediately. No prose, no reasoning."
                )
                user_text = "\n".join(filter(None, [scene_line, topic_line, dialogue_line])) + (
                    f"\n\nIMMEDIATELY output 8-15 scene {_fmt_label} tags, comma-separated. "
                    "SCENE & ENVIRONMENT ONLY — no hair/eye/clothing tags. "
                    "NO explanation. NO reasoning. First token must be a tag."
                )
            else:
                system_prompt = (
                    "Scene description generator for Stable Diffusion. "
                    "Output a concise English visual description of SETTING, LIGHTING, and ACTION ONLY. "
                    "CHARACTER APPEARANCE IS ALREADY SET — do not describe hair, eyes, or clothing. "
                    "No reasoning, no abstract concepts."
                )
                user_text = "\n".join(filter(None, [scene_line, topic_line, dialogue_line])) + (
                    "\n\nIMMEDIATELY output a short English scene description (1-3 sentences). "
                    "Describe setting, lighting, mood, and action only. NO character appearance. "
                    "NO explanation. NO reasoning. Start with the description directly."
                )
            num_predict = 128
        else:
            # current
            if _is_tag_based:
                system_prompt = (
                    f"You are a scene tag generator for Stable Diffusion. "
                    f"Output ONLY {_fmt_label}-style tags, comma-separated. "
                    "CHARACTER APPEARANCE IS ALREADY SET — DO NOT output hair color, eye color, clothing, body type. "
                    "Output ONLY: setting, background, lighting, weather, time of day, composition, "
                    "camera angle, character count, pose, action, expression/emotion. "
                    "Do NOT think out loud. Do NOT explain. Output tags immediately."
                )
                user_text = "\n".join(filter(None, [scene_line, topic_line, dialogue_line])) + (
                    f"\n\nOutput ONLY {_fmt_label}-style scene tags in English, comma-separated. "
                    "SCENE & ENVIRONMENT ONLY — no hair/eye/clothing tags. "
                    "Include: setting, lighting, mood, pose/action, expression. "
                    "No explanation. No reasoning. Tags only."
                )
            else:
                system_prompt = (
                    "You are a scene description generator for Stable Diffusion. "
                    "Output ONLY a concise English description of SETTING, LIGHTING, and ACTION. "
                    "CHARACTER APPEARANCE IS ALREADY SET — do not describe hair, eyes, or clothing. "
                    "Do NOT think out loud. Do NOT explain. Output the description immediately."
                )
                user_text = "\n".join(filter(None, [scene_line, topic_line, dialogue_line])) + (
                    "\n\nOutput ONLY a short English scene description (2-4 sentences). "
                    "Describe setting, lighting, mood, and character action/emotion. NO character appearance. "
                    "No explanation. No reasoning. Visual details only."
                )
            num_predict = 256

        backend_id = req.backend or session.get("backend", DEFAULT_LLM_BACKEND)
        if backend_id not in LLM_BACKENDS:
            backend_id = DEFAULT_LLM_BACKEND

        try:
            chat_fn = LLM_BACKENDS[backend_id]["chat"]
            model = _resolve_model(backend_id)
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ]
            from def_kari.resources.vram_lock import get_vram_lock
            _vram_lock_llm = get_vram_lock()
            if not _vram_lock_llm.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
                raise RuntimeError(f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s")
            try:
                image_prompt = chat_fn(messages, model, json_mode=False, options={"num_predict": num_predict})
            finally:
                _vram_lock_llm.release()
            image_prompt = re.sub(r'#(\w)', r'\1', image_prompt).strip().strip('"').strip("'")
            image_prompt = _apply_char_tags(image_prompt, _scene_char_id)
            if _is_tag_based:
                image_prompt = _dedup_tags(image_prompt)
        except Exception as e:
            return {"error": f"image prompt generation failed: {e}"}

    if not image_prompt:
        return {"error": "empty image prompt"}

    try:
        from def_kari.settings import load_settings
        from def_kari.api.routes.t2i import set_t2i_debug
        settings = load_settings()
        t2i_backend = req.t2i_backend or settings.get("t2i_backend", "")
        if not t2i_backend:
            return {"error": "T2Iバックエンドが未設定です"}
        t2i_model = req.t2i_model or settings.get(f"t2i_model_{t2i_backend}") or None
        workflow = settings.get("comfyui_workflow", "default") if t2i_backend == "comfyui" else ""
        width = int(settings.get("session_t2i_width") or settings.get("t2i_width", 512))
        height = int(settings.get("session_t2i_height") or settings.get("t2i_height", 768))
        from def_kari.models.t2i_profiles import get_quality_settings
        quality_tags, default_neg = get_quality_settings(t2i_model)
        prompt_final = f"{image_prompt}, {quality_tags}" if quality_tags else image_prompt
        t2i_debug = {
            "backend": t2i_backend,
            "model": t2i_model or "",
            "workflow": workflow,
            "t2i_prompt_mode": t2i_prompt_mode,
            "prompt_input": image_prompt,
            "quality_tags": quality_tags,
            "prompt_final": prompt_final,
            "negative_prompt": default_neg,
            "width": width,
            "height": height,
        }
        set_t2i_debug(t2i_debug)
        from def_kari.resources.vram_lock import get_vram_lock
        _vram_lock = get_vram_lock()
        if not _vram_lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
            raise RuntimeError(f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s")
        try:
            image_path = _generate_t2i_image(
                prompt=prompt_final,
                width=width,
                height=height,
                model=t2i_model,
                backend=t2i_backend,
                negative_prompt=default_neg,
                workflow_name=workflow,
            )
        finally:
            _vram_lock.release()
        filename = image_path.split("/")[-1].split("\\")[-1]
        image_url = f"/api/t2i/image/{filename}"
        t2i_debug["url"] = image_url
        set_t2i_debug(t2i_debug)
        session.setdefault("history", []).append({
            "character_id": "_scene_image",
            "content": "",
            "image_url": image_url,
        })
        _autosave(session_id)
        _game_event_bus.emit(session_id, "SESSION_IMAGE", {"url": image_url})
        return {"url": image_url, "prompt": prompt_final}
    except Exception as e:
        return {"error": str(e)}


@router.get("/{session_id}")
def get_session(session_id: str, _auth: dict = Depends(require_participant)):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    return {"session": _session_for_public_json(session)}


class StatSyncRequest(BaseModel):
    character_id: str
    stats: dict  # { stat_name: current_value }


@router.post("/{session_id}/sync_stats")
def sync_stats(session_id: str, req: StatSyncRequest, _auth: dict = Depends(require_keeper)):
    """フロントの runtime stat 変更をセッションに反映する（GMコンテキスト用）。"""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    runtime_stats = session.setdefault("runtime_stats", {})
    runtime_stats[req.character_id] = req.stats
    return {"status": "ok"}


# ── WebSocket エンドポイント ──────────────────────────────────────────

@router.websocket("/{session_id}/ws")
async def ws_endpoint(ws: WebSocket, session_id: str):
    """マルチプレイ用 WebSocket。first-message auth 方式。

    設計判断（S-10, 検討済み）: 接続受理時に Origin ヘッダーを検証していない。
    一般には Cross-Site WebSocket Hijacking (CSWSH) を疑うべき箇所だが、認証は
    Cookie ではなく「接続後5秒以内の first-message で送るJWT」方式であり、
    JWTはブラウザが自動送信するものではなくフロントエンドJSが明示的に送信する
    必要があるため、悪意あるサイトが接続を開いても有効なJWTを保持できず
    実害は限定的と判断し、Origin検証は追加していない。
    """
    await ws.accept()

    # 認証: 接続後5秒以内に {"type":"auth","token":"..."} を受け取る
    try:
        auth_msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
        raw_token = auth_msg.get("token", "")
        if not raw_token:
            raise ValueError("no token")
        jwt_payload = verify_jwt(raw_token)  # JWTError で 4001 に落ちる
        if jwt_payload.get("session_id") != session_id:
            raise ValueError("session mismatch")
    except Exception:
        try:
            await ws.close(code=4001)
        except Exception:
            pass
        return

    sess = _sessions.get(session_id)
    if not sess:
        try:
            await ws.close(code=4004)
        except Exception:
            pass
        return

    sess.setdefault("ws_connections", {})[raw_token] = ws
    _cancel_idle_shutdown(session_id)

    # 参加者（host以外）の再接続を全タブに通知（切断表示からの復帰）。
    # 初回接続時にも飛ぶが、フロント側は connected:true への上書きのみなので無害。
    if raw_token in sess.get("players", {}):
        _rc_participant_id = sess.get("token_to_participant", {}).get(raw_token, raw_token)
        _rc_char_id = sess["players"].get(raw_token, "")
        _game_event_bus.emit(session_id, "PLAYER_RECONNECTED", {
            "participant_id": _rc_participant_id,
            "character_id": _rc_char_id,
        })
        if _rc_char_id:
            _cancel_disconnect_skip(session_id, _rc_char_id)

    # 接続時に現在の状態を送信: 人間ターン待ちなら WAITING_FOR_HUMAN を再送する
    # （ブラウザ変更・リロード・遅延参加でイベントを見逃したタブ向け）
    if not sess.get("lobby_active"):
        _ai_task = sess.get("ai_task")
        _task_idle = _ai_task is None or _ai_task.done()
        if _task_idle:
            _current = _get_current_speaker(sess)
            if _current and _is_human_char(sess, _current):
                await _safe_send(session_id, raw_token, ws, {
                    "type": "WAITING_FOR_HUMAN",
                    "payload": {
                        "character_id": _current,
                        "character_name": sess.get("name_map", {}).get(_current, _current),
                        "round": sess.get("round", 1),
                        "counters": dict(sess.get("counters", {})),
                    },
                })

    # keepalive: Cloudflare の 100 秒タイムアウト対策（固定 30 秒）
    async def _keepalive() -> None:
        try:
            while True:
                await asyncio.sleep(30)
                lock = _ws_send_locks.setdefault(raw_token, asyncio.Lock())
                async with lock:
                    await ws.send_json({"type": "ping"})
        except Exception:
            pass

    keepalive_task = asyncio.create_task(_keepalive())
    try:
        async for msg in ws.iter_json():
            if not _check_ws_rate(session_id, raw_token):
                await _safe_send(session_id, raw_token, ws, {"type": "error", "code": "rate_limit"})
                continue
            if msg.get("type") == "pong":
                continue
            # Phase 2 以降でメッセージハンドラを追加する
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        keepalive_task.cancel()
        _ws_send_locks.pop(raw_token, None)
        sess = _sessions.get(session_id)
        if sess:
            sess["ws_connections"].pop(raw_token, None)
            # /leave で既に除去済み（players からも消えている）なら通知しない。
            # 参加者データは保持したまま切断のみを通知する（退室とは異なり再接続可能）
            if raw_token in sess.get("players", {}):
                _dc_participant_id = sess.get("token_to_participant", {}).get(raw_token, raw_token)
                _dc_char_id = sess["players"].get(raw_token, "")
                _game_event_bus.emit(session_id, "PLAYER_DISCONNECTED", {
                    "participant_id": _dc_participant_id,
                    "character_id": _dc_char_id,
                    "timeout_sec": _disconnect_timeout_sec(),
                })
                # 切断したのが現在のターン担当者なら、タイムアウト後の自動skipタイマーを
                # 起動する（マルチプレイ設計書§3.7）。他キャラのターン中の切断は、
                # そのキャラの番が回ってきた時点で _maybe_schedule_disconnect_skip が
                # 改めて判定する。
                if _dc_char_id and _get_current_speaker(sess) == _dc_char_id:
                    _schedule_disconnect_skip(session_id, _dc_char_id)
            if not sess["ws_connections"]:
                _schedule_idle_shutdown(session_id, delay=300)
