# DEF(kari) Multiplayer API Reference

This document defines the wire protocol for online multiplayer sessions (v4.0+). Use it as a reference when consuming the session API from something other than DEF's own frontend -- building an alternative client, a session-state monitoring tool, and so on.

For participant roles and the table's autonomy rules (speech power, voting, Round/Turn/Action progression), see `docs/DEF_TRPG_Table_Autonomy_Rules_en.md`. For terminology, see Chapter 8 of `docs/DEF_Glossary_en.md`.

-----

## 1. Invite Code Specification

The code embeds the session rating, so its content is understandable at a glance.

```
Format: {RATING}-{ALPHA3}-{NUM3}
Examples:
  SFW-ABK-492   All ages
  R15-GHM-837   Mild violence/horror present
  R18-XPQ-264   Adult content
  UNL-RTK-519   Unrestricted (deferred to zoning settings)
```

- Excluded characters: `O` (confusable with zero), `I` (confusable with the digit 1), `0`, `1`
- Character set: 24 uppercase letters A-Z (excluding O, I) + 8 digits 2-9 (excluding 0, 1)
- Expiry: until the session ends
- Entropy: with the rating fixed, 24³x8³ ≈ 7.1 million combinations. This is designed to be used together with IP-based rate limiting (10/min, locked for 1 hour after 10 failures) -- the size of the code space alone is not treated as the basis for its strength
- The join screen reflects the rating in the UI (color-coding, etc.). Even if the code is shared as-is over Discord or chat, the recipient can tell the rating from the code itself

-----

## 2. API Endpoints

```
POST /api/session/join
  body: { invite_code, character_json (guest character), join_as_gm: bool }
  response: { player_token (JWT), session_id, character_id, role, lobby_active, display_name }

POST /api/session/available-slots
  body: { invite_code }
  response: { human_slots, online_mode, gm_taken, waiting_for_gm, trpg_mode }
  -> Fetches slot status from an invite code (for the join dialog)

POST /api/session/{session_id}/invite
  -> Issues an invite code (host only)

PATCH /api/session/{session_id}/host_role?is_keeper=bool
  -> Switches the host's role (keeper: observe/manage progression, player: control a character)

PATCH /api/session/{session_id}/lobby/mode
  body: { trpg_mode: bool }
  -> Switches TRPG mode / normal session (only valid during the lobby, 409 after start)

PATCH /api/session/{session_id}/lobby/keeper_source
  body: { waiting_for_gm: bool }
  -> Switches the Keeper slot between AI auto-progression and waiting for a participant

POST /api/session/{session_id}/lobby/set_keeper_char
  body: { character_id: string }  # empty string = clear
  -> Assigns/clears the character acting as the AI Keeper during the lobby.
  -> Only meaningful in TRPG mode with AI auto-progression.
  -> Even without an assignment, auto-progression continues as an anonymous
     AI Keeper (generic "Keeper" display).
  -> Rejects a character already in the initiative, or a human-type character

PATCH /api/session/{session_id}/lobby/settings
  body: { topic?, rule_set?, trpg_rulebook?, trpg_scenario?, max_players? }
  -> Changes session settings during the lobby (omitted fields are left unchanged).
  -> Derived data (rules/scene, skill_pool, npc_state) is also rebuilt. 409 after start.
  -> max_players defaults to 4 when created online. The join capacity check is
     based on the initiative length (AI slots + joined players); observers/GM
     are excluded from capacity

PATCH /api/session/{session_id}/auto_advance
  body: { enabled: bool }
  -> Toggles auto-advance mode (session state). Broadcasts AUTO_ADVANCE_CHANGED to all tabs.
  -> Progression authority always belongs to exactly one party: gm only when a human
     gm is present (host gets 403), host only in an AI-Keeper configuration

WS   /api/session/{session_id}/ws
  -> WebSocket connection endpoint (see Chapter 3 below for details)

GET  /api/session/{session_id}
  headers: Authorization: Bearer {token}  # participant token required (host/player/gm/observer)
  -> Returns the entire session (the full history log, initiative, etc., with
     sensitive fields such as auth tokens/invite codes excluded). Readable only
     with a participant token for that session (no longer readable after the
     token is revoked by leaving or being expelled). History pagination is
     unimplemented -- the full log is returned every time. Response bloat as a
     session grows large is a known limitation
```

In addition to the above, session-progression actions such as submitting a human turn, voting, and leaving are performed via individual REST endpoints such as `POST /{session_id}/human_turn` (see Chapter 3).

-----

## 3. WebSocket

### 3.1 Connection and Authentication (first-message auth)

After connecting to `WS /api/session/{session_id}/ws`, the client sends `{"type": "auth", "token": "..."}` as its first message (the token is deliberately not included in the URL query string, to avoid leaking it into logs or browser history).

- Auth success: begins normal receiving
- Auth failure: `close(code=4001)`
- Session does not exist: `close(code=4004)`

