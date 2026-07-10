# DEF(kari) v2.0.0 Implementation Status

This document records the implementation status of feature specifications (F-numbers) described in the Basic Design Specification.

> **v2.0.0:** Architecture migrated from Streamlit to FastAPI + React (Vite/TypeScript). See Basic Design Specification Section 2.1.

---

## Implemented

| F# | Feature | Status | Notes |
|---|---|---|---|
| F-1 | LLM Async Pipeline | ✅ Done | Core text generation pipeline |
| F-2 | LLM Backend Adapters | ✅ Done | TGW / Ollama / OpenAI / Gemini / Anthropic |
| F-3 | Periodic Polling & Event Dispatcher | ✅ Done | React frontend uses REST polling |
| F-5 | Model Selection & Profiles | ✅ Done | Per-backend model management, profile editing UI |
| F-6 | Session Mode (Multi-Agent) | ✅ Done | Multiple AI + human participants, initiative system, speech power |
| F-7 | Safety Tags | ✅ Done | 6 levels (sfw/nsfw/hentai/violence/gore/extreme) |
| F-8 | Content Filtering | ✅ Done | off/warn/mask, user-controllable |
| F-9 | i18n / Multilingual | 🔶 Partial | 164 keys (JP/EN). ~30 dynamic messages in sessions not yet localized |
| F-10 | TTS Voice Synthesis | ✅ Done | VOICEVOX / Kokoro / Irodori / Gemini TTS |
| F-11 | TTS Auto-Play & Pipeline | ✅ Done | Session and Episode support |
| F-13-1 | VRAM Exclusive Control | ✅ Done | vram_lock mechanism |
| F-14 | Structured Output & Fallback Chain | ✅ Done | 4-stage fallback, field name typo auto-correction |
| F-15 | T2I Trigger | ✅ Done | 4 modes (end of cycle / start of cycle / manual / interval) |
| F-16 | Zoning (Public/Private Separation) | ✅ Done | data/public + data/private |
| F-17 | Generated Asset Management | ✅ Done | Isolated from Git tracking |
| F-18 | session_state Optimization | ✅ Done | MAX_VISIBLE_TURNS=3, trim_session, lazy loading |
| F-23 | Turn Regeneration & Undo/Redo | ✅ Done | Full/voice-only/image-only regen, configurable history. Novel mode uses browser-native Ctrl+Z and does not implement Undo/Redo |
| F-24 | Episode Mode Foundation | ✅ Done | Work management, plot settings, AI candidates, `Chapter N + Scene M` labels |
| F-24 | Episode Mode 3-Modality | ✅ Done | TTS narration (per-Scene), T2I illustration (LLM → prompt → generate) |
| F-24 | Plot file write-back | ✅ Done | `PUT /api/novel/plots/{filename}` — saves directly to source file for Git-managed plots |
| F-24 | T2I settings dialog | ✅ Done | Backend / model fetched dynamically from `/api/settings/backends` |
| F-24 | Resizable layout | ✅ Done | Body↔thumbnail (vertical), body↔candidates (horizontal) drag handles; persisted in localStorage |
| F-13-1 | VRAM lock — Novel tab | ✅ Done | `/api/novel/generate` and `/api/novel/t2i` acquire/release the global vram_lock |
| F-25 | origin_type & Publication Policy | ✅ Done | original/reconstructed_persona/personification/derivative |
| F-26 | Character Switch Auto-Greeting | ✅ Done | ON/OFF configurable |
| F-27 | Meta Self-Awareness Directive | ✅ Done | content_policy-based (3 variants: default/existing_ip/real_person), injected at the top of the system prompt |
| —— | Character image color | ✅ Done | `base_profile.image_color` field; color picker in CharacterTab; applied to AI bubbles in ChatTab |
| —— | Sidebar collapse | ✅ Done | `Sidebar.tsx` collapsed state, ◀/▶ toggle button |
| —— | Thought Tab | ✅ Done | Free-text AI thought experiments; `GET/POST /api/thought/` |
| —— | T2I Model Profile Dialog | ✅ Done | ⚙ dialog in Novel tab; per-backend model selection |
| —— | Session rules added | ✅ Done | manzai / rakugo presets added |
| —— | Action directives added | ✅ Done | standard preset added |
| —— | i18n foundation (i18n.tsx) | ✅ Done | React-side i18n base; Japanese + English |

---

## Not Yet Implemented (Next Phase)

| F# | Feature | Status | Notes |
|---|---|---|---|
| F-4 | Dynamic Generation (Consistency Provider) | ❌ Not implemented | Automatic visual consistency. Manual T2I generation available as workaround |
| F-13-2 | Lightweight Response Mode | ⏸ On hold | Not needed with current architecture |
| F-13-3 | Diffusers Offload Control | ⏸ On hold | Not needed with current architecture |
| F-19 | Export/Import | ⏸ On hold | Pending data structure stabilization |
| F-20 | TRPG Rulebook Injection | ⏸ On hold | TRPG expansion phase |
| F-21 | GM Agent | ⏸ On hold | TRPG expansion phase |
| F-22 | Dice Roll & History Branching | ⏸ On hold | TRPG expansion phase |
| F-24-1 | Episode Structured Output | ❌ Not implemented | narration/dialogue/tags/choices JSON Schema |
| F-24-3 | Branch Selection + Git Integration | ❌ Not implemented | choices → Git branch |

---

## Known Limitations

| Item | Description |
|---|---|
| Session history token limit | Long sessions may reach LLM context limit |
| Tab header pinning | Resolved by React migration |
| Irodori-TTS CUDA | venv may default to CPU after uv sync |
| Backend multi-start | PID file guard instability |

---

## Supported Backends

| Type | Count | Details |
|---|---|---|
| LLM | 5 | Text Generation WebUI / Ollama / OpenAI / Gemini / Anthropic |
| TTS | 4 | VOICEVOX / Kokoro / Irodori / Gemini TTS |
| T2I | 4 | A1111 / ComfyUI / Hugging Face / Civitai |

---

## Tests

| Type | Count | Result |
|---|---|---|
| Unit Tests | 186 | All passing |

---

This document reflects the status as of v2.0.0. For the latest status, see the repository's Issues and release notes.
