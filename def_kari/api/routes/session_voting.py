"""投票（お題変更・追放・セッション終了）: 弁明ラウンド・キーパー票+AI票集計・効果適用。

`session_gameplay.py`の一部だったが、単体で500行超と大きく、内容的にも
「ゲームプレイ全般」というより投票という1つのサブシステムのため独立モジュール化した
（TODO.md「session_gameplay.pyの投票ロジック分離」参照）。`_start_background_tts`・
`_is_human_char`・`_cancel_disconnect_skip`・`_end_session`はturn_engine側に依存する
ため、session_gameplay.py時代から踏襲して`session`facade経由の遅延importのまま。
"""

import asyncio
import logging
import os

from fastapi import HTTPException, Depends, Request
from pydantic import BaseModel

from def_kari.characters import load_profiles, get_character
from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.llm.client import generate_structured_reply
from def_kari.llm import backend_guard as _backend_guard
from def_kari.gm.context_builder import build_session_context as _build_session_context
from def_kari.gm.events import game_event_bus as _game_event_bus
from def_kari.safety.audit_log import record_generation_event
from def_kari.safety.content_filter import contains_blocked_content
from def_kari.settings import load_settings

from def_kari.api.routes.session_state import router, _sessions
from def_kari.api.routes.session_auth import (
    require_keeper,
    require_player,
    _check_circuit_breaker,
    _check_generation_rate,
    _check_daily_generation_limit,
    _check_ws_rate,
    _record_violation_and_maybe_trip,
    _resolve_client_ip,
    _character_json_fingerprint,
    revoke_token,
)
from def_kari.api.routes.session_lobby import _sp
from def_kari.api.routes.session_image import _resolve_model
from def_kari.api.routes.session_persistence import (
    _autosave, _save_session_episodic, _delete_autosave, _refund_proposer_counter,
)

_log = logging.getLogger("def.session")

_VRAM_LOCK_TIMEOUT_SECONDS = float(os.environ.get("DEF_VRAM_LOCK_TIMEOUT", "60"))


class VoteRequest(BaseModel):
    vote_type: str
    detail: str = ""
    target_id: str = ""
    proposer_id: str = ""  # 人間プレイヤーが発議した場合、カウンターを0にする
    proposer_text: str = ""  # 人間プレイヤーの弁明テキスト


class VoteCommitRequest(BaseModel):
    keeper_vote: bool


_KEEPER_ROLES = ("host", "gm")
_VOTE_TYPES = ("topic_change", "expel", "end_session")
_VOTE_DETAIL_MAX_LEN = 200


def _validate_vote_request(session: dict, req: "VoteRequest") -> None:
    """投票の中身を確かめる。detail は「[投票提案] …」としてキーパー名義の履歴に入り、
    お題変更が可決されれば session["topic"] にもなるのに、以前は何も確かめていなかった
    （2026-11-08レビュー指摘。発議者の確認と同じく、申告をそのまま信じない）。"""
    if req.vote_type not in _VOTE_TYPES:
        raise HTTPException(400, "Unknown vote type")
    if len(req.detail) > _VOTE_DETAIL_MAX_LEN:
        raise HTTPException(400, "Vote detail is too long")
    if req.detail and contains_blocked_content(req.detail):
        raise HTTPException(400, "This message cannot be sent.")
    if req.vote_type == "expel" and req.target_id not in session.get("initiative", []):
        raise HTTPException(400, "The expel target is not in this session")


