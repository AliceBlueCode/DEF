"""Session API routes."""

import asyncio
import datetime
import json
import logging
import os
import random
import re
import secrets
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

router = APIRouter()

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
_NON_SERIALIZABLE_KEYS = frozenset({"ws_connections", "ai_task", "idle_shutdown_task", "ws_rate"})


def _session_for_json(session: dict) -> dict:
    """autosave や GET レスポンス用: シリアライズ不可能なフィールドを除いたコピーを返す。"""
    return {k: v for k, v in session.items() if k not in _NON_SERIALIZABLE_KEYS}


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

_revoked_jtis: set[str] = set()

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


def verify_jwt(token: str) -> dict:
    """JWTを検証して payloadを返す。失敗時は JWTError を raise する。"""
    payload = _jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
    if payload.get("jti") in _revoked_jtis:
        raise _JWTError("Token revoked")
    return payload


def revoke_token(token: str) -> None:
    """退室・強制切断時に jti をブラックリストに追加する。"""
    try:
        payload = _jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
        _revoked_jtis.add(payload["jti"])
        sess = _sessions.get(payload.get("session_id", ""))
        if sess:
            sess["ws_connections"].pop(token, None)
    except Exception:
        pass


def _cleanup_revoked_jtis(session_id: str, session: dict | None = None) -> None:
    """セッション終了時に当該セッションの jti をブラックリストから掃除する。

    _end_session が _sessions.pop() した後に呼ぶ場合は session を直接渡す。
    """
    sess = session or _sessions.get(session_id)
    if not sess:
        return
    alive_jtis: set[str] = set()
    for token in list(sess.get("players", {}).keys()):
        try:
            p = _jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
            alive_jtis.add(p["jti"])
        except Exception:
            pass
    _revoked_jtis.difference_update(alive_jtis)


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


def _check_invite_rate(client_ip: str) -> bool:
    """True=許可、False=ロック中 or 制限超過（10回/分、10回失敗で1時間ロック）"""
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


# ── FastAPI Dependency ────────────────────────────────────────────────

from fastapi import Header, HTTPException, Depends, Request


def require_host(authorization: str = Header(...)) -> dict:
    """role == host のみ通す Dependency。"""
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = verify_jwt(token)
    except _JWTError:
        raise HTTPException(401, "Invalid or expired token")
    if payload.get("role") != "host":
        raise HTTPException(403, "Host role required")
    return payload


def require_player(authorization: str = Header(...)) -> dict:
    """role == host / player / gm を通す Dependency（observer は 403）。"""
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = verify_jwt(token)
    except _JWTError:
        raise HTTPException(401, "Invalid or expired token")
    if payload.get("role") not in ("host", "player", "gm"):
        raise HTTPException(403, "Player role required")
    return payload


def require_keeper(authorization: str = Header(...)) -> dict:
    """role == host / gm を通す Dependency（player / observer は 403）。
    オンラインセッションで専任キーパー(gm)がゲーム進行を操作できるようにする。"""
    token = authorization.removeprefix("Bearer ").strip()
    try:
        payload = verify_jwt(token)
    except _JWTError:
        raise HTTPException(401, "Invalid or expired token")
    if payload.get("role") not in ("host", "gm"):
        raise HTTPException(403, "Keeper role required")
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


# ── サーバー自律AIターン ──────────────────────────────────────────

def _get_current_speaker(session: dict) -> str | None:
    """現在のターンのキャラIDを返す。ラウンド境界は % で吸収。"""
    initiative = session.get("initiative", [])
    if not initiative:
        return None
    turn = session.get("turn", 0)
    return initiative[turn % len(initiative)]


