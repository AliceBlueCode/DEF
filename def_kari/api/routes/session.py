"""Session API routes: 後方互換の再エクスポート層。

session.py分割（TODO.md「session.py分割の設計」参照）完了後、実体は
session_state/session_auth/session_ws/session_persistence/session_rules/
session_image/session_lobby/session_gameplay/session_turn_engineの9モジュールに
分散している。このファイルはmain.py/public_main.pyの`session.router`/
`session.local_router`属性アクセス、および既存テストの
`from def_kari.api.routes.session import X`をそのまま動作させるための再エクスポートのみを持つ。

各名前は本来の所有モジュールから直接importする（session_turn_engine.py経由の
中継はしない）。中継だと"turn_engineが他の8モジュール全部に依存する"ように
見えてしまい、実際には使っていない大量のpass-through importが溜まる原因になった
（2026-08分割時、session_turn_engine.py内で125個のimport済み未使用名が発覚）。
"""

from def_kari.api.routes.session_state import (
    _MAX_SESSIONS,
    _NON_SERIALIZABLE_KEYS,
    _PUBLIC_SESSION_KEYS,
    _last_session_debug,
    _session_for_json,
    _session_for_public_json,
    _sessions,
    _ws_send_locks,
    local_router,
    router,
    set_main_loop,
)

from def_kari.api.routes.session_auth import (
    _INVITE_RATINGS,
    _character_json_fingerprint,
    _check_circuit_breaker,
    _check_daily_generation_limit,
    _check_generation_rate,
    _check_invite_rate,
    _check_session_create_rate,
    _check_ws_rate,
    _cleanup_expired_revoked_jtis,
    _evict_oldest_session,
    _extract_content_policy_from_json,
    _generate_invite_code,
    _get_jwt_secret,
    _invite_fail_rate,
    _invite_locked_until,
    _invite_registry,
    _record_invite_fail,
    _record_violation_and_maybe_trip,
    _release_generation_lock,
    _resolve_client_ip,
    _revoked_jtis,
    _revoked_jtis_last_cleanup,
    _session_create_rate,
    _token_currently_active,
    _try_acquire_generation_lock,
    issue_player_jwt,
    require_host,
    require_keeper,
    require_participant,
    require_player,
    revoke_token,
    verify_jwt,
)

from def_kari.api.routes.session_ws import (
    _WS_PENDING_AUTH_LIMIT_PER_IP,
    _WS_PENDING_AUTH_LIMIT_TOTAL,
    _release_ws_pending_auth_slot,
    _safe_send,
    _try_acquire_ws_pending_auth_slot,
    _ws_broadcast_handler,
    _ws_pending_auth_by_ip,
    _ws_pending_auth_total,
)

from def_kari.api.routes.session_persistence import (
    SaveSessionMediaItem,
    SaveSessionRequest,
    SessionLoadRequest,
    _AUTOSAVE_CLEANUP_INTERVAL_SEC,
    _AUTOSAVE_DIR,
    _AUTOSAVE_TTL_SEC,
    _SAFE_FILENAME_RE,
    _SESSION_HISTORY_DIRS,
    _VISITORS_DIR,
    _VISITORS_MAX_FILES,
    _autosave,
    _autosave_last_cleanup,
    _autosave_visitors,
    _cleanup_stale_autosaves,
    _delete_autosave,
    _extract_appearance_tags,
    _generate_visitor_images,
    _save_session_episodic,
    delete_saved_session,
    get_session_debug,
    list_saved_sessions,
    load_session,
    save_session,
)

from def_kari.api.routes.session_rules import (
    SaveRuleRequest,
    _DIRECTIVE_DIRS,
    _PUBLIC_DIRECTIVE_DIRS,
    _PUBLIC_RULE_DIRS,
    _RULE_DIRS,
    _is_public_request,
    _load_action_directives,
    _load_session_rules,
    get_action_directives,
    get_session_rule_detail,
    get_session_rules,
    save_session_rule,
)

from def_kari.api.routes.session_image import (
    SessionGenerateImageRequest,
    _apply_char_tags,
    _generate_session_image_impl,
    _resolve_model,
    generate_session_image,
)

from def_kari.api.routes.session_lobby import (
    AiTakeoverRequest,
    AvailableSlotsRequest,
    InviteRequest,
    JoinRequest,
    LobbyAIRequest,
    LobbyConfigRequest,
    LobbyKeeperCharRequest,
    LobbyKeeperSourceRequest,
    LobbyModeRequest,
    LobbySettingsRequest,
    SessionStartRequest,
    _build_initial_npc_state,
    _cancel_idle_shutdown,
    _load_session_prompts,
    _schedule_idle_shutdown,
    _sp,
    ai_takeover,
    create_invite,
    end_session_by_host,
    get_available_slots,
    join_session,
    leave_session,
    lobby_add_ai,
    lobby_remove_ai,
    lobby_set_keeper_char,
    set_lobby_config,
    set_lobby_keeper_source,
    set_lobby_settings,
    set_lobby_trpg_mode,
    start_session,
    update_host_role,
)

from def_kari.api.routes.session_gameplay import (
    AIKeeperRequest,
    AutoAdvanceRequest,
    CounterAdjustRequest,
    DesignateRequest,
    KeeperMessageRequest,
    NpcKnowledgeRequest,
    NpcRelationshipRequest,
    SessionDiceRollRequest,
    StatSyncRequest,
    add_npc_knowledge,
    adjust_counter,
    advance_chapter,
    advance_scene,
    ai_keeper_narrate,
    designate_next,
    get_npc_state,
    get_session,
    get_session_events,
    inject_keeper_message,
    reset_circuit_breaker,
    session_dice_roll,
    set_auto_advance,
    sync_stats,
    update_npc_relationship,
)

from def_kari.api.routes.session_voting import (
    VoteCommitRequest,
    VoteRequest,
    vote_commit,
    vote_deliberate,
)

from def_kari.api.routes.session_turn_engine import (
    BaseModel,
    DEFAULT_LLM_BACKEND,
    Depends,
    HTTPException,
    HumanTurnRequest,
    LLM_BACKENDS,
    SessionNextRequest,
    WebSocket,
    WebSocketDisconnect,
    _FLAG_UPDATED,
    _LANG_LABELS,
    _VRAM_LOCK_TIMEOUT_SECONDS,
    _ai_action_select,
    _apply_skip,
    _build_for_player,
    _build_session_context,
    _build_turn_instruction,
    _clean_history_for_retake,
    _emit_waiting_for_human,
    _end_session,
    _execute_ai_turn,
    _game_event_bus,
    _get_current_speaker,
    _handle_flag_updated,
    _is_human_char,
    _load_trpg_rulebook,
    _load_trpg_scenario,
    _log,
    _player_agent,
    _run_ai_turns,
    ai_pause,
    ai_resume,
    apply_emotion_tags,
    contains_blocked_content,
    get_character,
    human_turn_action,
    load_profiles,
    load_settings,
    next_turn,
    retake_turn,
    skip_turn,
    ws_endpoint,
)

from def_kari.api.routes.session_turn_disconnect import (
    _DEFAULT_DISCONNECT_TIMEOUT_SEC,
    _cancel_disconnect_skip,
    _disconnect_timeout_sec,
    _find_player_token,
    _maybe_schedule_disconnect_skip,
    _schedule_disconnect_skip,
)

from def_kari.api.routes.session_turn_media import (
    _generate_turn_audio,
    _generate_turn_image,
    _maybe_generate_turn_media,
    _start_background_tts,
    _synthesize_and_notify_audio,
    _synthesize_turn_audio_sync,
)
