"""Sessionのターン進行エンジン: AI自律ターン・next_turn/human_turn_action/retake/skip/
ai_pause/ai_resume・WebSocketエンドポイント。

`session.py`分割の最終モジュール（他の全モジュールが依存の少ない側から先に
抽出済みのため、循環importの懸念なくここに残った内容をまとめて移動する）として
作られたが、その後さらに以下の2モジュールへ分離した（TODO.md「session_turn_engine.py
のさらなる分割」参照）:
- `session_turn_media.py`: 挿絵・TTS自動生成（ターン進行ロジックへの依存を持たない）
- `session_turn_disconnect.py`: 切断タイムアウト検知・自動skipスケジューリング
  （`_apply_skip`のみturn_engine側に依存が残るため遅延import）
"""

import asyncio
import json
import logging
import os
import re

_log = logging.getLogger("def.session")


from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from def_kari.characters import load_profiles, get_character
from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.gm.player_agent import _player_agent
from def_kari.image_prompt.emotion_tags import apply_emotion_tags
from def_kari.settings import load_settings
from def_kari.gm.context_builder import (
    load_trpg_rulebook as _load_trpg_rulebook,
    load_trpg_scenario as _load_trpg_scenario,
    build_for_player as _build_for_player,
    build_session_context as _build_session_context,
    build_turn_instruction as _build_turn_instruction,
)
from def_kari.safety.content_filter import contains_blocked_content

# router/local_routerはsession_state.pyへ抽出済み（session.py分割）。他の全ルート
# ホストモジュール（auth/ws/persistence/lobby/rules/gameplay/image）がこれを共有
# import して自分のエンドポイントを登録できるようにするため、依存の少ない
# session_state.py側に置く。main.py/public_main.pyの`session.router`属性アクセスは
# 同一オブジェクトを指すためこのまま動作する。
from def_kari.api.routes.session_state import router

_LANG_LABELS = {
    "ja": "日本語", "en": "English", "zh": "中文",
    "ko": "한국어", "es": "Español", "fr": "Français", "de": "Deutsch",
}




# session_state.pyへ抽出済み（session.py分割・第一段階）。他のsessionモジュールとの
# 共有を前提に、`_sessions`辞書・シリアライズ関連の定義はそちらが正本。
from def_kari.api.routes.session_state import _sessions


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
# `_ws_send_locks`もsession_state.pyへ抽出済み（vote_commit・leave_session・
# autosave等、ws以外からも参照されるため）。
from def_kari.api.routes.session_state import _ws_send_locks


# session_ws.pyへ抽出済み（session.py分割）。未認証WS接続の同時数制限・
# 安全な送信・全接続への配信はそちらが正本。
from def_kari.api.routes.session_ws import (
    _try_acquire_ws_pending_auth_slot,
    _release_ws_pending_auth_slot,
    _safe_send,
)

# session_auth.pyへ抽出済み（session.py分割・第二段階）。
from def_kari.api.routes.session_auth import _check_ws_rate


# session_auth.pyへ抽出済み（session.py分割・第二段階）。JWT発行/検証/失効・
# 招待コード生成/レート制限・require_*等はそちらが正本。
from def_kari.api.routes.session_auth import verify_jwt


def _is_human_char(session: dict, char_id: str, profiles: dict | None = None) -> bool:
    """セッション内で人間扱いかどうかを返す。

    human_char_ids（Phase 3以降）に含まれていれば人間。
    未設定の場合は profiles の player_type にフォールバック。

    以前はguest_chars（持ち込みキャラ）を無条件に人間扱いするフォールバックが
    別途あったが、join_session（session_lobby.py）はcharacter_json持ち込み時
    必ずrole="player"を割り当て、その直後に同じ関数内でhuman_char_idsへも
    追加している（human_char_idsとguest_charsは常に対で揃う）ため、実質的に
    完全な重複だった。しかもこのフォールバックはhuman_char_idsからの明示的な
    除去（ai_takeover・投票expelの「AIに引き継ぐ」）を無視して常にTrueを返し
    続けてしまい、持ち込みキャラに対するAI引き継ぎ機能そのものを無効化する
    実害があった（2026-08-22、投票expelでAI引き継ぎを選んでもセッションが
    進まなくなる不具合として発覚——原因はAIターン再開そのものではなく、
    ここで対象がずっと人間のまま判定され続けていたこと）。
    """
    if char_id in session.get("human_char_ids", []):
        return True
    if profiles is None:
        profiles = load_profiles()
    char = get_character(char_id, profiles)
    return bool(char and char.get("player_type") == "human")


