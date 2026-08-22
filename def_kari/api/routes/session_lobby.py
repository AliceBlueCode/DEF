"""Sessionのロビー・参加系: start/join/leave/invite/AI引き継ぎ/ロビー設定。
`session.py`分割の一部。
"""

import asyncio
import logging
import random
import secrets
import threading
import uuid as _uuid_mod

from fastapi import Header, HTTPException, Depends, Request
from pydantic import BaseModel
from jose import JWTError as _JWTError

from def_kari.characters import load_profiles, get_character
from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.gm.context_builder import (
    load_trpg_rulebook as _load_trpg_rulebook,
    load_trpg_scenario as _load_trpg_scenario,
)
from def_kari.gm.events import game_event_bus as _game_event_bus
from def_kari.safety.character_audit import audit_character_json
from def_kari.safety.filters import character_rating_exceeds_invite
from def_kari.safety.content_filter import contains_blocked_content

from def_kari.api.routes.session_state import router, _sessions, _MAX_SESSIONS, _ws_send_locks
from def_kari.api.routes.session_auth import (
    require_host,
    issue_player_jwt,
    verify_jwt,
    revoke_token,
    _generate_invite_code,
    _invite_registry,
    _INVITE_RATINGS,
    _check_invite_rate,
    _record_invite_fail,
    _check_session_create_rate,
    _check_generation_rate,
    _evict_oldest_session,
    _character_json_fingerprint,
    _extract_content_policy_from_json,
    _resolve_client_ip,
)
from def_kari.api.routes.session_rules import _is_public_request, _load_session_rules
from def_kari.api.routes.session_persistence import (
    _autosave,
    _autosave_visitors,
    _generate_visitor_images,
    _delete_autosave,
    _save_session_episodic,
)

_log = logging.getLogger("def.session")

# 実体はdef_kari/prompts.py(gm/パッケージからも使う中立な置き場、2026-08-21移設)。
# session_voting.py・session.py(再export)が既存の名前で参照しているため
# エイリアスとして残す。
from def_kari.prompts import load_session_prompts as _load_session_prompts, sp as _sp


def _build_initial_npc_state(scenario_id: str, public_only: bool = False) -> dict:
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
    scenario = _load_trpg_scenario(scenario_id, public_only=public_only)
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