def _execute_ai_turn(session_id: str) -> dict:
    """AIターンを1回同期実行する（run_in_executor 用）。"""
    sess = _sessions.get(session_id)
    backend = sess.get("backend", DEFAULT_LLM_BACKEND) if sess else DEFAULT_LLM_BACKEND
    req = SessionNextRequest(session_id=session_id, backend=backend)
    return next_turn(req)


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
        if not current or _is_human_char(session, current):
            # 人間ターン到達をフロントに通知
            if current:
                # _get_current_speaker は turn % len で折り返すが round/turn は更新しない。
                # ラウンド境界を越えていた場合はここで正規化する。
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
            _game_event_bus.emit(session_id, "AI_ERROR", {"error": result["error"]})
            return
        if result.get("waiting_for_human"):
            _game_event_bus.emit(session_id, "WAITING_FOR_HUMAN", {
                "character_id": result.get("character_id", ""),
                "character_name": result.get("character_name", ""),
                "round": result.get("round", 1),
                "counters": dict(result.get("counters", session.get("counters", {}))),
            })
            return
        _game_event_bus.emit(session_id, "AI_TURN_COMPLETED", result)
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
    if tasks_to_cancel:
        await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
    for ws in list(session.get("ws_connections", {}).values()):
        try:
            await ws.close(code=1000)
        except Exception:
            pass
    session["ws_connections"].clear()
    for token in list(session.get("players", {}).keys()):
        _ws_send_locks.pop(token, None)
    # 招待コードのグローバルレジストリからも削除
    for code in list(session.get("invite_codes", {}).keys()):
        _invite_registry.pop(code, None)
    _cleanup_revoked_jtis(session_id, session=session)


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
_DIRECTIVE_DIRS = [
    _BASE / "data" / "public" / "action_directives",
    _BASE / "data" / "private" / "action_directives",
]
_SESSION_HISTORY_DIRS = [
    _BASE / "data" / "public" / "session_history",
    _BASE / "data" / "private" / "session_history",
]
_AUTOSAVE_DIR = _BASE / "data" / "private" / "session_autosave"
_SAFE_FILENAME_RE = re.compile(r'^[A-Za-z0-9_\-]+\.json$')


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


def _delete_autosave(session_id: str) -> None:
    try:
        (_AUTOSAVE_DIR / f"{session_id}.json").unlink(missing_ok=True)
    except Exception:
        pass


# ── 起動時に進行中セッションを復元 ──────────────────────────────
try:
    if _AUTOSAVE_DIR.is_dir():
        for _f in sorted(_AUTOSAVE_DIR.iterdir()):
            if _f.suffix == ".json":
                try:
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


def _load_action_directives() -> dict:
    directives: dict = {}
    for d in _DIRECTIVE_DIRS:
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


@router.get("/action-directives")
def get_action_directives():
    directives = _load_action_directives()
    return {
        "directives": [
            {"id": did, "label": d.get("label", did), "rating": d.get("rating", "general"), "recommended_for": d.get("recommended_for", [])}
            for did, d in directives.items()
        ]
    }


def _load_session_rules() -> dict:
    rules = {}
    for d in _RULE_DIRS:
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
def get_session_rules():
    rules = _load_session_rules()
    return {
        "rules": [
            {"id": rid, "label": r.get("label", rid)}
            for rid, r in rules.items()
        ]
    }


@router.get("/rules/{rule_id}")
def get_session_rule_detail(rule_id: str):
    if not re.match(r'^[A-Za-z0-9_\-]+$', rule_id):
        return {"error": "Invalid rule ID"}
    for d in _RULE_DIRS:
        path = d / f"{rule_id}.json"
        if path.exists():
            try:
                return {"content": path.read_text(encoding="utf-8"), "id": rule_id}
            except OSError as e:
                return {"error": str(e)}
    return {"error": f"Rule '{rule_id}' not found"}


class SaveRuleRequest(BaseModel):
    content: str


@router.put("/rules/{rule_id}")
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


class SessionHumanMessage(BaseModel):
    session_id: str
    message: str


class KeeperMessageRequest(BaseModel):
    text: str


@router.post("/start")
def start_session(req: SessionStartRequest):
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
        _sessions.popitem(last=False)
    _rule_data = _load_session_rules().get(req.rule_set, {})
    rules = _rule_data.get("rules", [])
    scene = _rule_data.get("scene", "")
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
        "max_players": 0,      # ロビー設定で上書き
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
    if auth.get("session_id") != session_id:
        raise HTTPException(403, "Token session mismatch")
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
def get_available_slots(req: AvailableSlotsRequest):
    """招待コードで入れるセッションの人間スロット一覧を返す（参加前プレビュー）。"""
    code = req.invite_code.strip().upper()
    session_id = _invite_registry.get(code)
    if not session_id:
        raise HTTPException(404, "Invalid invite code")
    sess = _sessions.get(session_id)
    if not sess:
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
    }