# session_auth.pyへ抽出済み（session.py分割・第二段階）。招待コード・
# セッション作成レート制限・セッション追い出し・キャラJSON検証・IP解決・
# require_*等はそちらが正本。
from fastapi import HTTPException, Depends
from def_kari.api.routes.session_auth import (
    _invite_registry,
    _resolve_client_ip,
    require_player,
    require_keeper,
)


# vram_lockは他の生成処理（LLM/T2I/TTS）と共有のグローバルシングルトン。取得元が
# 増えるほど「誰かが握ったまま長時間返ってこない」場合の影響範囲が広がるため、
# バックグラウンド生成系は無期限ブロックせずタイムアウトで諦める（fail-silent）。
# テスト環境でLLM呼び出しが未モックのままvram_lockを握り続け、後発のTTS取得が
# デッドロックした事例があったため導入（2026-08-02）。
# 環境変数で上書き可能にしているのはテスト実行時間の短縮用（モックし忘れを
# 60秒待たされず即座に検出できるようにするため）。本番の挙動自体は変えない。
_VRAM_LOCK_TIMEOUT_SECONDS = float(os.environ.get("DEF_VRAM_LOCK_TIMEOUT", "60"))


# ── サーバー自律AIターン ──────────────────────────────────────────

def _get_current_speaker(session: dict) -> str | None:
    """現在のターンのキャラIDを返す。ラウンド境界は % で吸収。"""
    initiative = session.get("initiative", [])
    if not initiative:
        return None
    turn = session.get("turn", 0)
    return initiative[turn % len(initiative)]