def _schedule_idle_shutdown(session_id: str, delay: int = 300) -> None:
    """全員切断後 delay 秒で AI タスクを停止する。再接続時はキャンセルする。"""
    import asyncio

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

    # 8.28対策: 無認証の公開ポート経由の/startは、rule_set/trpg_rulebook/trpg_scenarioに
    # data/private/配下のIDを直接指定してprivateコンテンツをセッションへ取り込める
    # （8.22で塞いだのは「一覧・詳細取得」のみで、「/start時点での選択」は
    # 「セッションが既に選んだものは信頼する」という前提で対象外にしていたが、
    # その前提は/start自体が公開ポートに乗っている場合は成立しない）。
    _public_req = _is_public_request(request)

    session_id = secrets.token_urlsafe(16)
    profiles = load_profiles()
    # 8.35対策: character_idsも8.28と同型の穴——load_profiles()はpublic/private無差別に
    # 読み込むため、公開ポート経由で私有キャラクターのIDを直接指定すれば、そのキャラの
    # persona_descriptionでAIが実際に喋り出し、history経由（allowlist内）で間接的に
    # ペルソナの内容が漏れる経路が成立していた。公開ポート経由ではdata/public/配下に
    # 存在しないIDをそのまま除外する（存在しないキャラとして扱う＝一覧化はしない）。
    if _public_req:
        from def_kari.api.routes.characters_common import find_char_dir as _find_char_dir_pub
        req.character_ids = [cid for cid in req.character_ids if _find_char_dir_pub(cid, public_only=True) is not None]
    if not req.online_mode:
        for cid in req.character_ids:
            char = get_character(cid, profiles)
            if char and char.get("entity_type") == "base_entity":
                raise HTTPException(400, f"base_entity '{cid}' はセッションに参加できません")
    all_name_map = {}
    char_colors = {}
    for cid in req.character_ids:
        char = get_character(cid, profiles)
        all_name_map[cid] = char.get("name", cid) if char else cid
        # image_colorは公開ポート経由のゲストがcharacters一覧APIを読めないため
        # （ローカル専用ポートにしかない）、GET /{session_id}経由での代替配信元
        # として持たせる（2026-08-16、TODO.md「ゲスト側imageColor」対応）。
        if char and char.get("image_color"):
            char_colors[cid] = char["image_color"]
    keeper_char_id = req.keeper_char_id if req.keeper_char_id in req.character_ids else ""
    player_ids = [c for c in req.character_ids if c != keeper_char_id]
    initiative = [] if req.online_mode else random.sample(player_ids, len(player_ids))
    name_map = {cid: all_name_map[cid] for cid in player_ids}

    if len(_sessions) >= _MAX_SESSIONS:
        _evict_oldest_session()
    _rule_data = _load_session_rules(public_only=_public_req).get(req.rule_set, {})
    rules = _rule_data.get("rules", [])
    scene = _rule_data.get("scene", "")
    rule_style = _rule_data.get("style", "discussion")
    rule_max_chars = _rule_data.get("max_chars", 0)
    rule_max_rounds = _rule_data.get("max_rounds", 0)
    rule_reinforced_rules = _rule_data.get("reinforced_rules", [])
    char_backends = {
        cid: bid
        for cid, bid in req.char_backends.items()
        if cid in req.character_ids and bid in LLM_BACKENDS
    }
    _skill_pool_init = 0
    if req.trpg_mode and req.trpg_rulebook:
        _rb = _load_trpg_rulebook(req.trpg_rulebook, public_only=_public_req)
        _skill_pool_init = int(_rb.get("skill_point_pool", 0))

    _sessions[session_id] = {
        "id": session_id,
        "initiative": initiative,
        "name_map": name_map,
        "char_colors": char_colors,
        "topic": req.topic,
        "backend": req.backend,
        "char_backends": char_backends,
        "rule_set": req.rule_set,
        "rules": rules,
        "style": rule_style,
        "max_chars": rule_max_chars,
        "max_rounds": rule_max_rounds,
        "reinforced_rules": rule_reinforced_rules,
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
        "npc_state": _build_initial_npc_state(req.trpg_scenario, public_only=_public_req),
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
        # 持ち込みキャラのimageColorも同じ両形式判定で抽出する。ホスト自身の
        # characters一覧APIに載らない（guest_xxxはdata/visitors/にしか永続化されない）
        # ため、これが唯一の配信経路になる（2026-08-16、TODO.md「持ち込みキャラの
        # imageColor」対応、_extract_content_policy_from_jsonと同じ抽出パターン）。
        display_color = _cj.get("image_color") or next(
            (v["base_profile"]["image_color"] for v in _cj.values()
             if isinstance(v, dict) and isinstance(v.get("base_profile"), dict) and v["base_profile"].get("image_color")),
            ""
        )
        # イニシアティブと名前マップに追加（オンラインセッションで参加者が埋めていく）
        if char_id not in sess["initiative"]:
            sess["initiative"].append(char_id)
        sess["name_map"][char_id] = display_name
        if display_color:
            sess.setdefault("char_colors", {})[char_id] = display_color

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
        # _cancel_disconnect_skipはturn_engine（session.py側、まだ未抽出）に依存するため
        # 循環import回避のため呼び出し時に遅延import。
        from def_kari.api.routes.session import _cancel_disconnect_skip
        _cancel_disconnect_skip(session_id, char_id)
    _keeper_handed_off = False
    if char_id and char_id == sess.get("keeper_char_id"):
        # 自治規約62行目: 「キーパーが退場した場合はAIキーパーへ交代してセッションを
        # 継続する」。expel（4006-4013行目）と同じ扱い。空文字列にすると
        # ai_keeper_narrate()が自動的に無名AIキーパーにフォールバックする。
        # 従来はexpelのみで処理しており、明示的な退室（このパス）では
        # keeper_char_idが宙に浮いたまま残っていた。
        sess["keeper_char_id"] = ""
        sess["keeper_char_name"] = ""
        _keeper_handed_off = True
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
    # 8.30対策: playersからのトークン除去をautosaveへ即座に反映する。以前はここで
    # autosaveしておらず、退室直後にプロセスがクラッシュ/再起動すると、起動時復元
    # （_AUTOSAVE_DIR走査）が古い players を丸ごと復元してしまい、かつ_revoked_jtis
    # はメモリ上のみで空に戻るため、退室済みトークンが認証を再び通ってしまい得た
    # （require_*側の_token_currently_activeで最終的には塞がっているが、
    # データ自体を鮮度高く保つのが根本対応）。
    if _keeper_handed_off:
        from def_kari.settings import load_settings as _load_settings
        _v_lang = _load_settings().get("user_language", "ja") or "ja"
        _notice = _sp("keeper_handoff_notice", _v_lang)
        sess["history"].append({
            "role": "user",
            "content": _notice,
            "character_id": "_keeper",
        })
        _game_event_bus.emit(session_id, "HUMAN_ACTION", {
            "character_id": "_keeper",
            "character_name": "🎩 Keeper",
            "text": _notice,
            "action": "keeper_handoff",
            "counters": dict(sess.get("counters", {})),
        })

    _autosave(session_id)

    _game_event_bus.emit(session_id, "PLAYER_LEFT", {
        "participant_id": participant_id,
        "character_id": char_id,
    })
    return {"status": "ok"}


class AiTakeoverRequest(BaseModel):
    character_id: str


async def _resume_ai_turns_for(session_id: str, sess: dict) -> None:
    """ai_resumeエンドポイントと全く同じ手順でAIターン処理を再起動する。"""
    from def_kari.api.routes.session_turn_engine import _run_ai_turns
    sess["ai_paused"] = False
    ai_task = sess.get("ai_task")
    if not ai_task or ai_task.done():
        sess["ai_task"] = asyncio.create_task(_run_ai_turns(session_id))


def _hand_char_to_ai_control(session_id: str, sess: dict, character_id: str) -> None:
    """human_char_idsから外す、AI引き継ぎの中核処理。ai_takeoverエンドポイント本体と、
    投票expelの「AIに引き継ぐ」follow-up（session_voting.py _apply_vote_expel_handover）
    の両方から呼ばれる共有実装（重複を避けるための切り出し、2026-08-22）。

    引き継ぎ対象が現在まさにWAITING_FOR_HUMAN中のターン担当キャラだった場合、
    human_char_idsから外すだけではAIターン処理が自動的に再開されない——
    _run_ai_turns（session_turn_engine.py）は人間ターンに当たると1回きりで
    リターンする一方通行のコルーチンで、human_char_idsの変化を監視する仕組みが
    どこにも無いため、誰かが明示的にai_resume相当の処理を呼ばない限りセッションが
    止まったまま進まなくなる（2026-08-22、実機でexpelのAI引き継ぎ直後に
    セッションが停止する不具合として発覚）。対象が現在のターンであればai_resumeと
    同じ手順で再開する。ai_takeover（同期エンドポイント）とvote_expel_resolve
    （非同期エンドポイント）の両方から呼ばれるため、_ws_broadcast_handler
    （session_ws.py）と同じ「実行中ループの有無で経路を切り替える」パターンで
    asyncio.create_taskを安全にスケジュールする。
    """
    human_ids: list = sess.setdefault("human_char_ids", [])
    if character_id in human_ids:
        human_ids.remove(character_id)

    if sess.get("lobby_active"):
        return
    from def_kari.api.routes.session_turn_engine import _get_current_speaker
    if character_id != _get_current_speaker(sess):
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_resume_ai_turns_for(session_id, sess))
    except RuntimeError:
        from def_kari.api.routes import session_state as _session_state
        if _session_state._main_loop and _session_state._main_loop.is_running():
            asyncio.run_coroutine_threadsafe(_resume_ai_turns_for(session_id, sess), _session_state._main_loop)


