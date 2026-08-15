"""Sessionのゲームプレイ系: キーパー発言・ダイス・シーン進行・指名・カウンター・
NPC状態・stat同期。`session.py`分割の一部。

投票（vote_deliberate/vote_commit）はsession_voting.pyへ分離済み
（TODO.md「session_gameplay.pyの投票ロジック分離」参照）。
"""

import asyncio
import logging
import os

from fastapi import HTTPException, Depends
from pydantic import BaseModel

from def_kari.llm.backend import DEFAULT_LLM_BACKEND
from def_kari.gm.gm_agent import _gm_agent
from def_kari.gm.context_builder import load_trpg_scenario as _load_trpg_scenario
from def_kari.gm.events import game_event_bus as _game_event_bus
from def_kari.safety.audit_log import reset_violations as _reset_audit_violations

from def_kari.api.routes.session_state import router, _sessions, _session_for_public_json
from def_kari.api.routes.session_auth import (
    require_host,
    require_keeper,
    require_player,
    require_participant,
)
from def_kari.api.routes.session_persistence import _autosave

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