def _mark_spoken_and_check_round_complete(session: dict, char_id: str) -> bool:
    """指定キャラがこのラウンドで発言/skip済みであることを記録し、initiativeの
    全員が出そろったらTrueを返す（このラウンドの発言済み集合はTrue時にリセットする）。

    以前はフロントエンド側で「initiative配列の末尾のキャラが喋ったか」という
    ヒューリスティックのみでキーパーの発言タイミングを判定していたが、指名
    （designate、`session["turn"] = initiative.index(designated)`で配列順を
    無視して直接ジャンプする）が絡むと、配列末尾のキャラが一度もそのラウンド中に
    発言しないまま次ラウンドへ巻き戻ることがあり、そのラウンドのキーパー発言が
    何のエラーも無く握り潰されていた（2026-08-23、実機で発覚）。initiativeの
    並び順・turnのモジュロ演算に依存しない、サーバー側の権威データとして
    「誰が発言済みか」の集合を管理する。

    戻り値がTrueの回にサーバーが払い出す`_round_seq`（呼び出し側で加算）を
    フロントの重複発火ガードに使う想定（`session["round"]`自体はこの判定とは
    独立して別経路で遅延更新されるため、ラウンド境界の識別子としては使えない）。
    """
    spoken: list = session.setdefault("_round_spoken", [])
    if char_id not in spoken:
        spoken.append(char_id)
    initiative = session.get("initiative", [])
    if initiative and set(initiative) <= set(spoken):
        session["_round_spoken"] = []
        session["_round_seq"] = session.get("_round_seq", 0) + 1
        return True
    return False


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
    round_completed = _mark_spoken_and_check_round_complete(session, char_id)
    _autosave(session_id)
    _game_event_bus.emit(session_id, "HUMAN_ACTION", {
        "character_id": char_id,
        "character_name": char_name,
        "text": "",
        "action": "skip",
        "counters": dict(counters),
        "round_completed": round_completed,
        "round_seq": session.get("_round_seq", 0),
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
        "round_completed": round_completed,
        "round_seq": session.get("_round_seq", 0),
    }


# session_turn_disconnect.pyへ抽出済み（session_turn_engine.pyのさらなる分割）。
# 切断タイムアウト検知・自動skipスケジューリングはそちらが正本。
from def_kari.api.routes.session_turn_disconnect import (
    _disconnect_timeout_sec,
    _schedule_disconnect_skip,
    _cancel_disconnect_skip,
    _maybe_schedule_disconnect_skip,
)


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


# session_turn_media.pyへ抽出済み（session_turn_engine.pyのさらなる分割）。
# ターン結果の挿絵・TTS自動生成、人間プレイヤー発言のTTSバックグラウンド合成は
# そちらが正本（ターン進行ロジックへの依存を持たない自己完結モジュールのため）。
from def_kari.api.routes.session_turn_media import _maybe_generate_turn_media, _start_background_tts


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


from def_kari.api.routes.session_persistence import _autosave

from def_kari.api.routes.session_rules import _load_action_directives

from def_kari.api.routes.session_lobby import _schedule_idle_shutdown, _cancel_idle_shutdown

from def_kari.api.routes.session_image import _resolve_model


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


class SessionNextRequest(BaseModel):
    session_id: str
    backend: str = DEFAULT_LLM_BACKEND
    model: str = ""


def _resolve_turn_start(session: dict, req: SessionNextRequest):
    """ターン開始時の解決: ラウンド繰り上げ・GM指名の適用・発言力マイナス時の
    強制スキップ・人間ターンの入力待ち判定（`next_turn`から切り出し、2026-08-15、
    `session.py`分割・第二段階）。

    戻り値は `(early_result, ctx)` の2要素タプル。強制スキップ/人間待ちで即座に
    返すべき場合は `early_result` にレスポンス辞書、`ctx` は`None`。通常続行の
    場合は `early_result` が`None`、`ctx`に以降の処理へ渡す値一式
    （current_char_id・turn・counters・profiles・char・backend_id・model・
    _skip_gen_before）を持つ辞書を返す。
    """
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
        }, None

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
        }, None

    char_backends = session.get("char_backends", {})
    backend_id = char_backends.get(current_char_id) or req.backend or session.get("backend", DEFAULT_LLM_BACKEND)
    if backend_id not in LLM_BACKENDS:
        backend_id = DEFAULT_LLM_BACKEND
    model = _resolve_model(backend_id, req.model)

    return None, {
        "current_char_id": current_char_id,
        "turn": turn,
        "counters": counters,
        "profiles": profiles,
        "char": char,
        "backend_id": backend_id,
        "model": model,
        "_skip_gen_before": _skip_gen_before,
    }


def _build_recent_history(session: dict, current_char_id: str, name_map: dict) -> list[dict]:
    """直近履歴をLLM入力用（本人はassistant、他キャラは`[名前] `プレフィックス付きuser）に
    整形する（`next_turn`から切り出し、2026-08-15、`session.py`分割・第二段階）。

    performative系（漫才・落語等）は「直近のネタ/演目」に集中させたいのと、履歴が
    育つほど応答が長文化していく傾向を抑えるため、discussion系より短い窓に絞る
    （2026-08-10）。
    """
    history_window = 8 if session.get("style") == "performative" else 20
    history = []
    for h in session["history"][-history_window:]:
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
    return history


