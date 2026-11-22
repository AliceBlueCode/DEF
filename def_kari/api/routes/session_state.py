"""Session共有状態: `_sessions`辞書ほか、複数のsessionモジュールから参照される
モジュールレベルの可変状態をここに集約する。

`session.py`の分割（TODO.md「`session.py`分割の設計」参照）の第一段階。他のどの
機能グループ（auth/ws/persistence/turn_engine/lobby/rules/gameplay/image）からも
参照されうる、本当に横断的な状態のみをここに置く。特定の機能グループにしか
関係しない状態（招待コードのレート制限等）は、そのグループのモジュールに残す。
"""

import asyncio
from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from starlette.requests import HTTPConnection

# ── ルーター ──────────────────────────────────────────────────────────
# `router`/`local_router`はAPIRouterインスタンス（デコレータで内部の routes
# リストにミューテートされる）で、`_sessions`と同じく再代入ではなくミューテートの
# 対象なので、他モジュールから名前importしても安全に共有できる。
# main.py/public_main.pyは`session.router`/`session.local_router`という属性
# アクセスで参照するため、session.py側がここからimportして再エクスポートする
# 限り、それらの参照は変更不要（同一オブジェクトを指す）。
#
# `router`はpublic_main.pyに丸ごとマウントされるため、フル機能アプリ（main.py）
# 専用の操作（ローカル専用エンドポイント: デバッグ・セーブ/ロード）を含めると
# 外部公開されてしまう（8.8「session.router丸ごとマウントに起因する無認証
# エンドポイントの公開漏れ」参照）。main.pyはrouterとlocal_routerの両方を
# マウントし、public_main.pyはrouterのみマウントする。
# ── 手番の口（turn_driver）を持つ卓の関所（差し込み口 1、基本設計書 11.4） ─────────────
# 手番を自分で回すルールシステムの卓では、セッションの状態を変える DEF の操作を**既定で断る**。
# 通すものを、エンドポイントの関数の名前の許可リストで持つ（呼ぶ所を1つずつ並べる方式にしない。
# 後から足された操作が素通りしないようにするため）。ルーターのすべての HTTP の操作がここを通る。
# - そのまま通す: 取得（get_session は visibility を通る）・参加・退室・ホストによる終了・停止
# - 手番の口の handle_request へ回す（関数の頭で `_turn_driver_request` を呼ぶ）: 再開・人間の手番の
#   入力・ホストから GM への指示
# - それ以外: 409
_TURN_DRIVER_PASS = frozenset({
    "get_session", "get_session_credits", "get_session_events",
    "end_session_by_host", "leave_session", "ai_pause",
})
_TURN_DRIVER_HANDLE = frozenset({"ai_resume", "human_turn_action", "inject_keeper_message"})


def _turn_driver_gate(conn: HTTPConnection) -> None:
    if conn.scope.get("type") != "http":
        return  # WS の接続はそのまま通す（配るものは visibility の口が決める）
    session_id = conn.path_params.get("session_id")
    session = _sessions.get(session_id) if session_id else None
    if not session:
        return  # 卓の無い操作（/start・/join など）と、卓が無いとき（各操作が 404 を返す）
    endpoint = getattr(conn.scope.get("endpoint"), "__name__", "")
    if endpoint in _TURN_DRIVER_PASS or endpoint in _TURN_DRIVER_HANDLE:
        return
    from def_kari.trpg import plugin_hooks
    if plugin_hooks.has_capability(session, "turn_driver"):
        raise HTTPException(409, "This rule system runs its own turns; this operation is not used on this table")


router = APIRouter(dependencies=[Depends(_turn_driver_gate)])
local_router = APIRouter(dependencies=[Depends(_turn_driver_gate)])


# ── セッションレジストリ ──────────────────────────────────────────────

_MAX_SESSIONS = __import__("os").environ.get("DEF_MAX_SESSIONS", "1000")
_MAX_SESSIONS = int(_MAX_SESSIONS)
_sessions: "OrderedDict[str, dict]" = OrderedDict()
_last_session_debug: dict = {}


# ── シリアライズ ──────────────────────────────────────────────────────

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


# GET /{session_id}（参加者認証必須、8.24）で外部に公開してよいフィールドのallowlist。
# 8.27対策: 以前はblacklist（`_PUBLIC_EXCLUDED_KEYS`、認証トークン・招待コードのみ除外）
# 方式だったため、npc_state（GM専用情報。`/{session_id}/npc/{npc_id}/state`が
# require_keeperで保護しているのと同じデータが、こちらは無防備に全ロールへ露出していた）・
# player_knowledge・rules/scene（private ruleset本文がそのまま入りうる）等、新フィールド
# 追加のたびに「除外し忘れる」リスクを構造的に抱えていた。フロントエンド
# （SessionTab.tsx）がこのエンドポイントから実際に読むのは`history`/`name_map`/
# `initiative`/`char_colors`（2026-08-16、リロード復帰・公開ポート経由ゲストの
# 名前/色欠落修正で追加。characters一覧APIがローカル専用ポートにしか無く、
# 公開ポート経由のゲストはそちらを読めないための代替経路）。allowlistは実際に
# 必要なフィールド＋ゲーム進行の表示に使う非秘匿のメタデータ（数値カウンタ・
# モードフラグ・ID文字列）に限定し、GM/シナリオ/ルールセット由来の自由記述
# コンテンツ（npc_state・player_knowledge・rules・scene・char_game_sheets・
# skill_pool・skill_values・guest_chars等）は一切含めない。
_PUBLIC_SESSION_KEYS = frozenset({
    "id", "history", "name_map", "initiative", "char_colors",
    "round", "_round_seq", "turn", "action_count", "actions_per_turn",
    "topic", "trpg_mode", "online_mode", "lobby_active", "host_keeper_mode",
    "human_keeper", "waiting_for_gm", "auto_advance", "human_char_ids",
    "keeper_char_id", "keeper_char_name", "max_players",
    "current_scene_index", "scene_round_start", "designated_next",
    "rule_set", "trpg_rulebook", "trpg_scenario", "action_directive_set",
})


def _session_for_public_json(session: dict) -> dict:
    """GETレスポンス専用: allowlist（`_PUBLIC_SESSION_KEYS`）に含まれるフィールドのみの
    コピーを返す。autosave用の`_session_for_json`（全フィールド保持）とは別軸。"""
    return {k: v for k, v in session.items() if k in _PUBLIC_SESSION_KEYS}


# ── WebSocket横断状態 ─────────────────────────────────────────────────
# `_ws_send_locks`はws_endpoint以外（vote_commitのexpel処理・leave_session・
# autosave等）からも参照されるため、ws.py単体ではなくここに置く。

# 接続ごとの送信ロック: 同一WSへの並列 send_json を防ぐ
_ws_send_locks: "dict[str, asyncio.Lock]" = {}

# asyncio メインループ（スレッドプールから broadcast するために保存）
_main_loop: "asyncio.AbstractEventLoop | None" = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """lifespan 起動時に main.py から呼ぶ。スレッドセーフな broadcast に使用。"""
    global _main_loop
    _main_loop = loop