class JoinRequest(BaseModel):
    invite_code: str
    claim_char_id: str = ""   # 既存人間スロットを引き継ぐ
    character_json: dict = {} # オンラインセッション: キャラJSON持ち込み
    join_as_gm: bool = False  # オンラインセッション: GM/キーパーとして参加


@router.post("/join")
def join_session(req: JoinRequest, request: Request):
    """招待コードでセッションに参加し、player JWT を返す。"""
    client_ip = request.client.host if request.client else "unknown"
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

    # 参加人数チェック（オブザーバー除く・ホスト込みでカウント）
    if req.character_json or req.claim_char_id:
        max_p = sess.get("max_players", 0)
        if max_p > 0:
            host_token = sess.get("host_token", "")
            # ホスト(1) + キャラ持ち参加者 = 実際の参加人数
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
        role = "player"
        char_id = req.claim_char_id
        display_name = sess.get("name_map", {}).get(char_id, char_id)
    elif req.character_json:
        # オンラインセッション: 参加者がキャラJSONを持ち込む
        role = "player"
        char_id = f"guest_{_uuid_mod.uuid4().hex[:8]}"
        char_data = dict(req.character_json)
        char_data["id"] = char_id
        char_data["player_type"] = "human"
        sess.setdefault("guest_chars", {})[char_id] = char_data
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


class AiTakeoverRequest(BaseModel):
    character_id: str


@router.post("/{session_id}/ai_takeover")
def ai_takeover(session_id: str, req: AiTakeoverRequest, auth: dict = Depends(require_host)):
    """退室したプレイヤーのキャラ枠を AI に引き継ぐ（ホストのみ）。"""
    if auth.get("session_id") != session_id:
        raise HTTPException(403, "Token session mismatch")
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


@router.post("/next")
def next_turn(req: SessionNextRequest):
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

    history = []
    for h in session["history"][-20:]:
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
    _vram_lock.acquire()
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


@router.post("/{session_id}/end")
async def end_session_by_host(session_id: str, auth: dict = Depends(require_host)):
    """ホストがセッションを明示的に終了する。参加者全員に SESSION_ENDED を通知してから後片付けする。"""
    if auth.get("session_id") != session_id:
        raise HTTPException(403, "Token session mismatch")
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
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
    if auth.get("session_id") != session_id:
        raise HTTPException(403, "Token session mismatch")
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    sess["host_keeper_mode"] = is_keeper
    return {"ok": True, "host_keeper_mode": is_keeper}


@router.post("/{session_id}/lobby_config")
def set_lobby_config(session_id: str, req: LobbyConfigRequest, auth: dict = Depends(require_host)):
    """ロビー設定を更新する（最大プレイヤー数・ホストキャラ）。セッション開始前にホストが呼ぶ。"""
    if auth.get("session_id") != session_id:
        raise HTTPException(403, "Token session mismatch")
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
    return {
        "status": "ok",
        "max_players": sess["max_players"],
        "initiative": sess["initiative"],
    }


class LobbyAIRequest(BaseModel):
    character_id: str


@router.post("/{session_id}/lobby/add_ai")
def lobby_add_ai(session_id: str, req: LobbyAIRequest, auth: dict = Depends(require_host)):
    """ロビーに AI キャラクターを追加する（ホストのみ）。"""
    if auth.get("session_id") != session_id:
        raise HTTPException(403, "Token session mismatch")
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    if not sess.get("lobby_active"):
        raise HTTPException(409, "Session already started")
    char_id = req.character_id
    if char_id in sess["initiative"]:
        raise HTTPException(409, "Already in initiative")
    profiles = load_profiles()
    char = get_character(char_id, profiles)
    if not char:
        raise HTTPException(404, "Character not found")
    if char.get("player_type") == "human":
        raise HTTPException(400, "Cannot add human character as AI slot")
    sess["initiative"].append(char_id)
    sess["name_map"][char_id] = char.get("name", char_id)
    _autosave(session_id)
    _game_event_bus.emit(session_id, "LOBBY_UPDATE", {
        "initiative": sess["initiative"],
        "name_map": dict(sess["name_map"]),
    })
    return {"status": "ok", "initiative": sess["initiative"], "name_map": dict(sess["name_map"])}