def _resolve_ai_action(
    session: dict, req: SessionNextRequest, current_char_id: str, turn: int, counters: dict,
    initiative: list, name_map: dict, speaker_name: str, backend_id: str, model: str,
    char: dict, user_lang: str,
):
    """TRPGモード Round>=2 のAI行動選択（none/skip/vote/designate/extend）と、
    各選択肢の発言力消費・状態反映を行う（`next_turn`から切り出し、2026-08-15、
    `session.py`分割・第二段階）。

    戻り値は `(early_result, ai_action, designated_target_name)` の3要素タプル。
    skip・vote（発言力3以上）は即座にレスポンスを返すべき操作のため、その場合は
    `early_result`にレスポンス辞書を入れて返す（`next_turn`はこれを見て即returnする）。
    それ以外は`early_result`が`None`で、解決済みの`ai_action`辞書
    （designate/extend不成立時は`{"action": "none"}`に落とされる）と、
    designateが成立した場合のみ非空の`designated_target_name`を返す。
    """
    ai_action: dict = {"action": "none"}
    designated_target_name = ""
    if session.get("trpg_mode") and session["round"] >= 2:
        ai_action = _ai_action_select(
            backend_id, model, char,
            current_char_id,
            counters.get(current_char_id, 0),
            session["round"], session["history"],
            initiative, name_map, speaker_name, user_lang,
        )
        _log.info("[action] %s chose: %s", speaker_name, ai_action.get("action"))

    if ai_action["action"] == "skip":
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
        }, ai_action, designated_target_name

    if ai_action["action"] == "vote":
        _cur = counters.get(current_char_id, 0)
        if _cur >= 3:
            counters[current_char_id] = 0
            _autosave(req.session_id)
            return {
                "action": "vote_proposal",
                "character_id": current_char_id,
                "character_name": name_map.get(current_char_id, current_char_id),
                "vote_type": ai_action.get("vote_type", "topic_change"),
                "vote_detail": ai_action.get("vote_detail", ""),
                "proposer_text": ai_action.get("reason", ""),
                "round": session["round"],
                "counters": dict(counters),
            }, ai_action, designated_target_name
        else:
            ai_action["action"] = "none"

    if ai_action["action"] == "designate":
        _target_name = ai_action.get("target_name", "")
        _target_id = next((c for c in initiative if name_map.get(c, c) == _target_name), None)
        _cur = counters.get(current_char_id, 0)
        if _target_id and _target_id != current_char_id and _cur >= 1:
            counters[current_char_id] = _cur - 1
            session["designated_next"] = _target_id
            designated_target_name = _target_name
        else:
            ai_action["action"] = "none"

    if ai_action["action"] == "extend":
        _cur = counters.get(current_char_id, 0)
        if _cur >= 1:
            counters[current_char_id] = _cur - 1
        else:
            ai_action["action"] = "none"

    return None, ai_action, designated_target_name