def _authorize_vote_proposer(session: dict, req: "VoteRequest", auth: dict) -> tuple[dict | None, str]:
    """発議者（proposer_id）と、その人の発言として記録する弁明（proposer_text）を確かめる。

    以前はどちらも呼び出し側の申告どおりに受け付けていた。APIを直接叩けば、発言力が3未満
    でも発議でき、しかも他人（AIを含む）を発議者に指定して、任意の文章をその人の発言として
    履歴と全タブに流せた（発言の偽装。2026-11-08レビュー指摘）。
      - 空、または "_keeper": キーパー（host/gm）の発議
      - 人間のキャラ: その本人（_check_actor_char_ownership）。プレイヤーは発言力3以上
        （画面の投票ボタンと同じ条件。キーパー権限の発議は条件なし）
      - AIのキャラ: キーパーのタブが、そのAIの発議（_ai_vote_proposal）を受け付ける場合だけ。
        弁明の文章は申告を使わず、AIが行動選択で出した理由をサーバー側の記録から使う
    戻り値は (引き継ぐAIの発議の記録 or None, 記録する弁明の文章)。
    """
    from def_kari.api.routes.session import _check_actor_char_ownership, _is_human_char
    role = auth.get("role")
    proposer_id = req.proposer_id
    if proposer_id in ("", "_keeper"):
        if role not in _KEEPER_ROLES:
            raise HTTPException(403, "Only the keeper can propose a vote without a proposer character")
        return None, req.proposer_text
    if _is_human_char(session, proposer_id):
        _check_actor_char_ownership(session, auth, proposer_id)
        if role == "player" and session.get("counters", {}).get(proposer_id, 0) < 3:
            raise HTTPException(409, "Not enough speech power to propose a vote")
        if req.proposer_text and contains_blocked_content(req.proposer_text):
            raise HTTPException(400, "This message cannot be sent.")
        return None, req.proposer_text
    ai_proposal = session.get("_ai_vote_proposal") or {}
    if role not in _KEEPER_ROLES or ai_proposal.get("proposer_id") != proposer_id:
        raise HTTPException(403, "This character has not proposed a vote")
    # 受け付けた時点で記録を取り出す。手番の開始時の返却（_refund_unaccepted_ai_vote_proposal）
    # と同じ記録を二重に扱わないため
    session.pop("_ai_vote_proposal", None)
    return ai_proposal, ai_proposal.get("reason", "")


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
    if session.get("_pending_expel_followup"):
        return {"error": "An expel decision is still awaiting the keeper's follow-up choice."}
    if session.get("_pending_vote"):
        # 投票中にもう1つ発議すると、保留中の投票が上書きされて消えていた
        raise HTTPException(409, "vote_in_progress")
    ai_proposal, proposer_text = _authorize_vote_proposer(session, req, _auth)
    if ai_proposal:
        # AIの発議は、行動選択の時点で正規化して記録した中身を使う（申告は使わない）
        req = req.model_copy(update={
            "vote_type": ai_proposal.get("vote_type", req.vote_type),
            "detail": ai_proposal.get("detail", ""),
            "target_id": ai_proposal.get("target_id", ""),
        })
    try:
        _validate_vote_request(session, req)
    except HTTPException:
        # 記録は受け付けの時点で取り出しているので、ここで落ちたら発言力を戻す
        # （追放の対象が発議の後に抜けていた場合など）
        if ai_proposal:
            _refund_proposer_counter(session, {
                "proposer_id": req.proposer_id, "proposer_counter_spent": ai_proposal.get("spent", 0),
            })
        raise

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

    # 投票の状態。これがある間はターンを進める操作を止める（_turn_progress_blocked）
    pending_vote = {
        "vote_type": req.vote_type,
        "detail": req.detail,
        "target_id": req.target_id,
        "proposer_id": req.proposer_id,
        "vote_label": vote_label,
        "detail_text": detail_text,
        "deliberation_texts": {},
        "human_votes": {},
    }
    counters = session.setdefault("counters", {})
    if req.proposer_id:
        # 発議のコストとして発言力を全て消費する。消費した量を記録しておき、キーパーの取り消し
        # （vote_cancel）やサーバーの再起動（autosaveの復元）で投票が流れたら戻す。どちらも
        # 発議した人の責任ではないため（2026-11-08、ユーザー決定）。確定した場合は戻さない。
        # AIの発議は、行動選択（_resolve_ai_action）の時点で既に消費して記録している。
        if ai_proposal:
            pending_vote["proposer_counter_spent"] = ai_proposal.get("spent", 0)
        else:
            pending_vote["proposer_counter_spent"] = counters.get(req.proposer_id, 0)
            counters[req.proposer_id] = 0
    session["_pending_vote"] = pending_vote

    # 弁明の生成はAIの人数分LLMを呼ぶので長く走る。その間にキーパーが取り消し（vote_cancel）
    # たり確定（vote_commit）したりすると、この投票はもう保留中ではない。以前は
    # session["_pending_vote"] を毎回引き直していたため KeyError で500になり、取り消しの後に
    # 弁明が履歴・全タブへ流れたり、直後の別の発議に古い弁明が混ざったりしていた
    # （2026-11-08レビュー指摘）。この投票オブジェクトへの参照を持ち、それが今も保留中かを
    # 書き込みの前に確かめる。
    def _still_pending() -> bool:
        return session.get("_pending_vote") is pending_vote

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
    _game_event_bus.emit(session_id, "HUMAN_ACTION", {
        "action": "vote_deliberation",
        "character_id": "_keeper",
        "character_name": "キーパー",
        "text": vote_announce,
        "proposer_id": req.proposer_id,
        "sender_role": _auth.get("role"),
    })

    if req.proposer_id and proposer_text.strip():
        proposer_name = name_map.get(req.proposer_id, req.proposer_id)
        session["history"].append({
            "role": "assistant",
            "content": f"{proposer_name}: {proposer_text}",
            "character_id": req.proposer_id,
            "emotion": "neutral",
            "tags": [],
        })
        # _start_background_ttsはturn_engine（session.py側）に依存するため、
        # 循環import回避のため遅延import。
        from def_kari.api.routes.session import _start_background_tts
        _proposer_audio_id = _start_background_tts(session_id, proposer_text, req.proposer_id)
        deliberations.append({
            "character_id": req.proposer_id,
            "character_name": proposer_name,
            "text": proposer_text,
            "emotion": "neutral",
            "audio_request_id": _proposer_audio_id,
        })
        pending_vote["deliberation_texts"][req.proposer_id] = proposer_text
        _game_event_bus.emit(session_id, "HUMAN_ACTION", {
            "action": "vote_deliberation",
            "character_id": req.proposer_id,
            "character_name": proposer_name,
            "text": proposer_text,
            "audio_request_id": _proposer_audio_id,
            "proposer_id": req.proposer_id,
            "sender_role": _auth.get("role"),
        })

    _v_settings = load_settings()
    _v_lang = _v_settings.get("user_language", "ja") or "ja"
    _v_allowed_sexual = _v_settings.get("allowed_rating_sexual", ["general"])
    _v_allowed_violence = _v_settings.get("allowed_rating_violence", ["general"])

    # _is_human_char/_start_background_ttsはturn_engine（session.py側）に
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
        # 外部への送信を許さない卓では、外部の LLM に弁明させない（B-021。弁明なしと同じ扱い）
        if not _backend_guard.allowed(session, "llm", bid):
            continue
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

        if not _still_pending():
            # 生成中に取り消された・確定された。残りの弁明も生成せずに打ち切る
            return {"deliberations": deliberations, "counters": dict(counters), "cancelled": True}

        session["history"].append({
            "role": "assistant",
            "content": f"{char_name}: {dialogue}",
            "character_id": char_id,
            "emotion": emotion,
            "tags": tags,
        })
        _ai_audio_id = _start_background_tts(session_id, dialogue, char_id) if had_dialogue else ""
        deliberations.append({
            "character_id": char_id,
            "character_name": char_name,
            "text": dialogue,
            "emotion": emotion,
            "tags": tags,
            "audio_request_id": _ai_audio_id,
        })
        pending_vote["deliberation_texts"][char_id] = dialogue
        _game_event_bus.emit(session_id, "HUMAN_ACTION", {
            "action": "vote_deliberation",
            "character_id": char_id,
            "character_name": char_name,
            "text": dialogue,
            "emotion": emotion,
            "tags": tags,
            "audio_request_id": _ai_audio_id,
            "proposer_id": req.proposer_id,
            "sender_role": _auth.get("role"),
        })

    if not _still_pending():
        return {"deliberations": deliberations, "counters": dict(counters), "cancelled": True}
    _game_event_bus.emit(session_id, "HUMAN_ACTION", {
        "action": "vote_deliberation_done",
        "character_id": "_keeper",
        "vote_type": req.vote_type,
        "target_id": req.target_id,
        "vote_label": vote_label,
        "detail_text": detail_text,
        "proposer_id": req.proposer_id,
        "sender_role": _auth.get("role"),
    })
    _autosave(session_id)
    return {"deliberations": deliberations, "counters": dict(counters)}


