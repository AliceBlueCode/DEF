"""Session認証・認可・レート制限。

JWT発行/検証/失効・`require_host/player/keeper/participant`・招待コード生成/
レート制限・セッション作成レート制限・IP解決・content_policy指紋照合・生成系
エンドポイント向けの汎用レート制限ヘルパー群。`session.py`分割の第二段階
（`session_state.py`に次ぐ）。
"""

import hashlib
import json
import secrets
import time
import datetime
import datetime as _dt
from collections import deque

from fastapi import Header, HTTPException, Request
from jose import jwt as _jwt, JWTError as _JWTError
import uuid as _uuid_mod

from def_kari.safety.audit_log import record_rate_limit_violation
from def_kari.api.routes import session_state as _session_state
from def_kari.api.routes.session_state import _sessions, _ws_send_locks


# ── 生成系エンドポイント向け汎用レート制限 ──────────────────────────────

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


# ── JWT 認証 ─────────────────────────────────────────────────────────

# jti(JWTのユニークID) → 失効理由の有効期限(exp、UTC unixタイムスタンプ)。
# 値はトークン自身のexpをそのまま流用する: exp到来後はverify_jwtのjose.decode自体が
# 期限切れとして拒否するため、それより後までブラックリストに残しておく意味がない。
_revoked_jtis: dict[str, float] = {}
# 0.0ではなく-infにする理由は_autosave_last_cleanupと同じ（session_turn_engine.py参照）。
_revoked_jtis_last_cleanup = {"t": float("-inf")}
_REVOKED_JTIS_CLEANUP_INTERVAL = 600.0  # 10分


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


# ── 招待コード ────────────────────────────────────────────────────────

_INVITE_CHARS_ALPHA = "ABCDEFGHJKLMNPQRSTUVWXYZ"  # O・I除く
_INVITE_CHARS_NUM   = "23456789"                   # 0・1除く
_INVITE_RATINGS     = ["SFW", "R15", "R18", "UNL"]

# invite_code → session_id マッピング
_invite_registry: dict[str, str] = {}
# invite失敗カウント (ip → [timestamp, ...])
_invite_fail_rate: dict[str, deque] = {}
_invite_locked_until: dict[str, float] = {}


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


# ── セッション作成レート制限 ──────────────────────────────────────────
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
    import asyncio
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
            if _session_state._main_loop and _session_state._main_loop.is_running():
                asyncio.run_coroutine_threadsafe(_close_all(), _session_state._main_loop)


# ── 持ち込みキャラクターの検証 ────────────────────────────────────────

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


# ── IP解決 ────────────────────────────────────────────────────────────

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
    import os
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


# ── FastAPI Dependency ────────────────────────────────────────────────

def _token_currently_active(session_id: str, token: str) -> bool:
    """8.30対策: JWTの署名・exp・session_id・roleが正しくても、そのトークンが
    「現在もこのセッションの参加者として登録されているか」（`session["players"]`）を
    最終防波堤として確認する。

    `_revoked_jtis`はプロセスメモリ上のみで永続化されないのに対し、`players`は
    autosave・起動時復元（`_AUTOSAVE_DIR`走査）を通じて永続化される。退室(`/leave`)・
    追放(expel)はどちらも`players`からのトークン削除とrevoke_token()を必ずセットで
    行うため、`players`に無い＝現在有効ではない、という判定は`_revoked_jtis`が
    プロセス再起動で失われても揺らがない。session_id自体が存在しない場合は
    Trueを返し、呼び出し元（各エンドポイント）の既存の404チェックに判定を委ねる。
    """
    session = _sessions.get(session_id)
    if session is None:
        return True
    return token in session.get("players", {})


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
    if not _token_currently_active(session_id, token):
        raise HTTPException(401, "Token is no longer active")
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
    if not _token_currently_active(session_id, token):
        raise HTTPException(401, "Token is no longer active")
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
    if not _token_currently_active(session_id, token):
        raise HTTPException(401, "Token is no longer active")
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
    if not _token_currently_active(session_id, token):
        raise HTTPException(401, "Token is no longer active")
    return payload