def _build_turn_prompt_context(
    session: dict, current_char_id: str, char: dict, initiative: list, name_map: dict,
    profiles: dict, speaker_name: str, topic: str, rules: list, action_count: int,
    other_names: list, user_lang: str,
) -> tuple[str, str, bool]:
    """LLMに渡すセッション文脈（同基底衝突アンカー文・死者視点の注入込み）と、
    毎ターンの指示文を構築する（`next_turn`から切り出し、2026-08-15、
    `session.py`分割・第二段階）。戻り値は `(session_ctx, user_text, is_dead)`。

    プロンプト文脈構築を`context_builder.py`（既に`build_session_context`/
    `build_turn_instruction`を持つ）へ統合し直す案がTODO.mdに残っているが、
    今回は`next_turn`本体からの切り出しに留めた。
    """
    directive_set_id = session.get("action_directive_set", "default")
    directives = _load_action_directives().get(directive_set_id, {}).get("directives", {})

    trpg_ctx = ""
    scenario = None
    if session.get("trpg_mode"):
        rulebook = _load_trpg_rulebook(session.get("trpg_rulebook", ""))
        scenario = _load_trpg_scenario(session.get("trpg_scenario", ""))
        trpg_ctx = _build_for_player(
            current_char_id, char, rulebook, scenario or None, session, user_lang
        )

    effective_topic = (
        scenario.get("title", topic) if session.get("trpg_mode") and scenario else topic
    )
    session_ctx = _build_session_context(
        effective_topic, rules, initiative, name_map, speaker_name, user_lang,
        trpg_context=trpg_ctx,
    )

    # 同基底衝突処理: 同一 base_entity_id を持つキャラが複数参加している場合にアンカー文注入
    base_entity_groups: dict[str, list[tuple[str, str]]] = {}
    for cid in initiative:
        c = get_character(cid, profiles)
        if not c:
            continue
        beid = c.get("base_entity_id")
        if not beid:
            continue
        cname = name_map.get(cid, cid)
        core = (c.get("character_constitution") or {}).get("core", "")
        base_entity_groups.setdefault(beid, []).append((cname, core))
    for beid, group in base_entity_groups.items():
        if len(group) < 2:
            continue
        if user_lang == "ja":
            anchor_lines = "\n".join(
                f"- {n}：{k}" if k else f"- {n}"
                for n, k in group
            )
            session_ctx += (
                f"\n\n【重要：共通表現参照キャラクター】"
                f"以下のキャラクターは共通の表現参照（{beid}）を持ちますが、"
                "それぞれ完全に独立したアイデンティティを持ちます。"
                "互いの人格・価値観・口調を混同・継承してはなりません。\n"
                f"{anchor_lines}"
            )
        else:
            anchor_lines = "\n".join(
                f"- {n}: {k}" if k else f"- {n}"
                for n, k in group
            )
            session_ctx += (
                f"\n\n[IMPORTANT: Shared Expression Reference] "
                f"The following characters share a common expression reference ({beid}), "
                "but are completely independent identities. "
                "They must NOT inherit or borrow personality, values, or speech patterns from each other.\n"
                f"{anchor_lines}"
            )

    # 死者視点：runtime_statsでステータスが0になっているキャラは死者として発言させる
    runtime_stats = session.get("runtime_stats", {}).get(current_char_id, {})
    is_dead = bool(runtime_stats) and any(v <= 0 for v in runtime_stats.values())
    if is_dead:
        if user_lang == "ja":
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
        session["history"], current_char_id, session, directives, user_lang,
    )

    return session_ctx, user_text, is_dead


def _generate_ai_turn_reply(
    session: dict, current_char_id: str, char: dict, user_text: str, history: list,
    model: str, backend_id: str, session_ctx: str, allowed_sexual: list, allowed_violence: list,
    name_map: dict, topic: str, turn: int, is_dead: bool,
):
    """LLM呼び出し（vram_lock込み・1回だけ自動リトライ）と結果パースを行う
    （`next_turn`から切り出し、2026-08-15、`session.py`分割・第二段階）。

    戻り値は `(early_result, text, emotion, tags, image_prompt_en)` の5要素タプル。
    vram_lock取得タイムアウト・LLM呼び出し自体の例外はエラーレスポンスをそのまま
    返すべきケースのため`early_result`にレスポンス辞書を入れて返す。それ以外は
    `early_result`が`None`で、パース済みの発言（生成失敗時は
    "(generation failed)"のプレースホルダー文言）を返す。
    """
    prev_emotion = next(
        (h.get("emotion", "neutral") for h in reversed(session["history"])
         if h.get("character_id") == current_char_id),
        "neutral",
    )
    if isinstance(prev_emotion, list):
        prev_emotion = ", ".join(prev_emotion)

    global _last_session_debug
    from def_kari.resources.vram_lock import get_vram_lock
    vram_lock = get_vram_lock()
    if not vram_lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
        err = f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s"
        _last_session_debug = {"error": err, "success": False, "attempts": [], "character_id": current_char_id, "backend": backend_id, "topic": topic, "round": session["round"], "user_text": user_text}
        return {"error": err, "character_id": current_char_id, "character_name": name_map.get(current_char_id, current_char_id), "text": f"(error: {err})", "emotion": "neutral", "round": session["round"], "turn": turn + 1, "counters": dict(session.get("counters", {}))}, "", "neutral", [], ""
    try:
        narrate_kwargs = dict(
            character=char,
            user_text=user_text,
            history=history,
            model=model,
            backend=backend_id,
            session_context=session_ctx,
            allowed_sexual=allowed_sexual,
            allowed_violence=allowed_violence,
            current_emotion=prev_emotion,
            char_id=current_char_id,
        )
        result = _player_agent.narrate(**narrate_kwargs)
        if not result.get("success"):
            import time as _time
            _time.sleep(1)
            result = _player_agent.narrate(**narrate_kwargs)
    except Exception as e:
        _last_session_debug = {"error": str(e), "success": False, "attempts": [], "character_id": current_char_id, "backend": backend_id, "topic": topic, "round": session["round"], "user_text": user_text}
        return {"error": str(e), "character_id": current_char_id, "character_name": name_map.get(current_char_id, current_char_id), "text": f"(error: {e})", "emotion": "neutral", "round": session["round"], "turn": turn + 1, "counters": dict(session.get("counters", {}))}, "", "neutral", [], ""
    finally:
        vram_lock.release()

    text = ""
    emotion = "neutral"
    tags: list[str] = []
    image_prompt_en = ""
    if result.get("success") and result.get("result"):
        parsed = result["result"]
        text = parsed.get("dialogue", "")
        if is_dead and text:
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

    return None, text, emotion, tags, image_prompt_en