@router.post("/{session_id}/lobby/remove_ai")
def lobby_remove_ai(session_id: str, req: LobbyAIRequest, auth: dict = Depends(require_host)):
    """ロビーから AI キャラクターを削除する（ホストのみ）。"""
    if auth.get("session_id") != session_id:
        raise HTTPException(403, "Token session mismatch")
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


@router.post("/human")
def human_message(req: SessionHumanMessage):
    session = _sessions.get(req.session_id)
    if not session:
        return {"error": "Session not found"}
    current = _get_current_speaker(session)
    char_name = session.get("name_map", {}).get(current, current) if current else "Player"
    session["history"].append({
        "role": "user",
        "content": req.message,
        "character_id": current or "human",
        "emotion": "",
    })
    _game_event_bus.emit(req.session_id, "HUMAN_TURN_COMPLETED", {
        "character_id": current or "human",
        "character_name": char_name,
        "text": req.message,
        "emotion": "",
        "tags": [],
    })
    _autosave(req.session_id)
    return {"status": "ok"}


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
    _keeper_lock.acquire()
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


class JudgmentAllocateRequest(BaseModel):
    character_id: str
    stat: str
    backend: str = DEFAULT_LLM_BACKEND


@router.post("/{session_id}/judgment/allocate")
def judgment_allocate(session_id: str, req: JudgmentAllocateRequest):
    """スキル値未設定の判定でキャラAIにポイント配分を決定させる。

    配分値をセッションの skill_values に書き込み、skill_pool から減算する。
    スキル値が既に設定済みの場合はLLMを呼ばずそのまま返す。
    """
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    skill_values = session.setdefault("skill_values", {})
    char_skills = skill_values.setdefault(req.character_id, {})

    if req.stat in char_skills:
        return {
            "character_id": req.character_id,
            "stat": req.stat,
            "allocated": char_skills[req.stat],
            "skill_pool": session.get("skill_pool", {}).get(req.character_id, 0),
            "already_set": True,
        }

    skill_pool = session.setdefault("skill_pool", {})
    pool = skill_pool.get(req.character_id, 0)
    if pool <= 0:
        return {
            "character_id": req.character_id,
            "character_name": session.get("name_map", {}).get(req.character_id, req.character_id),
            "stat": req.stat,
            "allocated": 0,
            "skill_pool": 0,
            "already_set": False,
            "label": "",
        }
    max_alloc = min(100, pool)
    name_map = session.get("name_map", {})
    char_name = name_map.get(req.character_id, req.character_id)

    _s = load_settings()
    _lang = _s.get("user_language", "ja") or "ja"

    recent = "\n".join(
        h["content"] for h in session.get("history", [])[-6:]
        if h.get("content")
    )

    if _lang == "ja":
        alloc_prompt = (
            f"あなたは「{req.stat}」のスキル判定を行います。\n"
            f"スキルポイントプール残量: {pool}点\n"
            f"今回の最大配分: {max_alloc}点（上限100点）\n"
            f"最近の状況:\n{recent}\n\n"
            f"何点配分しますか？ 0〜{max_alloc}の整数のみ答えてください。数字以外は不要です。"
        )
    else:
        alloc_prompt = (
            f"You are making a '{req.stat}' skill check.\n"
            f"Skill point pool remaining: {pool}\n"
            f"Maximum allocation this check: {max_alloc} (cap 100)\n"
            f"Recent context:\n{recent}\n\n"
            f"How many points do you allocate? Answer with an integer 0–{max_alloc} only."
        )

    profiles = load_profiles()
    char = get_character(req.character_id, profiles)
    backend_id = session.get("char_backends", {}).get(req.character_id) or req.backend
    if backend_id not in LLM_BACKENDS:
        backend_id = DEFAULT_LLM_BACKEND

    allocated = 0
    try:
        chat_fn = LLM_BACKENDS[backend_id]["chat"]
        model = _resolve_model(backend_id)
        persona = (char or {}).get("persona_description", "")
        messages = [
            {"role": "system", "content": persona} if persona else
            {"role": "system", "content": "You are a TRPG character deciding skill point allocation."},
            {"role": "user", "content": alloc_prompt},
        ]
        from def_kari.resources.vram_lock import get_vram_lock
        _vl = get_vram_lock()
        _vl.acquire()
        try:
            reply = chat_fn(messages, model, json_mode=False, options={"num_predict": 16})
        finally:
            _vl.release()
        import re as _re
        _m = _re.search(r'\d+', reply or "")
        allocated = int(_m.group()) if _m else 0
        allocated = max(0, min(max_alloc, allocated))
    except Exception:
        allocated = 0

    char_skills[req.stat] = allocated
    skill_pool[req.character_id] = max(0, pool - allocated)

    _label = f"🎯 {char_name}: {req.stat} に{allocated}点配分（プール残{skill_pool[req.character_id]}点）"
    if _lang != "ja":
        _label = f"🎯 {char_name}: allocated {allocated} pts to {req.stat} (pool remaining: {skill_pool[req.character_id]})"

    session["history"].append({
        "role": "user",
        "content": _label,
        "character_id": req.character_id,
        "skill_allocation": {"stat": req.stat, "allocated": allocated},
    })
    _autosave(session_id)
    return {
        "character_id": req.character_id,
        "character_name": char_name,
        "stat": req.stat,
        "allocated": allocated,
        "skill_pool": skill_pool[req.character_id],
        "already_set": False,
        "label": _label,
    }


