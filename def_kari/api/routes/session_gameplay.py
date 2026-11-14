"""Sessionのゲームプレイ系: キーパー発言・ダイス・シーン進行・指名・カウンター・
NPC状態・stat同期。`session.py`分割の一部。

投票（vote_deliberate/vote_commit）はsession_voting.pyへ分離済み
（TODO.md「session_gameplay.pyの投票ロジック分離」参照）。
"""

import logging
import os

from fastapi import HTTPException, Depends
from pydantic import BaseModel

from def_kari.llm.backend import DEFAULT_LLM_BACKEND
from def_kari.gm.gm_agent import _gm_agent
from def_kari.gm.context_builder import load_trpg_scenario as _load_trpg_scenario
from def_kari.gm.events import game_event_bus as _game_event_bus
from def_kari.safety.audit_log import reset_violations as _reset_audit_violations
from def_kari.safety.content_filter import contains_blocked_content

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
            from def_kari.api.routes.session import _ensure_ai_turns_running, _get_current_speaker, _is_human_char
            current = _get_current_speaker(sess)
            if current and not _is_human_char(sess, current):
                _ensure_ai_turns_running(session_id, sess)
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
    inject_history: bool = True


@router.post("/{session_id}/ai_keeper")
def ai_keeper_narrate(session_id: str, req: AIKeeperRequest, _auth: dict = Depends(require_player)):
    """AIキーパー（無個性モード）: シナリオ・ルールブック・履歴からGM発言を生成する。

    キーパーの発火はクライアント駆動（各タブがラウンド完了を検知して自律的に
    このエンドポイントを叩く）のため、同じラウンドで複数タブがほぼ同時に呼びうる。
    session["_round_seq"]（session_turn_engine.pyのラウンド完了判定と共通）単位で
    生成結果をキャッシュし、二重LLM生成・タブ間で異なるナレーションが生成される
    事態を避ける。加えて生成結果をKEEPER_NARRATEDイベントで全タブへ配信する
    （以前は呼び出したタブへの同期レスポンスのみで、他タブには一切届いていなかった
    ——判定結果(JUDGMENT_RESOLVED)も同様に配信自体はあったがフロント側に受信
    ハンドラが無く、実質どちらも「発火した本人のタブにしか見えない」状態だった。
    2026-09-06、実機でユーザーが発見）。
    """
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    if not session.get("trpg_mode"):
        return {"error": "Not in TRPG mode"}
    if session.get("human_keeper"):
        return {"error": "Human keeper mode: use POST /keeper endpoint instead"}

    _round_seq = session.get("_round_seq", 0)
    _cache = session.get("_keeper_narrated_cache")
    if session.get("_keeper_narrated_seq") == _round_seq and _cache:
        return _cache

    # 以前はreq.backend（呼び出したタブが個別に持つSettings上の選択、公開ポート
    # 経由のゲストは常に空）→ハードコードされたグローバルデフォルト
    # （DEFAULT_LLM_BACKEND、環境変数LLM_BACKEND未設定時は"openai"）の順で解決して
    # おり、session.get("backend")（セッション作成時に選んだ実際のバックエンド）を
    # 一切見ていなかった。session_turn_engine.pyの通常AIターン解決
    # （char_backends.get(...) or req.backend or session.get("backend", ...)）とも
    # 非対称で、キーパー発火がどのタブで勝つか次第でセッションの意図と無関係な
    # バックエンド（実機ではOpenAI、レート制限に直撃）が使われてしまっていた
    # （2026-09-06、実機でユーザーが発見）。タブごとに変動するreq.backendには
    # 依存せず、サーバー側の権威データだけで決定的に解決するよう修正。
    _keeper_char_id = session.get("keeper_char_id", "")
    _char_backends_map = session.get("char_backends", {})
    # session.get("backend", DEFAULT)はキーが無い場合しかデフォルトを補わず、
    # session["backend"]が空文字列（例: POST /startにbackend:""を渡した場合）だと
    # そのまま空文字列が解決結果になってしまう。旧コードの`... or DEFAULT_LLM_BACKEND`
    # 連鎖は空文字列も救っていたため、それと同じ意味になるよう明示的にorで繋ぐ
    # （2026-09-08コードレビューで発覚）。
    _effective_backend = _char_backends_map.get(_keeper_char_id) or session.get("backend") or DEFAULT_LLM_BACKEND

    from def_kari.resources.vram_lock import get_vram_lock as _get_vram_lock
    _keeper_lock = _get_vram_lock()
    if not _keeper_lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
        return {"error": f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s"}
    try:
        # ロック待機中に他タブが同じround_seq分の生成を完了させている場合がある
        # （二重チェックロッキング、TOCTOU回避）。キャッシュへの書き込みまでロック
        # 保持下で行う必要がある——以前はロック解放後（_autosave/シーン進行判定を
        # 挟んだ後）に書き込んでいたため、その間に後続タブがロックを取得して
        # まだ空のキャッシュを見てしまい、二重チェックロッキングが実質機能して
        # いなかった（2026-09-08コードレビューで発覚）。
        _cache = session.get("_keeper_narrated_cache")
        if session.get("_keeper_narrated_seq") == _round_seq and _cache:
            return _cache
        result = _gm_agent.narrate(
            session=session,
            backend_id=_effective_backend,
            inject_history=req.inject_history,
            session_id=session_id,
        )
        if result.get("error"):
            _log.error("[keeper] error: %s", result["error"])
            if result.get("rule_system_error"):
                # ルールシステム（プラグイン）の失敗は、卓を止めて知らせる（B-027）
                from def_kari.api.routes.session_turn_engine import _pause_for_plugin_error
                _pause_for_plugin_error(session, {"capability": "rule", "method": "gm", "error": result["error"]})
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
        resp["round_seq"] = _round_seq
        session["_keeper_narrated_seq"] = _round_seq
        session["_keeper_narrated_cache"] = resp
    finally:
        _keeper_lock.release()
    _game_event_bus.emit(session_id, "KEEPER_NARRATED", resp)
    return resp


_STAT_NAME_MAX_LEN = 40


class SessionDiceRollRequest(BaseModel):
    # 卓のルールブックがあれば、その表記を使い、この値は使わない（B-030。以前は画面が '1d100' を
    # 直書きして送っていた）。ルールブックの無い卓でだけ使う。
    notation: str = ""
    skill_value: int = 0
    rulebook_id: str = ""
    character_id: str = ""
    stat_name: str = ""
    is_skill: bool = False
    is_stat: bool = False
    # 発火元タブがJUDGMENT_RESOLVEDブロードキャストを「自分のロール」として識別する
    # ためのクライアント生成ID（2026-09-08）。以前はcharacter_id|stat_name|total|
    # judgment_valueの組み合わせキーで判定していたが、rollDiceDialog（プレイヤー
    # 自身のダイアログ経由のロール）はcharacter_id/stat_nameを一切送っておらず
    # 常に空文字列になっていたため、ブロードキャストされた自分のロールが「他タブの
    # ロール」として誤認され、キャラ名も空のまま二重表示されていた
    # （コードレビューで発覚）。レスポンス到着を待たず送信直後に登録できるため、
    # 「サーバーがHTTPレスポンスより先にWS配信する」タイミングのレースも解消する。
    request_id: str = ""


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
    # 判定の結果は「🎲 {キャラ名}【{能力名}】…」としてそのキャラ名義で履歴に入り、LLMの入力
    # にも混ざる。以前はどのプレイヤーでも、どのキャラ名義でも振れ、能力名も申告どおりに
    # 入っていた（投票の発議者と同じ種類の偽装。2026-11-08レビュー指摘）。プレイヤーは自分の
    # キャラだけ（キーパーは全キャラ分を振るので制限しない）。判定値（skill_value）を
    # サーバー側のキャラシートから引く対応は、判定エンジンを作り直す v5.0 で行う（残課題）。
    if req.character_id and _auth.get("role") == "player":
        from def_kari.api.routes.session import _check_actor_char_ownership
        _check_actor_char_ownership(session, _auth, req.character_id)
    if len(req.stat_name) > _STAT_NAME_MAX_LEN:
        raise HTTPException(400, "Stat name is too long")
    if req.stat_name and contains_blocked_content(req.stat_name):
        raise HTTPException(400, "This message cannot be sent.")

    from def_kari.api.routes.trpg import compute_dice_judgment
    try:
        # 判定のルールブックはセッションの設定を使う（申告はセッションに設定が無いときだけ）。
        # 以前は申告どおりで、ルールブックを選ぶ画面を通らないプレイヤーのタブは空を送るため、
        # 判定（成功・失敗）が作られず合計だけになっていた（2026-11-08、実機確認で発覚）。
        rulebook_id = session.get("trpg_rulebook") or req.rulebook_id
        notation = req.notation
        from def_kari.trpg import plugin_hooks as _trpg_hooks, registry as _trpg_registry, resources as _trpg_resources
        _system = None
        if session.get("trpg_rulebook"):
            # 卓のルールシステムは、卓を作ったときに固定した値から引く（B-002）
            _system, _unavailable = _trpg_hooks.resolve_for_session(session)
            if _unavailable:
                from def_kari.api.routes.session_turn_engine import _pause_for_plugin_error
                _pause_for_plugin_error(session, {"capability": "rule", "method": "general_check", "error": _unavailable})
                return {"error": _unavailable}
        _rb = _trpg_resources.load_rulebook(rulebook_id) if rulebook_id else {}
        if session.get("trpg_rulebook") and not _rb:
            # 卓のルールブックが読めない（消えた・壊れた）なら、既定の表記で黙って振らず、止めて知らせる
            _why = f"rulebook {rulebook_id!r} of this table cannot be read"
            from def_kari.api.routes.session_turn_engine import _pause_for_plugin_error
            _pause_for_plugin_error(session, {"capability": "rule", "method": "dice_notation", "error": _why})
            return {"error": _why}
        if _rb and _system is None:
            _system = _trpg_registry.for_rulebook(_rb)
        try:
            if _rb and _system is not None:
                notation = _trpg_registry.call_rule(_system, "dice_notation", _rb)
            if not notation:
                # ルールブックの無い卓で表記も無ければ、既定のルールシステムの表記（以前は画面が 1d100 を送っていた）
                notation = _trpg_registry.get(_trpg_registry.DEFAULT_RULE_SYSTEM).dice_notation({})
            computed = compute_dice_judgment(notation, req.skill_value, rulebook_id, req.is_skill, req.is_stat,
                                             system=_system)
        except _trpg_registry.RuleSystemError as e:
            # プラグインの判定が失敗したら、卓を止めて知らせる（B-027）
            from def_kari.api.routes.session_turn_engine import _pause_for_plugin_error
            _pause_for_plugin_error(session, {"capability": "rule", "method": "general_check", "error": str(e)})
            return {"error": str(e)}
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
            "request_id": req.request_id,
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

    # 指名と、指名発言後に戻るべきターン位置（指名した人の次）。AIの指名と同じ窓口を使う
    from def_kari.api.routes.session import _set_designation
    _set_designation(session, req.target_id)
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
    result = {"session": _session_for_public_json(session)}
    # 再読み込みで復帰したプレイヤーのタブが、自分のキャラシートを読み込み直せるよう、
    # 呼び出した本人のキャラのシートIDだけを返す。以前は参加の瞬間にしか読み込まず、
    # 再読み込みの後は「振る」ボタンが消えて自分の判定を振れなくなっていた（2026-11-08、
    # 実機確認で発覚）。char_game_sheets 全体は 8.27対策で公開しない方針のままにする。
    if _auth.get("role") == "player" and _auth.get("char_id"):
        result["my_game_sheet_id"] = session.get("char_game_sheets", {}).get(_auth["char_id"], "")
    result["participants"] = _participants_snapshot(session)
    return result


def _participants_snapshot(session: dict) -> list[dict]:
    """参加者の一覧と、いまWSで接続しているかどうかを返す（再読み込みしたタブの復元用）。

    フロントの参加者一覧は SESSION_STARTED / PLAYER_JOINED のイベントでしか作られず、
    セッションの途中で再読み込みしたタブでは空のままだった。キーパーのタブは、この一覧から
    「接続中のプレイヤーが自分で振るキャラ」を決めているため、再読み込みの後はプレイヤーの
    キャラの判定まで振り、判定が二重になっていた（2026-11-08、レビューで指摘）。
    中身は PLAYER_JOINED で全タブに配っているものと同じ。ただし game_sheet_id は
    char_game_sheets と同じく公開しない（8.27）ので落とす。トークンは含めない。
    """
    connected_tokens = set(session.get("ws_connections", {}))
    token_to_pid = session.get("token_to_participant", {})
    connected_pids = {pid for tok, pid in token_to_pid.items() if tok in connected_tokens}
    return [
        {
            "character_id": p.get("character_id", ""),
            "participant_id": p.get("participant_id", ""),
            "display_name": p.get("display_name", ""),
            "role": p.get("role", "player"),
            "claimed_char_id": p.get("claimed_char_id", ""),
            "connected": p.get("participant_id", "") in connected_pids,
        }
        for p in session.get("joined_participants", [])
    ]


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