To keep the connection alive, the server sends `{"type": "ping"}` every 30 seconds (a countermeasure for Cloudflare Tunnel's 100-second idle timeout). The client responds with `{"type": "pong"}`.

### 3.2 Client -> Server Messages

| type | Payload | Timing |
|---|---|---|
| `auth` | `{token: string}` | Immediately after WS connection (mandatory first message) |
| `pong` | None | Upon receiving a ping from the server |

**No client -> server WS messages exist other than `auth`/`pong`.** All session-progression actions -- submitting a human turn, voting, leaving, Keeper speech, etc. -- go through individual REST endpoints (e.g. `POST /{session_id}/human_turn`), and the results are delivered over WS as the events below, via `game_event_bus`. The WebSocket functions as a one-way notification channel from server to client.

### 3.3 Server -> Client Messages

Delivered messages come in two shapes.

- **Via `game_event_bus` (most messages):** a 5-field structure, `{"id", "type", "session_id", "payload": {...}, "timestamp"}`. Read the contents from under `payload` (not directly under `type`)
- **`ping`/`error` (keepalive/rate limiting):** sent directly as `{"type": "..."}` with no `payload` wrapper

| type | Contents of payload | Timing |
|---|---|---|
| `ping` | (no payload wrapper, no fields) | Every 30 seconds (keepalive) |
| `error` | (no payload wrapper) `{code: string}` | Rate limit exceeded, etc. (`code: "rate_limit"`) |
| `WAITING_FOR_HUMAN` | `{character_id, character_name, round, counters}` | When a human turn starts. Also re-sent immediately after reconnection if currently waiting on a human turn |
| `HUMAN_ACTION` | `{character_id, character_name, text, action, ...}` (`action` is one of `"speak"`/`"vote"`/`"skip"`/`"keeper"`, etc.) | A human's speech, vote, Keeper speech, automatic timeout skip, etc. |
| `AI_TURN_COMPLETED` | The full AI turn generation result (`text`, `character_id`, `judgments`, `advance_scene`, etc.) | When the server's autonomous AI turn completes |
| `AI_ERROR` | `{error: string}` | On AI turn generation failure |
| `JUDGMENT_RESOLVED` | `{character_id, stat_name, notation, roll, judgment_value, success, critical, fumble, ...}` | When a dice judgment is resolved (TRPG mode) |
| `SCENE_NARRATED` | `{text, judgments}` | When the AI Keeper generates narration |
| `TOPIC_CHANGED` | `{new_topic}` | When a topic-change vote passes |
| `FLAG_UPDATED` | `{key, value, gm_only}` | When a story flag is updated |
| `PLAYER_JOINED` | Full participant info (same shape as the `/join` response) | When a participant joins |
| `PLAYER_LEFT` | `{participant_id, character_id}` | On intentional leave or an expel vote |
| `PLAYER_DISCONNECTED` | `{participant_id, character_id, timeout_sec}` | When a player disconnect is detected |
| `PLAYER_RECONNECTED` | `{participant_id, character_id}` | On reconnection |
| `SESSION_STARTED` | `{initiative, name_map, participants}` | When the lobby is dissolved and the session starts |
| `SESSION_ENDED` | `{}` | When the session ends |
| `LOBBY_UPDATE` | Lobby configuration change details (contents vary by call site) | On participant/slot configuration changes during the lobby |
| `AUTO_ADVANCE_CHANGED` | `{enabled: bool}` | When auto-advance mode is toggled |
| `VISITOR_ICON_READY` | `{character_id}` | When a guest character's icon/standing art generation completes |
| `TURN_IMAGE_READY` | `{character_id, round, turn, url}` | When an AI turn's auto-generated illustration completes |
| `TURN_AUDIO_READY` | `{character_id, round, turn, url}` | When an AI turn's auto-narration TTS synthesis completes |
| `AUDIO_READY` | `{character_id, request_id, url}` | When TTS synthesis completes for a vote-defense round or a human player's own speech |
| `SESSION_IMAGE` | `{url}` | When the Keeper manually generates a scene illustration |
| `CHARACTER_AUDIT_SKIPPED` | `{character_id, reason}` | When a guest character's LLM audit fails open (e.g. on timeout) |

Regarding `participant_id`: since there can be multiple observers/Keepers with `char_id=""`, `PLAYER_LEFT`/`PLAYER_DISCONNECTED`/`PLAYER_RECONNECTED` identify the target uniquely by `participant_id` rather than `character_id`.

### 3.4 WebSocket Close Codes

| Code | Meaning |
|---|---|
| `4001` | Auth failure (no token / invalid) |
| `4004` | Session does not exist |
| `1008` | Forced disconnect due to JWT secret regeneration |

-----

## 4. Error Code System

### HTTP

| Status | Purpose |
|---|---|
| `400` | Malformed request / validation error. Also used when a guest character fails the LLM audit (`detail: "Character content rejected: {reason}"`) |
| `401` | JWT missing, expired, or has an invalid signature |
| `403` | Insufficient role (e.g. an observer attempting an action) |
| `404` | Session or character does not exist |
| `409` | Human slots full / invite code collision |
| `422` | Pydantic validation failure (FastAPI default) |
| `429` | Rate limit exceeded (e.g. invite code brute-forcing) |

### Application Errors (the `code` field within a WS message)

| code | Meaning |
|---|---|
| `rate_limit` | Too many WebSocket messages sent in a short time |

`rate_limit` is currently the only application-level error on the WS side. The human-slot-full check happens at `POST /api/session/join` time (before the WS connection), so it is represented as HTTP `409` instead.

-----

## Related Documents

- `docs/DEF_kari_Basic_Design_Specification_en.md`: Chapter 3 (Asynchronous Processing and Real-Time Notification Model), Chapter 7 (Multi-Agent Control)
- `docs/DEF_TRPG_Table_Autonomy_Rules_en.md`: Participant roles, speech power, voting, and other autonomy rules
- `docs/DEF_kari_User_Guide_en.md`: How to use online sessions (for end users)
- `docs/DEF_Glossary_en.md`: Terminology definitions