class JudgmentRollRequest(BaseModel):
    character_id: str
    stat: str
    roll: int
    stat_value: int = 0
    success_text: str = ""
    failure_text: str = ""


@router.post("/{session_id}/judgment/roll")
def judgment_roll(session_id: str, req: JudgmentRollRequest):
    """ダイスロール結果を受け取り、成否判定してセッション履歴に注入する。

    stat_value が 0 の場合はキャラシートから自動取得する。
    成功条件: roll <= stat_value
    """
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    stat_value = req.stat_value
    if stat_value == 0:
        # skill_values（セッション中に配分済み）を優先
        _sv = session.get("skill_values", {}).get(req.character_id, {})
        if req.stat in _sv:
            stat_value = _sv[req.stat]
        else:
            # フォールバック: キャラシートのstat値
            _cgs = session.get("char_game_sheets", {})
            _sheet_id = _cgs.get(req.character_id, "")
            if _sheet_id:
                _profiles = load_profiles()
                _char = get_character(req.character_id, _profiles)
                if _char:
                    stat_value = (
                        _char.get("game_rules_sheets", {})
                        .get(_sheet_id, {})
                        .get("stats", {})
                        .get(req.stat, {})
                        .get("current", 0)
                    )

    success: bool | None = (req.roll <= stat_value) if stat_value > 0 else None

    name_map = session.get("name_map", {})
    char_name = name_map.get(req.character_id, req.character_id)

    _s = load_settings()
    _lang = _s.get("user_language", "ja") or "ja"

    if _lang == "ja":
        if success is None:
            result_text = f"🎲 {char_name}: {req.stat}判定 出目{req.roll}"
        elif success:
            outcome = req.success_text or "成功"
            result_text = f"🎲 {char_name}: {req.stat}判定 出目{req.roll}/{stat_value} → 成功（{outcome}）"
        else:
            outcome = req.failure_text or "失敗"
            result_text = f"🎲 {char_name}: {req.stat}判定 出目{req.roll}/{stat_value} → 失敗（{outcome}）"
    else:
        if success is None:
            result_text = f"🎲 {char_name}: {req.stat} check roll {req.roll}"
        elif success:
            outcome = req.success_text or "Success"
            result_text = f"🎲 {char_name}: {req.stat} {req.roll}/{stat_value} → Success ({outcome})"
        else:
            outcome = req.failure_text or "Failure"
            result_text = f"🎲 {char_name}: {req.stat} {req.roll}/{stat_value} → Failure ({outcome})"

    session["history"].append({
        "role": "user",
        "content": result_text,
        "character_id": req.character_id,
        "judgment": {
            "stat": req.stat,
            "roll": req.roll,
            "stat_value": stat_value,
            "success": success,
        },
    })
    _autosave(session_id)
    return {
        "character_id": req.character_id,
        "character_name": char_name,
        "stat": req.stat,
        "roll": req.roll,
        "stat_value": stat_value,
        "success": success,
        "result_text": result_text,
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
    """人間プレイヤーのターンアクション（send / extend / skip）。"""
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
        counters[current_char_id] = counters.get(current_char_id, 0) + 1
        session["turn"] = turn + 1
        session["action_count"] = 0
        _autosave(session_id)
        _game_event_bus.emit(session_id, "HUMAN_ACTION", {
            "character_id": current_char_id,
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
            "character_id": current_char_id,
            "character_name": char_name,
            "round": session["round"],
            "counters": dict(counters),
        }

    if not req.text.strip():
        return {"error": "text required"}

    session["history"].append({
        "role": "assistant",
        "content": f"{char_name}: {req.text}",
        "character_id": current_char_id,
        "emotion": "neutral",
        "tags": [],
    })

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
        }


@router.post("/{session_id}/vote/deliberate")
def vote_deliberate(session_id: str, req: VoteRequest, _auth: dict = Depends(require_player)):
    """弁明ラウンド: 全 AI キャラが意見を述べてセッションに保存し、結果を返す。"""
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
            _delib_lock.acquire()
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
            if result.get("success") and result.get("result"):
                parsed = result["result"]
                dialogue = parsed.get("dialogue", "")
                emotion = parsed.get("emotion", "neutral")
            if not dialogue:
                dialogue = _sp("no_deliberation", _v_lang) or "(弁明なし)"
        except Exception:
            dialogue = _sp("no_deliberation", _v_lang) or "(弁明なし)"
            emotion = "neutral"

        session["history"].append({
            "role": "assistant",
            "content": f"{char_name}: {dialogue}",
            "character_id": char_id,
            "emotion": emotion,
            "tags": [],
        })
        deliberations.append({
            "character_id": char_id,
            "character_name": char_name,
            "text": dialogue,
            "emotion": emotion,
        })
        session["_pending_vote"]["deliberation_texts"][char_id] = dialogue

    _autosave(session_id)
    return {"deliberations": deliberations, "counters": dict(counters)}


@router.post("/{session_id}/vote/commit")
async def vote_commit(session_id: str, req: VoteCommitRequest, _auth: dict = Depends(require_player)):
    """キーパー票を受け取り、AI票と合算して集計・効果適用する。"""
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
            _vram_lock.acquire()
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
                _vram_lock.acquire()
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

    if passed:
        if vote_type == "topic_change" and detail:
            session["topic"] = detail
        elif vote_type == "expel" and target_id:
            session["initiative"] = [c for c in initiative if c != target_id]

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

    ended = passed and vote_type == "end_session"
    if ended:
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
def get_session_events(session_id: str):
    """セッションのゲームロジックイベントログを返す（Observer Agent用）。"""
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
def get_npc_state(session_id: str, npc_id: str):
    """NPC の現在の動的状態を返す（GM確認用）。"""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "session not found"}
    npc_state = session.get("npc_state", {})
    return {"npc_id": npc_id, "state": npc_state.get(npc_id, {"knowledge": [], "relationship": {}})}


