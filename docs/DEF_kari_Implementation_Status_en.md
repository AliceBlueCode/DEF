# DEF(kari) v4.0.0 Implementation Status

This document records the implementation status of feature specifications (F-numbers) described in the Basic Design Specification.

> **v2.0.0:** Architecture migrated from Streamlit to FastAPI + React (Vite/TypeScript). See Basic Design Specification Section 2.1.

> **v2.1.x:** Added OpenAI TTS backend (5 total). T2I prompt generation mode added (current/passthrough/dedicated). LLM instructions externalized to `session_prompts.json`. `status_poll_sec` settings UI. DEF-Character repository separation. Skip greeting on same-character switch (F-26).

> **v3.0.0:** TRPG Mode Phase 1 (F-20/21/22) implemented. Rulebook/scenario management API, dice rolling, GM agent, event bus. Speech counter limit setting (`session_max_counter`) added. TRPG Mode terminology (38+ keys) added to i18n.

> **v4.0.0:** Online multiplayer (`feature/v4.0`) implemented. WebSocket real-time sync, JWT auth, invite codes (`SFW-XXX-NNN` format), 4 participant roles (host/player/gm/observer), lobby system (session mode switching, independent keeper slot management), single-flight AI turns, HUMAN_ACTION event propagation, public-port separation via Cloudflare Tunnel, LLM audit for imported characters, invite-code rating matching. See `DEF_kari_マルチプレイ設計書_内部用.md` (internal, Japanese only) and Basic Design Specification (internal) Section 7.11.

---

## Implemented

| F# | Feature | Status | Notes |
|---|---|---|---|
| F-1 | LLM Async Pipeline | ✅ Done | Core text generation pipeline |
| F-2 | LLM Backend Adapters | ✅ Done | TGW / Ollama / OpenAI / Gemini / Anthropic |
| F-3 | Periodic Polling & Event Dispatcher | ✅ Done | React frontend REST polling. `status_poll_sec` configurable from Settings tab (default 5s, persisted in localStorage) |
| F-5 | Model Selection & Profiles | ✅ Done | Per-backend model management, profile editing UI |
| F-6 | Session Mode (Multi-Agent) | ✅ Done | Multiple AI + human participants, initiative system, speech power |
| F-7 | Safety Tags | ✅ Done | 6 levels (sfw/nsfw/hentai/violence/gore/extreme) |
| F-8 | Content Filtering | ✅ Done | off/warn/mask, user-controllable |
| F-9 | i18n / Multilingual | ✅ Done | 599 keys (JP/EN) including 38+ TRPG Mode keys. LLM instructions externalized to `session_prompts.json`. Dynamic in-session messages (hardcoded Japanese strings in SessionTab.tsx etc.) are now also fully localized (2026-08-11) |
| F-10 | TTS Voice Synthesis | ✅ Done | VOICEVOX / Kokoro / Irodori / Gemini TTS / OpenAI TTS / Grok TTS |
| F-11 | TTS Auto-Play & Pipeline | ✅ Done | Session and Novel mode support |
| F-13-1 | VRAM Exclusive Control | ✅ Done | vram_lock mechanism |
| F-14 | Structured Output & Fallback Chain | ✅ Done | 4-stage fallback, field name typo auto-correction |
| F-15 | T2I Trigger | ✅ Done | 4 modes (end of cycle / start of cycle / manual / interval). T2I prompt generation mode (current/passthrough/dedicated) selectable from Settings tab |
| F-16 | Zoning (Public/Private Separation) | ✅ Done | data/public + data/private |
| F-17 | Generated Asset Management | ✅ Done | Isolated from Git tracking |
| F-18 | session_state Optimization | ✅ Done | MAX_VISIBLE_TURNS=3, trim_session, lazy loading |
| F-23 | Turn Regeneration & Undo/Redo | ✅ Done | Full/voice-only/image-only regen, configurable history count. Novel mode uses browser-native Ctrl+Z instead |
| F-25 | Publication Policy (rating classification) | ✅ Done | `content_policy`'s `rating_sexual`/`rating_violence`/`is_real_person`/`is_existing_ip` are implemented. The `origin_type` field and its automated classification logic are design-only, not implemented -- publication scope is currently managed by manually placing files under `data/public/characters/` vs `data/private/characters/` (see `docs/DEF_kari_Character_Data_Specification_en.md`) |
| F-26 | Character Switch Auto-Greeting | ✅ Done | ON/OFF configurable. Greeting skipped when switching to the same character (v2.1.1+) |
| F-27 | Meta Self-Awareness Directive | ✅ Done | content_policy-based (3 variants: default/existing_ip/real_person), injected at the top of the system prompt |
| F-28 | Novel Mode Foundation | ✅ Done | Work management, plot settings, AI candidate generation, `Chapter N + Scene M` labels |
| F-28 | Novel Mode 3-Modality | ✅ Done | TTS narration (per Scene), T2I illustration (LLM → prompt → generate) |
| F-28 | Plot file write-back | ✅ Done | `PUT /api/novel/plots/{filename}` saves directly to Git-managed plot files |
| F-28 | T2I settings dialog | ✅ Done | Backend/model fetched dynamically from `/api/settings/backends` |
| F-28 | Resizable layout | ✅ Done | Body↔thumbnail (vertical), body↔candidates (horizontal) drag handles; persisted in localStorage |
| F-28 | VRAM lock — Novel tab | ✅ Done | `/api/novel/generate` and `/api/novel/t2i` acquire/release the global vram_lock |
| —— | Character image color | ✅ Done | `base_profile.image_color` field; color picker in CharacterTab; applied to AI bubbles in ChatTab |
| —— | Sidebar collapse | ✅ Done | `Sidebar.tsx` collapsed state, ◀/▶ toggle button |
| —— | Thought Tab | ✅ Done | Free-text AI thought experiments; `GET/POST /api/thought/` |
| —— | T2I Model Profile Dialog | ✅ Done | ⚙ dialog in Novel tab; per-backend model selection |
| —— | Session rules added | ✅ Done | manzai / rakugo presets added |
| —— | Action directives added | ✅ Done | standard preset added |
| —— | i18n foundation (i18n.tsx) | ✅ Done | React-side i18n base; Japanese + English |
| —— | DEF-Character repository separation | ✅ Done | External character repository linked via `CHARACTER_REPO_PATH`. Falls back to legacy `data/characters/` format |
| F-20 | TRPG Rulebook Injection | ✅ Done | JSON format. Loaded from `data/public/trpg_rules/` / `data/private/trpg_rules/`. ID validation included |
| F-21 | GM Agent | ✅ Done | Designate a character as GM. Async notification via event bus (`game_event_bus`). Judgment results auto-injected into session history |
| F-22 | Dice Roll & Character Sheet | ✅ Done | `NdM±K` notation, success/critical/fumble/failure judgment, opposed rolls, damage rolls. Scenario management API also provided |
| —— | Online Multiplayer (v4.0+) | ✅ Done | WebSocket sync, JWT auth, invite codes, 4 participant roles, lobby, GM role (`waiting_for_gm`), public exposure via Cloudflare Tunnel. See `DEF_kari_マルチプレイ設計書_内部用.md` (internal, Japanese only) and Basic Design Specification Section 7.11 |