def _finalize_ai_turn(
    session: dict, req: SessionNextRequest, current_char_id: str, name_map: dict, counters: dict,
    initiative: list, turn: int, text: str, emotion: str, tags: list, image_prompt_en: str,
    backend_id: str, skip_gen_before: int, ai_action: dict, designated_target_name: str,
) -> dict:
    """生成された発言を履歴に反映し、リピートペナルティ判定・ターン/action_count
    の進行・autosave・レスポンス組み立てを行う（`next_turn`から切り出し、
    2026-08-15、`session.py`分割・第二段階）。
    """
    session["history"].append({
        "role": "assistant",
        "content": f"{name_map.get(current_char_id, current_char_id)}: {text}",
        "character_id": current_char_id,
        "emotion": emotion,
        "tags": tags,
    })
    round_completed = _mark_spoken_and_check_round_complete(session, current_char_id)

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
        if session.get("_skip_gen", 0) == skip_gen_before:
            session["turn"] = next_t
        session["action_count"] = 0
    else:
        session["action_count"] = action_count

    _autosave(req.session_id)
    _char_name = name_map.get(current_char_id, current_char_id)
    _log.info("[next] Round %d | Turn %d | %s (%s) | %d chars | action=%s",
              session["round"], turn + 1, _char_name, backend_id, len(text), ai_action.get("action", "none"))
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
        "ai_action": ai_action.get("action", "none"),
        "designated_name": designated_target_name or None,
        "round_completed": round_completed,
        "round_seq": session.get("_round_seq", 0),
    }