@router.post("/{session_id}/ai_takeover")
def ai_takeover(session_id: str, req: AiTakeoverRequest, auth: dict = Depends(require_host)):
    """退室したプレイヤーのキャラ枠を AI に引き継ぐ（ホストのみ）。"""
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    if req.character_id not in sess.get("initiative", []):
        raise HTTPException(404, "Character not in session")
    if req.character_id not in sess.get("human_char_ids", []):
        raise HTTPException(409, "Character is already AI-controlled")
    _hand_char_to_ai_control(session_id, sess, req.character_id)
    return {"status": "ok", "character_id": req.character_id, "human_char_ids": sess.get("human_char_ids", [])}


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
    import asyncio
    await asyncio.sleep(0.3)
    # _end_sessionはturn_engine（session.py側、まだ未抽出）に依存するため、循環import
    # 回避のため呼び出し時に遅延import。
    from def_kari.api.routes.session import _end_session
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
    # human_turn_actionのオーナーシップチェック（session_turn_engine.py
    # _check_human_turn_authorization）がhostロールの持ちキャラ判定に使う。
    # 空文字なら「ホストはキーパー専任、人間ターンを一切送信できない」を意味する。
    sess["host_char_id"] = req.host_char_id
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
            if char.get("image_color"):
                sess.setdefault("char_colors", {})[req.host_char_id] = char["image_color"]
            if char.get("player_type") == "human":
                sess.setdefault("human_char_ids", []).append(req.host_char_id)
    # オンラインセッションのinitiativeは参加/追加された順（join_session・
    # lobby_add_ai・上のホストキャラ追加、いずれも.append）で積み上がるだけで、
    # ここまでランダム化する処理が無かった。オフラインセッション（start_session、
    # random.sample使用）と非対称で、常に最初に参加した人間が1番手固定になる
    # バグだった（2026-08-16、ユーザーが実機で発見）。ロビー解除＝ゲーム開始の
    # このタイミングで1回だけシャッフルする。
    random.shuffle(sess["initiative"])
    # ロビー解除 → 参加者全員に通知
    sess["lobby_active"] = False
    from def_kari.gm.events import game_event_bus, SESSION_STARTED
    game_event_bus.emit(session_id, SESSION_STARTED, {
        "initiative": sess["initiative"],
        "name_map": sess.get("name_map", {}),
        "participants": sess.get("joined_participants", []),
    })
    # 最初のターンが人間なら WAITING_FOR_HUMAN を即時通知（_run_ai_turns を経由しないため）
    # _get_current_speaker/_is_human_char/_maybe_schedule_disconnect_skipはturn_engine
    # （session.py側、まだ未抽出）に依存するため、循環import回避のため遅延import。
    from def_kari.api.routes.session import (
        _get_current_speaker,
        _is_human_char,
        _maybe_schedule_disconnect_skip,
    )
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
def set_lobby_settings(session_id: str, req: LobbySettingsRequest, request: Request, auth: dict = Depends(require_host)):
    """ロビー中にセッション設定（お題・ルールセット・ルールブック・シナリオ）を変更する。

    /start 時に確定する派生データ（rules/scene・skill_pool・npc_state）もここで再構築する。
    省略されたフィールドは変更しない。ロビー解除後は 409。
    """
    sess = _sessions.get(session_id)
    if not sess:
        raise HTTPException(404, "Session not found")
    if not sess.get("lobby_active"):
        raise HTTPException(409, "Session already started")
    _public_req = _is_public_request(request)  # 8.28対策: /startと同じ理由
    if req.topic is not None:
        sess["topic"] = req.topic
    if req.rule_set is not None:
        sess["rule_set"] = req.rule_set
        _rule_data = _load_session_rules(public_only=_public_req).get(req.rule_set, {})
        sess["rules"] = _rule_data.get("rules", [])
        sess["style"] = _rule_data.get("style", "discussion")
        sess["max_chars"] = _rule_data.get("max_chars", 0)
        sess["max_rounds"] = _rule_data.get("max_rounds", 0)
        sess["reinforced_rules"] = _rule_data.get("reinforced_rules", [])
        sess["scene"] = _rule_data.get("scene", "")
    if req.trpg_rulebook is not None:
        sess["trpg_rulebook"] = req.trpg_rulebook
        _rb = _load_trpg_rulebook(req.trpg_rulebook, public_only=_public_req) if req.trpg_rulebook else {}
        _pool = int(_rb.get("skill_point_pool", 0))
        # 開始前なので既存参加者の技能ポイントプールも新ルールブック値でリセットする
        sess["skill_pool"] = {cid: _pool for cid in sess.get("skill_pool", {})}
    if req.trpg_scenario is not None:
        sess["trpg_scenario"] = req.trpg_scenario
        sess["npc_state"] = _build_initial_npc_state(req.trpg_scenario, public_only=_public_req)
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
def lobby_add_ai(session_id: str, req: LobbyAIRequest, request: Request, auth: dict = Depends(require_host)):
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
    # 8.35対策: /startのcharacter_idsと同じ穴。公開ポート経由では、hostトークン自体が
    # 攻撃者自身の場合があるため（自分で/startしてhostになれる）、data/public/以外の
    # キャラクターは追加不可にする。
    if _is_public_request(request):
        from def_kari.api.routes.characters_common import find_char_dir as _find_char_dir_pub
        if _find_char_dir_pub(char_id, public_only=True) is None:
            raise HTTPException(404, "Character not found")
    profiles = load_profiles()
    char = get_character(char_id, profiles)
    if not char:
        raise HTTPException(404, "Character not found")
    if char.get("player_type") == "human":
        raise HTTPException(400, "Cannot add human character as AI slot")
    sess["initiative"].append(char_id)
    sess["name_map"][char_id] = char.get("name", char_id)
    if char.get("image_color"):
        sess.setdefault("char_colors", {})[char_id] = char["image_color"]
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