class VoteCastRequest(BaseModel):
    character_id: str
    agree: bool
    text: str = ""


@router.post("/{session_id}/vote/cast")
def vote_cast(session_id: str, req: VoteCastRequest, _auth: dict = Depends(require_player)):
    """人間キャラ本人が、進行中の弁明ラウンドに対して自分の意見テキスト＋実際の賛否を
    投じる。commit時にreq.keeper_voteへ一律置き換えられていた人間票の実態を、
    本人の意思に置き換える（2026-08-22対策）。オーナーシップ検証はhuman_turn_actionの
    interrupt/generate_image分岐（8.34対策）と同じ_check_actor_char_ownershipを流用。
    """
    if not _check_ws_rate(session_id, _auth.get("jti") or str(_auth)):
        raise HTTPException(429, "Too many requests. Please wait a moment.")
    if req.text and contains_blocked_content(req.text):
        raise HTTPException(400, "This message cannot be sent.")

    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    pending = session.get("_pending_vote")
    if not pending:
        return {"error": "No pending vote"}

    # _check_actor_char_ownership/_start_background_ttsはturn_engine（session.py側）に
    # 依存するため、循環import回避のため遅延import。
    from def_kari.api.routes.session import _check_actor_char_ownership, _start_background_tts
    _check_actor_char_ownership(session, _auth, req.character_id)
    if req.character_id not in session["initiative"]:
        raise HTTPException(409, "Character is not part of this vote")

    name_map = session["name_map"]
    char_name = name_map.get(req.character_id, req.character_id)
    pending.setdefault("human_votes", {})[req.character_id] = {"agree": req.agree, "text": req.text}

    audio_request_id = ""
    if req.text.strip():
        session["history"].append({
            "role": "assistant",
            "content": f"{char_name}: {req.text}",
            "character_id": req.character_id,
            "emotion": "neutral",
            "tags": [],
        })
        pending["deliberation_texts"][req.character_id] = req.text
        audio_request_id = _start_background_tts(session_id, req.text, req.character_id)

    _game_event_bus.emit(session_id, "HUMAN_ACTION", {
        "action": "vote_cast",
        "character_id": req.character_id,
        "character_name": char_name,
        "text": req.text,
        "agree": req.agree,
        "audio_request_id": audio_request_id,
    })
    _autosave(session_id)
    return {"status": "ok", "character_id": req.character_id, "agree": req.agree}


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
    # turn_engine（session.py側）に依存するため、循環import回避のため遅延import。
    from def_kari.api.routes.session import _cancel_disconnect_skip
    _cancel_disconnect_skip(session_id, target_id)
    expelled_participant_id = session.get("token_to_participant", {}).pop(expelled_token, target_id)
    session["joined_participants"] = [
        p for p in session.get("joined_participants", [])
        if p.get("participant_id") != expelled_participant_id
    ]
    from def_kari.api.routes.session_ws import _close_ws_connection
    await _close_ws_connection(session, expelled_token)
    revoke_token(expelled_token)
    return expelled_participant_id