def next_turn(req: SessionNextRequest):
    """AIターンを1回進める内部ロジック。以前は`POST /api/session/next`として無認証で
    公開されており、session_idさえ分かればkeeper権限を経ずにLLM呼び出しを無制限に
    実行できてしまっていた（8.8参照）。フロントからは未使用だったためエンドポイントは
    廃止したが、`_execute_ai_turn`が内部関数として直接呼び出すためこの関数自体は残す。
    """
    session = _sessions.get(req.session_id)
    if not session:
        return {"error": "Session not found"}

    early_result, _ctx = _resolve_turn_start(session, req)
    if early_result is not None:
        return early_result

    initiative = session["initiative"]
    name_map = session["name_map"]
    current_char_id = _ctx["current_char_id"]
    turn = _ctx["turn"]
    counters = _ctx["counters"]
    profiles = _ctx["profiles"]
    char = _ctx["char"]
    backend_id = _ctx["backend_id"]
    model = _ctx["model"]
    _skip_gen_before = _ctx["_skip_gen_before"]

    history = _build_recent_history(session, current_char_id, name_map)

    _settings = load_settings()
    _user_lang = _settings.get("user_language", "ja") or "ja"
    _allowed_sexual = _settings.get("allowed_rating_sexual", ["general"])
    _allowed_violence = _settings.get("allowed_rating_violence", ["general"])

    rules = session.get("rules", [])
    speaker_name = name_map.get(current_char_id, current_char_id)
    topic = session.get("topic", "")
    action_count = session.get("action_count", 0)
    other_names = [name_map.get(c, c) for c in initiative if name_map.get(c, c) != speaker_name]

    early_result, _ai_action, _designated_target_name = _resolve_ai_action(
        session, req, current_char_id, turn, counters, initiative, name_map,
        speaker_name, backend_id, model, char, _user_lang,
    )
    if early_result is not None:
        return early_result

    session_ctx, user_text, _is_dead = _build_turn_prompt_context(
        session, current_char_id, char, initiative, name_map, profiles,
        speaker_name, topic, rules, action_count, other_names, _user_lang,
    )

    early_result, text, emotion, tags, image_prompt_en = _generate_ai_turn_reply(
        session, current_char_id, char, user_text, history, model, backend_id,
        session_ctx, _allowed_sexual, _allowed_violence, name_map, topic, turn, _is_dead,
    )
    if early_result is not None:
        return early_result

    return _finalize_ai_turn(
        session, req, current_char_id, name_map, counters, initiative, turn,
        text, emotion, tags, image_prompt_en, backend_id, _skip_gen_before,
        _ai_action, _designated_target_name,
    )


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


def _check_actor_char_ownership(session: dict, auth: dict, actor_id: str) -> None:
    """`actor_id`を名乗る操作を行っているトークンが本当にその本人かを検証する
    （8.34対策のオーナーシップ判定を、human_turn_actionのinterrupt/generate_image
    分岐から、vote/castなど「ターン外で特定の人間キャラとして振る舞う」他の
    エンドポイントからも再利用できるよう切り出したもの。判定内容は完全に同一）。
    """
    role = auth.get("role")
    online = session.get("online_mode")
    if actor_id not in session.get("human_char_ids", []):
        raise HTTPException(409, "Not a human player's character")
    if role == "player" and auth.get("char_id") != actor_id:
        raise HTTPException(409, "You can only act as your own character")
    if online and role == "host" and actor_id != session.get("host_char_id", ""):
        raise HTTPException(409, "You can only act as your own character")
    if online and role == "gm":
        raise HTTPException(409, "You can only act as your own character")