@router.get("/debug")
def get_session_debug():
    return _last_session_debug


@router.get("/saved")
def list_saved_sessions():
    files = list_session_mode_files()
    result = []
    for f in files:
        meta = f.get("metadata", {})
        result.append({
            "filename": Path(f["path"]).name,
            "session_id": f["session_id"],
            "topic": meta.get("topic", ""),
            "saved_at": meta.get("saved_at", ""),
            "round": meta.get("round", 1),
            "character_names": list(meta.get("name_map", {}).values()),
            "trpg_scenario_title": meta.get("trpg_scenario_title", ""),
            "private": f.get("private", False),
        })
    result.sort(key=lambda x: x["saved_at"], reverse=True)
    return {"sessions": result}


class SessionLoadRequest(BaseModel):
    filename: str


@router.delete("/saved/{filename}")
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


@router.post("/load")
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
    if len(_sessions) >= _MAX_SESSIONS:
        _sessions.popitem(last=False)
    _sessions[new_id] = session
    return {
        "session_id": new_id,
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
def generate_session_image(session_id: str, req: SessionGenerateImageRequest, _auth: dict = Depends(require_player)):
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
            _vram_lock_llm.acquire()
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
        _vram_lock.acquire()
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
def get_session(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    return {"session": _session_for_json(session)}


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
    """マルチプレイ用 WebSocket。first-message auth 方式。"""
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
            if not sess["ws_connections"]:
                _schedule_idle_shutdown(session_id, delay=300)
