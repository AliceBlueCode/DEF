"""Sessionのゲームプレイ系: キーパー発言・ダイス・シーン進行・指名・カウンター・
投票・NPC状態・stat同期。`session.py`分割の一部。
"""

import asyncio
import logging
import os

from fastapi import HTTPException, Depends, Request
from pydantic import BaseModel

from def_kari.characters import load_profiles, get_character
from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.llm.client import generate_structured_reply
from def_kari.gm.gm_agent import _gm_agent
from def_kari.gm.context_builder import (
    build_session_context as _build_session_context,
    load_trpg_scenario as _load_trpg_scenario,
)
from def_kari.gm.events import game_event_bus as _game_event_bus
from def_kari.safety.audit_log import record_generation_event, reset_violations as _reset_audit_violations
from def_kari.settings import load_settings

from def_kari.api.routes.session_state import router, _sessions, _ws_send_locks, _session_for_public_json
from def_kari.api.routes.session_auth import (
    require_host,
    require_keeper,
    require_player,
    require_participant,
    _check_circuit_breaker,
    _check_generation_rate,
    _check_daily_generation_limit,
    _record_violation_and_maybe_trip,
    _resolve_client_ip,
    _character_json_fingerprint,
    revoke_token,
)
from def_kari.api.routes.session_lobby import _sp
from def_kari.api.routes.session_image import _resolve_model
from def_kari.api.routes.session_persistence import _autosave, _save_session_episodic, _delete_autosave

_log = logging.getLogger("def.session")

_VRAM_LOCK_TIMEOUT_SECONDS = float(os.environ.get("DEF_VRAM_LOCK_TIMEOUT", "60"))


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
            # _get_current_speaker/_is_human_char/_run_ai_turnsはturn_engine
            # （session.py側、まだ未抽出）に依存するため、循環import回避のため遅延import。
            from def_kari.api.routes.session import _get_current_speaker, _is_human_char, _run_ai_turns
            current = _get_current_speaker(sess)
            if current and not _is_human_char(sess, current):
                ai_task = sess.get("ai_task")
                if not ai_task or ai_task.done():
                    sess["ai_task"] = asyncio.create_task(_run_ai_turns(session_id))
    else:
        sess["ai_paused"] = True
    return {"auto_advance": req.enabled}


class KeeperMessageRequest(BaseModel):
    text: str


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

    # 8.34対策: キーパー(host/gm)は自治規約上の管理者特権として無条件・無償で指名できる
    # （SessionTab.tsxのdesignateBtnKeeperがcounters無視で表示されているのと同じ扱い、
    # skipBtnKeeper等の既存の他のキーパー特権とも一貫）。一方プレイヤー用UI
    # （designateBtn）はextend/interrupt/vote等の兄弟ボタンと同じ発言力コスト消費の
    # 並びに置かれており、自治規約（docs/DEF_TRPG卓_自治規約.md）も「次発言者指名: -1」
    # と明記しているが、本エンドポイントはrole区別なく誰でも無条件・無償で呼べていた
    # （他人のターン中でも連打可能）。playerロールのみ、現在のターンの本人であること・
    # 発言力1以上を持つことを要求し、-1を消費する。
    if _auth.get("role") == "player":
        if not initiative or current_turn >= len(initiative):
            return {"error": "invalid turn"}
        current_char_id = initiative[current_turn]
        if _auth.get("char_id") != current_char_id:
            raise HTTPException(409, "It is not your turn")
        counters = session.setdefault("counters", {})
        if counters.get(current_char_id, 0) < 1:
            raise HTTPException(409, "Not enough speech power to designate")
        counters[current_char_id] = counters[current_char_id] - 1

    # 指名発言後に戻るべきターン位置を保存（指名キャラの次）
    session["designated_next"] = req.target_id
    session["designated_return_turn"] = (current_turn + 1) % len(initiative) if initiative else 0
    _autosave(session_id)
    name_map = session.get("name_map", {})
    # _get_current_speakerはturn_engine（session.py側、まだ未抽出）に依存するため、
    # 循環import回避のため遅延import。
    from def_kari.api.routes.session import _get_current_speaker
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
        # _start_background_ttsはturn_engine（session.py側、まだ未抽出）に依存するため、
        # 循環import回避のため遅延import。
        from def_kari.api.routes.session import _start_background_tts
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

    # _is_human_char/_start_background_ttsはturn_engine（session.py側、まだ未抽出）に
    # 依存するため、循環import回避のため遅延import。
    from def_kari.api.routes.session import _is_human_char, _start_background_tts

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