def _check_human_turn_authorization(session: dict, req: HumanTurnRequest, auth: dict, current_char_id: str) -> None:
    """human_turn_actionのアクション別認可チェック。違反時はHTTPExceptionを送出し、
    問題なければ何も返さない（`session.py`分割・第二段階、2026-08-15切り出し）。

    ── ターン所有権チェック(2026-08-08修正) ────────────────────────
    send/extend/skip は「今まさに initiative[turn] の人間キャラの番である」ことを
    前提に session["turn"] を進める。だが従来はcurrent_char_idが本当に人間枠か・
    呼び出しトークンがそのキャラ本人かを一切検証していなかった。そのため同一
    クライアントからの二重送信(ネットワーク再試行・連打・スクリプトでの連打)が
    後続の別キャラ(他プレイヤーやAI含む)のターンまで次々と消費してしまっていた
    (frontend/e2e/ai_turn_dedup.js で実証。8並列送信→4件処理されRoundが進む)。

    当初「turnの読み取りから書き戻しまでの間に割り込まれるTOCTOU」と誤診断していたが、
    human_turn_action は async def ながら本体に await が一切無く、asyncioの協調
    スケジューリング上この関数は呼ばれたら他コルーチンに横入りされず単一
    イベントループ上でアトミックに完走する。実体はレースではなく、この認可漏れ
    そのものだった(重複送信は真の並行処理ではなく、逐次的に全件処理されていた)。

    ── host/gmのオーナーシップ(2026-08-20対応、指摘5/TODO.md該当項目) ─────────
    host/gmはトークン発行時にchar_idを持たない(issue_player_jwt呼び出し側を参照)。
    オフライン(ホットシート含む)はhost_token=唯一のローカル操作者であり、そのセッション
    内の人間キャラ全員を正規に操作できる（他に人間がいないため「なりすまし」が成立し
    得ない）ため、従来通り対象外のまま維持する。オンラインセッションのみ制限を掛ける:
    hostは`lobby_config`(session_lobby.py)で自分が登録したhost_char_id(未登録なら
    空文字＝一切送信不可)、gmはTRPGモードの構造上ずっとkeeper専任(session_lobby.py
    のset_lobby_config: keeper_char_idはplayer_idsから除外される)で自分の人間キャラを
    持つケースが存在しないため常に対象外。
    """
    role = auth.get("role")
    online = session.get("online_mode")

    if req.action in ("send", "extend", "skip"):
        if current_char_id not in session.get("human_char_ids", []):
            raise HTTPException(409, "It is not currently a human player's turn")
        if role == "player" and auth.get("char_id") != current_char_id:
            raise HTTPException(409, "It is not your turn")
        if online and role == "host" and current_char_id != session.get("host_char_id", ""):
            raise HTTPException(409, "It is not your turn")
        if online and role == "gm":
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

    # 8.34対策: interrupt/generate_imageはsend/extend/skipと違い「今のターンの本人」
    # である必要はない（割り込みは他人のターン中に別の人間キャラが横から発言する
    # 機能のため、req.character_idがcurrent_char_idと異なること自体は仕様通り）。
    # しかし従来は「そのreq.character_idを名乗るトークンが本当にその本人か」を
    # 一切検証しておらず、任意のplayerトークンが他人のcharacter_idを指定するだけで
    # なりすまし発言・他人の発言力を勝手に消費できてしまっていた。
    if req.action in ("interrupt", "generate_image"):
        actor_id = req.character_id if req.character_id else current_char_id
        _check_actor_char_ownership(session, auth, actor_id)


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

    _check_human_turn_authorization(session, req, _auth, current_char_id)

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
        round_completed = _mark_spoken_and_check_round_complete(session, current_char_id)
        _autosave(session_id)
        _game_event_bus.emit(session_id, "HUMAN_ACTION", {
            "character_id": current_char_id,
            "character_name": char_name,
            "text": req.text,
            "action": "send",
            "counters": dict(counters),
            "round_completed": round_completed,
            "round_seq": session.get("_round_seq", 0),
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
            "round_completed": round_completed,
            "round_seq": session.get("_round_seq", 0),
        }



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

    # 8.32対策: 未認証で保持中の接続数がIP単位/全体単位の上限に達していれば、
    # authを待たず即座に切断する（_check_ws_rateは認証後のtoken単位のため、
    # このフェーズには効かない）。
    client_ip = _resolve_client_ip(ws)
    if not _try_acquire_ws_pending_auth_slot(client_ip):
        try:
            await ws.close(code=1013)  # Try Again Later
        except Exception:
            pass
        return

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
    finally:
        _release_ws_pending_auth_slot(client_ip)

    sess = _sessions.get(session_id)
    if not sess:
        try:
            await ws.close(code=4004)
        except Exception:
            pass
        return

    # 8.30対策: require_*と同じ「現在playersに登録されているか」の最終防波堤。
    # _revoked_jtisはプロセス再起動で失われるが、playersはautosave/起動時復元で
    # 永続化されるため、退室・追放済みのトークンでの再接続をここでも塞ぐ。
    if raw_token not in sess.get("players", {}):
        try:
            await ws.close(code=4001)
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