---

## Not Yet Implemented (Next Phase)

| F# | Feature | Status | Notes |
|---|---|---|---|
| F-4 | Dynamic Generation (Consistency Provider) | ❌ Not implemented | Automatic visual consistency. Manual T2I generation available as workaround |
| F-12 | Smart Resource Manager | ⏸ On hold | Core concern covered by F-13-1 (vram_lock). CPU/GPU hybrid auto-detection not needed with current architecture |
| F-13-2 | Lightweight Response Mode | ⏸ On hold | Not needed with current architecture |
| F-13-3 | Diffusers Offload Control | ⏸ On hold | Not needed with current architecture |
| F-19 | Export/Import | ⏸ On hold | Pending data structure stabilization |
| F-24-1 | Episode Structured Output | ❌ Not implemented | narration/dialogue/tags/choices JSON Schema |
| F-24-3 | Branch Selection + Git Integration | ❌ Not implemented | choices → Git branch |

> **Note (corrected 2026-08-11):** This table previously listed "F-24 Episode Mode Foundation — ❌ Not implemented" (duplicated by mistake). That functionality is actually done — see "F-28 Novel Mode Foundation" / "F-28 Novel Mode 3-Modality" in the Implemented table above. The F-24 vs. F-28 numbering conflicts with the Basic Design Specification and will be reconciled when that document is next reviewed.

---

## Known Limitations

| Item | Description |
|---|---|
| Session history token limit | Long sessions may reach LLM context limit |
| Irodori-TTS CUDA | venv may default to CPU after uv sync |
| Backend multi-start | PID file guard instability |

---

## Supported Backends

| Type | Count | Details |
|---|---|---|
| LLM | 5 | Text Generation WebUI / Ollama / OpenAI / Gemini / Anthropic |
| TTS | 6 | VOICEVOX / Kokoro / Irodori / Gemini TTS / OpenAI TTS / Grok TTS |
| T2I | 5 | A1111 / ComfyUI / Hugging Face / Civitai / OpenAI Images |

All three also support connecting to any service exposing an OpenAI-compatible API (LM Studio, vLLM, llama.cpp server, Groq, OpenRouter, etc.) via the `compatible` adapters, not counted in the totals above.

---

## Tests

| Type | Count | Result |
|---|---|---|
| Unit Tests | 553 | All passing |

Measurement command: `python -m pytest def_kari tests` (excludes `poc/` and `llamacpp_tools/` PoC/vendor tests, as of 2026-08-11)

---

This document reflects the status as of v4.0.0. For the latest status, see the repository's Issues and release notes.