async def _remove_expelled_participant(session_id: str, session: dict, target_id: str) -> str:
    """expel対象のトークンをplayers/ws_connections/token_to_participantから完全に除去し、
    JWTを無効化する。対象の人間プレイヤーのトークンが見つからなければ何もせず空文字列を返す
    （対象が人間プレイヤーの場合、initiativeから外すだけでは接続・トークンが生きたまま
    残り続けるため——leave_session相当の後始末）。
    """
    expelled_token = next(
        (t for t, c in list(session.get("players", {}).items()) if c == target_id), None
    )
    if not expelled_token:
        return ""
    session["players"].pop(expelled_token, None)
    # turn_engine（session.py側、まだ未抽出）に依存するため、循環import回避のため遅延import。
    from def_kari.api.routes.session import _cancel_disconnect_skip
    _cancel_disconnect_skip(session_id, target_id)
    expelled_participant_id = session.get("token_to_participant", {}).pop(expelled_token, target_id)
    session["joined_participants"] = [
        p for p in session.get("joined_participants", [])
        if p.get("participant_id") != expelled_participant_id
    ]
    expelled_ws = session.get("ws_connections", {}).pop(expelled_token, None)
    _ws_send_locks.pop(expelled_token, None)
    if expelled_ws:
        try:
            await expelled_ws.close(code=1000)
        except Exception:
            pass
    revoke_token(expelled_token)
    return expelled_participant_id


async def _apply_vote_expel(session_id: str, session: dict, initiative: list, target_id: str) -> tuple[bool, str]:
    """投票expel可決時の後始末。戻り値: (keeper_handed_off, expelled_participant_id)。"""
    session["initiative"] = [c for c in initiative if c != target_id]

    keeper_handed_off = target_id == session.get("keeper_char_id")
    if keeper_handed_off:
        # 自治規約62行目: 「キーパーが退場した場合はAIキーパーへ交代してセッションを
        # 継続する」。空文字列にするとai_keeper_narrate()が自動的に汎用の
        # 無名AIキーパー（🎩 Keeper）にフォールバックする（lobby_set_keeper_charの
        # 解除と同じ仕組み）ため、他に配線は不要。
        session["keeper_char_id"] = ""
        session["keeper_char_name"] = ""

    expelled_participant_id = await _remove_expelled_participant(session_id, session, target_id)

    # 追放されたキャラのcharacter_jsonをブラックリストに記録し、同じ招待コードで
    # 同一character_jsonの再参加を拒否できるようにする（8.21対策）。guest_charsに
    # 存在しない対象（既存人間スロットのclaim_char_id等）は元々character_json持ち込み
    # ではないため対象外。
    expelled_char_data = session.get("guest_chars", {}).get(target_id)
    if expelled_char_data:
        fp = _character_json_fingerprint(expelled_char_data)
        session.setdefault("expelled_char_fingerprints", []).append(fp)

    return keeper_handed_off, expelled_participant_id


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

    # _is_human_char/_cancel_disconnect_skip/_end_sessionはturn_engine
    # （session.py側、まだ未抽出）に依存するため、循環import回避のため遅延import。
    from def_kari.api.routes.session import _is_human_char, _cancel_disconnect_skip, _end_session

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
            _keeper_handed_off, _expelled_participant_id = await _apply_vote_expel(
                session_id, session, initiative, target_id
            )

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