async def _apply_vote_expel(session_id: str, session: dict, target_id: str) -> tuple[bool, str, bool, bool]:
    """投票expel可決時の後始末。
    戻り値: (keeper_handed_off, expelled_participant_id, round_completed, was_current_speaker)。
    """
    from def_kari.api.routes.session import _get_current_speaker, _remove_from_initiative
    was_current_speaker = target_id == _get_current_speaker(session)
    # initiativeからの除去と手番の補正は、ターン状態の持ち主（session_turn_engine）に任せる
    round_completed = _remove_from_initiative(session, target_id)

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

    return keeper_handed_off, expelled_participant_id, round_completed, was_current_speaker


async def _apply_vote_expel_handover(session_id: str, session: dict, target_id: str) -> tuple[bool, str]:
    """投票expel可決時、キーパーが「AIに引き継ぐ」を選んだ場合の後始末。initiativeは
    変更せず、ai_takeover（session_lobby.py）と全く同じ効果（human_char_idsから外す
    のみ）で対象キャラをAI制御に切り替えたうえで、対象人間プレイヤー自身の接続
    （players/ws_connections/token）は_apply_vote_expelと同じく完全に除去する
    （expelされる「人間」はどちらの選択でも退室する——変わるのは、そのキャラが
    AI操作でセッションに残るか、initiativeから完全に消えるかだけ）。
    戻り値: (keeper_handed_off, expelled_participant_id)。
    """
    from def_kari.api.routes.session_lobby import _hand_char_to_ai_control
    _hand_char_to_ai_control(session_id, session, target_id, resume=False)

    keeper_handed_off = target_id == session.get("keeper_char_id")
    if keeper_handed_off:
        session["keeper_char_id"] = ""
        session["keeper_char_name"] = ""

    expelled_participant_id = await _remove_expelled_participant(session_id, session, target_id)
    return keeper_handed_off, expelled_participant_id


def _resolve_vote_results(
    session: dict, req: VoteCommitRequest, initiative: list, name_map: dict,
    pending: dict, vram_lock, force_approve: bool, lang: str,
) -> dict[str, bool]:
    """投票集計: 人間キャラは keeper_vote（ボタンクリック）を直接使い、AIキャラは
    LLM判定、提案者不在時のキーパー票はkeeper_vote、提案者あり時は追加のLLM判定で
    決める（`vote_commit`から切り出し、2026-08-15、`session.py`分割・第二段階）。
    vram_lockは呼び出し元と共有（取得・解放は各LLM呼び出しの前後で行う）。
    """
    char_backends = session.get("char_backends", {})
    default_backend = session.get("backend", DEFAULT_LLM_BACKEND)
    profiles = load_profiles()
    vote_label = pending["vote_label"]
    detail_text = pending["detail_text"]
    deliberation_texts = pending["deliberation_texts"]
    proposer_id = pending.get("proposer_id", "")

    # _is_human_charはturn_engine（session.py側）に依存するため、循環import回避のため遅延import。
    from def_kari.api.routes.session import _is_human_char

    results: dict[str, bool] = {}
    for char_id in initiative:
        char = get_character(char_id, profiles)

        # 人間プレイヤーは自分でvote/castを叩いていればその値を使う。未投票なら
        # 従来通りkeeper_vote（ボタンクリック）へフォールバックする（2026-08-22、
        # 「対象者本人にも意思表示させたい」というユーザー要望への対応。100%の
        # 応答を強制せず、キーパーがcommitを進められる状態は維持する）。
        if _is_human_char(session, char_id, profiles):
            human_votes = pending.get("human_votes", {})
            if char_id in human_votes:
                results[char_id] = human_votes[char_id]["agree"]
            else:
                results[char_id] = req.keeper_vote
            continue

        bid = char_backends.get(char_id) or default_backend
        if bid not in LLM_BACKENDS:
            bid = DEFAULT_LLM_BACKEND
        model = _resolve_model(bid)
        dialogue = deliberation_texts.get(char_id, "")

        if force_approve:
            results[char_id] = True
            continue

        judge_prompt = _sp("judge_prompt", lang).format(
            dialogue=dialogue, vote_label=vote_label, detail_text=detail_text,
            yes_word=_sp("yes_word", lang), no_word=_sp("no_word", lang),
        )
        try:
            _backend_guard.check(session, "llm", bid)  # 断ったら下の except（判定できない票）に乗る（B-021）
            chat_fn = LLM_BACKENDS[bid]["chat"]
            messages = [
                {"role": "system", "content": char.get("persona_description", "")},
                {"role": "user", "content": judge_prompt},
            ]
            if not vram_lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
                raise RuntimeError(f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s")
            try:
                reply = chat_fn(messages, model, json_mode=False, options={"num_predict": 32})
            finally:
                vram_lock.release()
            results[char_id] = _sp("yes_word", lang) in reply or "yes" in reply.lower()
        except Exception:
            results[char_id] = True

    if proposer_id and proposer_id != "_keeper":
        # 人間キャラが発議: LLM がキーパーとして追加投票
        bid = default_backend if default_backend in LLM_BACKENDS else DEFAULT_LLM_BACKEND
        model = _resolve_model(bid)
        if force_approve:
            results["_keeper"] = True
        else:
            all_texts = "\n".join(
                f"{name_map.get(cid, cid)}: {text}"
                for cid, text in deliberation_texts.items()
                if text
            )
            keeper_judge_prompt = _sp("keeper_judge_prompt", lang).format(
                vote_label=vote_label, detail_text=detail_text, all_texts=all_texts,
                yes_word=_sp("yes_word", lang), no_word=_sp("no_word", lang),
            )
            try:
                _backend_guard.check(session, "llm", bid)  # 断ったら下の except に乗る（B-021）
                chat_fn = LLM_BACKENDS[bid]["chat"]
                keeper_msgs = [
                    {"role": "system", "content": _sp("keeper_system", lang) or "あなたはセッションのキーパー（GM・司会者）です。"},
                    {"role": "user", "content": keeper_judge_prompt},
                ]
                if not vram_lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
                    raise RuntimeError(f"vram_lock busy for over {_VRAM_LOCK_TIMEOUT_SECONDS:.0f}s")
                try:
                    reply = chat_fn(keeper_msgs, model, json_mode=False, options={"num_predict": 32})
                finally:
                    vram_lock.release()
                results["_keeper"] = _sp("yes_word", lang) in reply or "yes" in reply.lower()
            except Exception:
                results["_keeper"] = True
    else:
        # 人間キャラなし: キーパー票はボタンクリックで決まる
        results["_keeper"] = req.keeper_vote

    return results


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

    vote_type = pending["vote_type"]
    vote_label = pending["vote_label"]
    detail_text = pending["detail_text"]
    detail = pending["detail"]
    target_id = pending["target_id"]
    proposer_id = pending.get("proposer_id", "")

    from def_kari.resources.vram_lock import get_vram_lock
    from def_kari.settings import load_settings as _load_settings
    _vram_lock = get_vram_lock()
    _force_approve = bool(_load_settings().get("vote_force_approve", False))
    _v_lang = _load_settings().get("user_language", "ja") or "ja"

    # _end_sessionはturn_engine（session.py側）に依存するため、循環import回避のため遅延import。
    from def_kari.api.routes.session import _end_session

    results = _resolve_vote_results(
        session, req, initiative, name_map, pending, _vram_lock, _force_approve, _v_lang,
    )

    yes_count = sum(1 for v in results.values() if v)
    no_count = len(results) - yes_count
    passed = yes_count > no_count

    _expel_pending_followup = None
    if passed:
        if vote_type == "topic_change" and detail:
            session["topic"] = detail
        elif vote_type == "expel" and target_id:
            # expelの実際の後始末（initiative除去 or AI引き継ぎ・接続切断）はここでは
            # 行わず、キーパーの追加選択（vote/expel_resolve）まで遅延させる
            # （2026-08-22、「このまま人数減で続行」/「AIに引き継ぐ」の2択を追加した
            # ための再設計。副次効果として、対象者は自分の画面で投票結果を見届けて
            # から切断されるようになる）。
            session["_pending_expel_followup"] = {"target_id": target_id}
            _expel_pending_followup = {"target_id": target_id, "target_name": name_map.get(target_id, target_id)}

    # イベントバス通知（vote結果をゲームロジックレイヤーへ伝播）
    if passed:
        from def_kari.gm.events import game_event_bus, TOPIC_CHANGED, SESSION_ENDED
        if vote_type == "topic_change" and detail:
            game_event_bus.emit(session_id, TOPIC_CHANGED, {"new_topic": detail})
        elif vote_type == "end_session":
            game_event_bus.emit(session_id, SESSION_ENDED, {})

    # 以前はここで turn/round/action_count を発議時の値へ巻き戻していた。投票中は
    # ターンの進行そのものを止める（session_turn_engine._turn_progress_blocked）ように
    # したため、巻き戻すものが無い（2026-11-08）。

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
    if _expel_pending_followup:
        result_text += "\n" + _sp("vote_expel_awaiting_choice", _v_lang)
    session["history"].append({
        "role": "user",
        "content": result_text,
        "character_id": "_keeper",
    })

    session.pop("_pending_vote", None)

    # 投票結果を全タブへ配信（表示専用。決着の通知は _on_turn_progress_unblocked の VOTE_CLOSED）
    _game_event_bus.emit(session_id, "HUMAN_ACTION", {
        "character_id": "_keeper",
        "character_name": "🗳 Vote",
        "text": result_text,
        "action": "vote_result",
        "sender_role": _auth.get("role"),
        "counters": dict(session.get("counters", {})),
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
        if not session.get("_pending_expel_followup"):
            from def_kari.api.routes.session import _on_turn_progress_unblocked
            _on_turn_progress_unblocked(session_id, session)
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
        "expel_pending_followup": _expel_pending_followup,
    }


@router.post("/{session_id}/vote/cancel")
async def vote_cancel(session_id: str, _auth: dict = Depends(require_keeper)):
    """保留中の投票（発議〜確定）と追放の決定待ちを取り消し、止めていたターンの進行を戻す。

    投票中・追放の決定待ちの間はターンを進める操作を止めている（_turn_progress_blocked）。
    確定や選択のUIはキーパーのタブの状態にしか無いため、タブの再読み込み・クラッシュで
    それが失われると、確定する手段が無くなりセッションが二度と進まなくなっていた
    （2026-11-08レビュー指摘）。その逃げ道としてキーパーが取り消せるようにする。
    追放の決定待ちを取り消した場合、可決済みの追放は反映されない（対象は残る）。
    """
    session = _sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Session not found")
    pending_vote = session.pop("_pending_vote", None)
    expel = session.pop("_pending_expel_followup", None)
    if not (pending_vote or expel):
        return {"status": "nothing_pending"}
    _refund_proposer_counter(session, pending_vote)
    _v_lang = load_settings().get("user_language", "ja") or "ja"
    if expel:
        # 可決済みの追放を反映しないまま終わるので、そのことを全員に分かるように書く
        target_name = session.get("name_map", {}).get(expel.get("target_id"), expel.get("target_id", ""))
        note = (_sp("expel_cancelled_notice", _v_lang) or (
            "🗳 The passed expulsion was cancelled. {name} stays in the session"
            if _v_lang == "en" else "🗳 可決された退場を取り消しました。{name} はセッションに残ります"
        )).format(name=target_name)
    else:
        note = _sp("vote_cancelled_notice", _v_lang) or (
            "🗳 The pending vote was cancelled" if _v_lang == "en" else "🗳 保留中の投票を取り消しました"
        )
    session["history"].append({"role": "user", "content": note, "character_id": "_keeper"})
    _game_event_bus.emit(session_id, "HUMAN_ACTION", {
        "action": "vote_result", "character_id": "_keeper", "character_name": "🗳 Vote",
        "text": note, "sender_role": _auth.get("role"),
    })
    _autosave(session_id)
    from def_kari.api.routes.session import _on_turn_progress_unblocked
    _on_turn_progress_unblocked(session_id, session)
    return {"status": "cancelled", "result_text": note, "counters": dict(session.get("counters", {}))}


class VoteExpelResolveRequest(BaseModel):
    choice: str  # "continue" | "ai_handover"


@router.post("/{session_id}/vote/expel_resolve")
async def vote_expel_resolve(session_id: str, req: VoteExpelResolveRequest, _auth: dict = Depends(require_keeper)):
    """expel可決後、キーパーが「このまま人数減で続行」/「AIに引き継ぐ」のどちらを
    選んだかを反映する。vote_commit時点では対象の切断・initiative変更を一切
    行わず、この関数の実行まで遅延させている（自治規約62行目の「退場後、人数減で
    続けるか選択する」への対応＋対象者が自分の画面で結果を見届けられるようにする、
    の両方が目的、2026-08-22）。
    """
    if req.choice not in ("continue", "ai_handover"):
        raise HTTPException(400, "choice must be 'continue' or 'ai_handover'")

    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    pending = session.get("_pending_expel_followup")
    if not pending:
        return {"error": "No pending expel decision"}
    target_id = pending["target_id"]
    name_map = session["name_map"]
    target_name = name_map.get(target_id, target_id)

    _v_lang = load_settings().get("user_language", "ja") or "ja"

    if req.choice == "ai_handover":
        outcome_note = (_sp("vote_expel_handover_notice", _v_lang) or "🎩 {name} の役をAIに引き継ぎます").format(name=target_name)
    else:
        outcome_note = (_sp("vote_expel_continue_notice", _v_lang) or "🎩 {name} を退場させ、人数を減らして続行します").format(name=target_name)
    session["history"].append({"role": "user", "content": outcome_note, "character_id": "_keeper"})

    # 対象がまだ接続中なら、このブロードキャストを受け取れるうちに結果を見せる。実際の
    # 切断はこの後(300ms猶予を挟んで)行う——end_session_by_hostの「ブロードキャスト
    # タスクがWS送信を完了してから接続を閉じる」と同じ既存パターン（session_lobby.py参照）。
    _game_event_bus.emit(session_id, "HUMAN_ACTION", {
        "action": "vote_expel_resolved",
        "character_id": "_keeper",
        "character_name": "🗳 Vote",
        "text": outcome_note,
        "choice": req.choice,
        "sender_role": _auth.get("role"),
    })
    await asyncio.sleep(0.3)

    round_completed = False
    was_current_speaker = False
    if req.choice == "ai_handover":
        from def_kari.api.routes.session import _get_current_speaker
        was_current_speaker = target_id == _get_current_speaker(session)
        keeper_handed_off, expelled_participant_id = await _apply_vote_expel_handover(session_id, session, target_id)
    else:
        keeper_handed_off, expelled_participant_id, round_completed, was_current_speaker = await _apply_vote_expel(
            session_id, session, target_id,
        )

    if keeper_handed_off:
        handoff_note = _sp("keeper_handoff_notice", _v_lang)
        session["history"].append({"role": "user", "content": handoff_note, "character_id": "_keeper"})
        _game_event_bus.emit(session_id, "HUMAN_ACTION", {
            "action": "vote_result", "character_id": "_keeper", "character_name": "🗳 Vote",
            "text": handoff_note, "sender_role": _auth.get("role"),
        })

    if expelled_participant_id:
        _game_event_bus.emit(session_id, "PLAYER_LEFT", {
            "participant_id": expelled_participant_id,
            "character_id": target_id,
        })

    session.pop("_pending_expel_followup", None)
    _autosave(session_id)

    # 「人数を減らして続行」で手番中のキャラ（入力待ちの人間）を外した場合、_run_ai_turns
    # は誰にも再起動されずセッションが止まる。「AIに引き継ぐ」側（_hand_char_to_ai_control）
    # で2026-08-22に直したのと同じ問題が、こちら側に残っていた（2026-11-08）。
    # 再開は後始末（トークン無効化・切断タイマー解除・決定待ちの印の除去）がすべて
    # 終わってから行う。外したことでラウンドが完了した場合は再開しない: 通常の経路と
    # 同じく、キーパーの処理（フロントのfireKeeperTurn→applyKeeperResult）の最後で
    # 再開させる。ここで再開すると、キーパーの発言より先に次ラウンドが始まってしまう。
    # （キーパーがいるのはTRPGモードだけなので、それ以外ではラウンド完了でも再開する）
    # 「AIに引き継ぐ」側も同じ理由で、再開をここまで遅らせている（_hand_char_to_ai_control
    # にresume=Falseを渡している）。
    keeper_will_resume = round_completed and session.get("trpg_mode")
    from def_kari.api.routes.session import _on_turn_progress_unblocked
    _on_turn_progress_unblocked(
        session_id, session,
        resume_ai=was_current_speaker and not keeper_will_resume,
        allow_auto_resume=not keeper_will_resume,
    )

    return {
        "status": "ok",
        "choice": req.choice,
        "target_id": target_id,
        "keeper_handed_off": keeper_handed_off,
        "initiative": session["initiative"],
        "human_char_ids": session.get("human_char_ids", []),
        "result_text": outcome_note,
        "round": session.get("round", 1),
        "round_completed": round_completed,
        "round_seq": session.get("_round_seq", 0),
    }
