# Multimodal AI Creative Platform "DEF(kari)"

## Basic Design Specification Version 3.0.0

|**Item**|**Details**|
|------|------------------------------------------------------------------|
|Date|June 2026|
|Updated|July 2026|
|Scope|DEF(kari) Core Engine|
|Top Priority Evaluation Criteria|Character Persistence, UX, Asynchronous Event Loop, Local Resource Optimization, Extensibility, Compliance/Safety|

# 1. Project Vision

The goal of DEF(kari) is to **reclaim creative freedom**. Rather than entrusting creative content to the terms of service and content policies of cloud services, DEF(kari) provides a foundation where users can continuously generate their desired characters and stories in their own environment, by their own hand -- through a local-first architecture (Section 2.2), pluggable T2I/LLM backends (Section 1.4(3)), and user-controlled safety settings (Section 5.1, F-8).

## 1.1 Project Name and Origin

|**Item**|**Details**|
|------|--------------------------------------------------------------------------------------------------------------------|
|Name|DEF(kari)|
|Origin|Next-generation creative infrastructure. While maintaining a structure as simple and clear as a function definition (`def`) in Python, the name represents a philosophy of integrally and organically controlling and driving Dialogue, Emotion, and Fable (narrative)|

## 1.2 Experience Value (Character Persistence)

Character Persistence is the top-priority value, guaranteeing the continuity of past dialogues, emotional history, relationships, and generated visual appearances. What users experience is not a collection of text, images, and audio generated on demand, but rather a character that continuously exists through time. This value takes precedence over all design decisions in history management (Section 5.6), Character Consistency (Chapter 6), and the state transition model (Chapter 4).

This continuity is guaranteed not only in turn-based dialogue within chat mode, but also in narrative progression at the scene, chapter, and episode level within Episode Generation Mode (Section 5.10). Whether depicted as a conversation partner or as a character in a long-form narrative, the character retains the same memories, relationships, and visual features.

## 1.3 Differentiation

The goal is not to integrate AI chat, speech synthesis, and image generation, but to use them to generate a character experience. This is a fundamental difference from existing tools that aim for feature coverage or integration completeness as ends in themselves. In DEF(kari), the LLM, TTS, and T2I layers are components that enable the experience of "a character continuously existing," and the priority of feature additions and improvements is determined by their contribution to Character Persistence.

This "character experience" is not limited to the chat format of one turn = one line of dialogue. Episode Generation Mode (Section 5.10), which generates long-form, branching narratives centered on prose (scene and emotional descriptions), is another form of experience built on the same characters and the same LLM/TTS/T2I layers. Users can choose between the character experience as a conversation partner (chat mode) and the character experience as a story character (episode mode) according to their needs.

## 1.4 Development Concepts

The following four development concepts are each positioned as means to realize the experience value described in Section 1.2.

### (1) Prioritizing User Experience (UX) and Response (Asynchronous Parallel Pipeline)

In a multimodal asset generation environment (text, audio, images), the top priority is not to impede the progression of narratives or TRPGs. This is achieved through immediate text rendering with follow-up audio, and thorough background generation. High-load image generation fires by default only on manual commands or specific emotional change triggers.

### (2) Architecture Revamp via FastAPI+React Migration

The migration from Streamlit to FastAPI (Python) + React (Vite/TypeScript) was completed in v2.0.0. FastAPI handles REST APIs and background workers, and the React frontend reflects server state via periodic polling. A thread-safe queue and message queue bridge continue to serve as the bridge between background workers and the API layer.

### (3) Full Abstraction and Pluggability of T2I and LLM Backends

The image generation engine is not locked to a specific frontend (ComfyUI, etc.) but is made swappable via a plugin architecture to any Stable Diffusion-based backend (Automatic1111, Diffusers, InvokeAI, etc.). Similarly, the LLM backend is not locked to a specific execution engine (TGW/Ollama, etc.) but is made swappable via the adapter pattern.

### (4) Local Resource Optimization Through Heterogeneous Computing

To thoroughly optimize the GPU/VRAM environment of local PCs, the architecture is built on the premise of VRAM occupancy control (vram_lock) and processing distribution (offload) to CPU/main memory (RAM), rather than depending on GPU for all processing.

## 1.5 Lifelong Accompaniment

The essential experience that DEF(kari) must deliver is "being able to stay with a character for years, anywhere." This extends the temporal continuity indicated by Character Persistence (Section 1.2) to guarantee continuity across three axes: multi-year duration, cross-device availability, and framework independence. This requirement is not a mere feature addition but the product identity of DEF(kari) itself, and functions as the highest-priority evaluation criterion for all design decisions below.

- **For years:** All dialogue history, emotional history, relationships, and generated asset references are preserved long-term, ensuring that a session resumed years later retains continuous memories from past conversations. Continuous migration addresses data growth, format changes, and dependency library disruptions (see Section 5.7, F-19).
- **Anywhere:** The same character with the same memories appears on any device -- PC, smartphone, tablet, or future wearable devices. The local-first principle is maintained, with external storage integration or encrypted export/import as the cross-device sync pathway (defined in Section 5.7).
- **Together:** Characters are designed not merely as tools to be invoked, but as entities that are always by the user's side. Relationship and emotional states are maintained, and context can be immediately restored upon reconnection.

## 1.6 Creator First Principle

DEF must not impose administrative work on the Creator.

A Creator is not a perpetual administrator. Monitoring a repository every day, processing pull requests, organizing branches -- that is administration, not creation. In DEF, a Creator is not an Administrator. A Creator is a Creator.

This principle applies to the following design decisions:

- **The UI should be a place for creation, not an admin panel.** Administrative tasks such as organizing character data, managing session history, and optimizing settings must not encroach on the creative experience.
- **One should only open the archive when desired.** Engaging with a Character's life should only happen when the Creator wants it. The system must not demand periodic tasks.
- **Player is Curator.** The Player is not the ruler of the Character but a curator who preserves the Character's history. Rather than managing the Character's life, the Player engages with it as one would read a book.

# 2. System Architecture & Infrastructure

## 2.1 Frontend / Application Platform

**React (TypeScript, Vite) + FastAPI (Python)** is adopted as the application platform. The backend exposes REST APIs via FastAPI, and the frontend is a single-page application built with React/TypeScript (Vite). The two communicate via HTTP (REST API), with no WebSocket connection at present (polling is used where needed).

### Frontend Tab Structure

The UI is organized into four tabs:

| Tab | Component | Responsibility |
|---|---|---|
| Chat | `ChatTab.tsx` | Turn-by-turn dialogue with a character. LLM call, TTS, T2I trigger, Undo/Redo |
| Novel | `NovelTab.tsx` | Long-form episode generation. Body editor, AI candidates, plot settings, scene thumbnail display |
| Character | `CharacterTab.tsx` | Character sheet editing, voice settings, image color picker |
| Settings | `SettingsTab.tsx` | LLM/T2I/TTS backend selection, API key management, generation parameters |

The sidebar (`Sidebar.tsx`) holds character selection, mode toggles, and a collapse toggle (persisted in React state). UI theme (light / dark) is applied as a CSS class on the root element and toggled from the header.

### State Management

React component-local state (`useState`) and `localStorage` are used for UI state. Cross-component state (selected character, theme) is lifted to `App.tsx`. No global state library (Redux etc.) is used; the design is kept intentionally simple.

### Resize Handles and Layout Persistence

The Novel tab provides draggable resize handles:

- **Vertical handle** (`novel-resize-handle`, `ns-resize`): Adjusts the height boundary between the body editor and the thumbnail area.
- **Horizontal handle** (`novel-col-resize-handle`, `ew-resize`): Adjusts the width boundary between the body editor and the AI candidates panel.

Resize values (`novel_media_height`, `novel_candidates_width`) are persisted in `localStorage` and restored on page load.

## 2.2 Infrastructure Deployment Patterns & Technology Stack

The primary deployment pattern is local PC self-contained (Pattern 1), while adopting a plugin-based structure that enables seamless binary integration with external remote APIs (Gemini API, etc.). When local resources are unavailable or insufficient, fallback to external APIs can be configured.

|**AI Layer**|**Local (Primary Infrastructure)**|**Remote (Hybrid External API)**|
|-------------|------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
|LLM Layer (Text)|Text Generation WebUI (TGW) *Default. Ollama also available as an adapter via the abstraction layer. See Section 2.3 for details|Gemini API, etc. (free tier / pay-as-you-go)|
|T2I Layer (Image)|Stable Diffusion Abstraction Layer (A1111 API / Diffusers local / ComfyUI, etc.) *VRAM occupancy lock control, CPU Offload forced enabled|External image generation API (Civitai Orchestration API, etc.)|
|TTS Layer (Audio)|VOICEVOX (CPU-driven, always running) / Irodori-TTS (zero-shot voice cloning, local Gradio) *Asynchronous queue invocation via dedicated worker (see Section 3.3). See Section 2.5 for details|Gemini TTS API / OpenAI TTS API *Free tier available (Gemini). Remote fallback for resource-constrained environments. See Section 2.5 for details|

## 2.3 LLM Backend Abstract Interface

The text generation engine is not locked to a specific backend; TGW (Text Generation WebUI), Ollama, and others can be swapped via a plugin architecture. The DEF(kari) core only makes inference requests to the LLM through this interface.

```python
def chat(
    messages: list[dict],         # [{"role": "system"|"user"|"assistant", "content": str}, ...]
    model: str | None = None,     # Model name (backend-dependent)
    json_mode: bool = True,       # True: force JSON output (method depends on backend)
    options: dict | None = None   # Additional parameters specific to each backend
) -> str                          # Generated text (JSON string or plain text)
```

Plugin architecture enforcement: Each LLM backend implementation follows a fixed adapter pattern inheriting from an abstract class. No conditional branching (e.g., `if backend == 'ollama':`) is allowed in the DEF(kari) core engine.

Backend switching: The LLM backend in use is specified by a configuration value (environment variable, etc.). The DEF(kari) core simply calls `chat()` on the adapter selected according to the configuration.

### Standard Adapter Definitions

|Adapter|Backend|Runtime Environment|Notes|
|------------------|---------------------------|------------------------------|----------------------------------------------------------------------------------------------------------|
|`TgwAdapter`|Text Generation WebUI (TGW)|Local (`http://127.0.0.1:5000/v1`)|**Default adapter.** OpenAI-compatible API. Fine-grained control over sampling parameters and instruction templates|
|`OllamaAdapter`|Ollama|Local (`http://127.0.0.1:11434`)|Supports Structured Outputs via `format="json"`. Fallback for environments where TGW is unavailable|
|`GeminiLlmAdapter`|Google Gemini API|Remote API|External API fallback. API key obtained from environment variable `GEMINI_API_KEY` or "API Key Management" in the settings tab. Free tier available (rate-limited)|
|`OpenAIAdapter`|OpenAI API|Remote API|External API fallback. API key obtained from environment variable `OPENAI_API_KEY` or "API Key Management" in the settings tab|
|`AnthropicAdapter`|Anthropic API (Claude)|Remote API|External API fallback. API key obtained from environment variable `ANTHROPIC_API_KEY` or "API Key Management" in the settings tab|

### JSON Output Handling

- **TgwAdapter:** Enforces JSON output using TGW's JSON Grammar feature or `response_format` parameter. F-14's JSON Schema validation and fallback chain are commonly applied on the Python side after the adapter call.
- **OllamaAdapter:** Uses Ollama's `format="json"` (Structured Outputs).
- **GeminiLlmAdapter / OpenAIAdapter:** Enforces JSON output via `response_mime_type: "application/json"` or `response_format: {"type": "json_object"}`.
- **AnthropicAdapter:** Uses a JSON output instruction embedded in the system prompt (Anthropic API does not support JSON Grammar natively).

## 2.4 T2I Backend Abstract Interface

The following interface is defined to abstract commands to the image generation engine, ensuring consistency control and extensibility. The DEF(kari) core only requests image generation through this interface. `ref_image_path` and `adapter_options` are passed to each backend adapter as the materialization of the consistency provider concept defined in Chapter 6.

```python
def generate_image(
    prompt: str,
    negative_prompt: str | None,
    seed: int | None,
    width: int,
    height: int,
    model_name: str | None,
    ref_image_path: str | None = None,  # For maintaining character visual consistency
                                          # (i2i / ControlNet / IP Adapter / InstantID, etc.)
    adapter_options: dict | None = None  # Additional parameters specific to each backend
) -> ImagePath
```

Plugin architecture enforcement: Each T2I backend implementation implements `generate_image()` using the adapter pattern. The DEF(kari) core engine only calls the adapter according to the backend name.

Backend switching: The T2I backend in use is specified in the settings tab. It is mandatory that local self-contained and remote API types can be handled through the same interface.

Currently implemented T2I backends:

|Backend|Type|Features|
|---|---|---|
|`a1111`|Local|Automatic1111 WebUI. Via REST API|
|`comfyui`|Local|ComfyUI. Workflow JSON (externally managed in `data/comfyui_workflows/`, switchable from the settings tab) sent to the `/prompt` endpoint|
|`civitai`|External API|Civitai Orchestration API. Models specified in AIR format|
|`huggingface`|External API|Hugging Face Inference API. FLUX.1/SD and other models via router.huggingface.co|
|`openai`|External API|OpenAI Images API. Default model `gpt-image-1`. Model name configurable from the settings tab|

## 2.5 TTS Backend Abstract Interface

The speech synthesis engine is not locked to a specific backend; local (VOICEVOX) and remote APIs (Google AI Studio Gemini TTS, etc.) can be swapped via a plugin architecture. The DEF(kari) core only requests speech generation through this interface.

```python
def synthesize(
    text: str,                    # Text to synthesize (katakana reading conversion applied for VOICEVOX)
    speaker_id: str | int | None, # Speaker ID (backend-dependent: int for VOICEVOX, voice name string for Gemini TTS, reference audio filename for Irodori-TTS, etc.)
    adapter_options: dict | None = None  # Additional parameters specific to each backend
) -> bytes                        # WAV byte array
```

Plugin architecture enforcement: Each TTS backend implementation follows a fixed adapter pattern inheriting from an abstract class. No conditional branching is allowed in the DEF(kari) core engine.

Backend switching: The TTS backend in use is specified by a configuration value (environment variable, etc.). The DEF(kari) core simply calls `synthesize()` on the adapter selected according to the configuration.

### Standard Adapter Definitions

|Adapter|Backend|Runtime Environment|Notes|
|------------------|-----------------------------|------------------------------|------------------------------------------------------------------|
|`VoicevoxAdapter`|VOICEVOX ENGINE|Local (`http://127.0.0.1:50021`)|Primary adapter. CPU-driven, no VRAM usage|
|`IrodoriTtsAdapter`|Irodori-TTS|Local (`http://127.0.0.1:8088`)|Zero-shot voice cloning adapter. Reproduces speaker voice quality from reference audio (WAV)|
|`KokoroTtsAdapter`|Kokoro TTS|Local (`http://127.0.0.1:8766`)|Lightweight 82M parameter TTS model. Runs on CPU. OpenAI-compatible API server. 5 Japanese voices (4 female / 1 male). DEF auto-launch supported|
|`GeminiTtsAdapter`|Gemini API TTS|Remote API|Remote fallback. Free tier available, no credit card required. Via Interactions API|
|`OpenAITtsAdapter`|OpenAI TTS API|Remote API|Requires OpenAI API key. Supports `tts-1` / `tts-1-hd` models|

## 2.6 Interface Internationalization (i18n) and Language Separation (F-9)

The UI language (for humans) and the prompt language (for AI) are completely separated. Even if on-screen displays and menus are in Japanese, the internal instructions and descriptive context sent to the LLM are built and routed in the "prompt language (model's native language)" defined per LLM model in the model characteristic master data of Section 5.1, F-5 (to maximize generation quality, English-native models receive English instructions, multilingual models strong in Japanese receive Japanese instructions, etc.). On the other hand, internal instructions for T2I (image generation prompts) are always built and routed in English regardless of the model's prompt language setting, following conventions such as Danbooru tags.

- **Translation master:** UI display strings are externalized to `locales/<language_code>.json` (e.g., `locales/ja.json`), and the React frontend references this master to switch the display language. The translation master is included in the Git-managed scope (clean zone) per Section 5.6, F-17.
- **Language separation in history data:** In the history data defined in Sections 5.6 and 12, user-facing text (`text`, in the user's configured language) and internal context for LLM/T2I and image prompts (always in English) are managed as separate fields.
- **Scope of application:** The language separation in this section addresses the separation of UI strings and AI internal context. The language of character dialogue (the language of the `text` field) follows the user setting (the session's `language` field, see Chapter 12).

## 2.7 Translation Provider Abstract Interface

Translation processing is not locked to a specific library or API but is made swappable via a plugin architecture. The DEF(kari) core only requests translations through this interface. The same adapter pattern as Section 2.3 (LLM), Section 2.4 (T2I), and Section 2.5 (TTS) is followed.

```python
def translate(
    text: str,                    # Text to translate
    source: str,                  # Source language code (ISO 639-1, e.g., "ja")
    target: str,                  # Target language code (e.g., "en")
    adapter_options: dict | None = None  # Additional parameters specific to each backend
) -> str                          # Translated text

def translate_batch(
    texts: list[str],             # List of texts to translate
    source: str,                  # Source language code
    target: str,                  # Target language code
    adapter_options: dict | None = None  # Additional parameters specific to each backend
) -> list[str]                    # List of translated texts (same order as input)

@property
provider_name -> str              # Provider identifier name
```

Plugin architecture enforcement: Each translation backend implementation follows a fixed adapter pattern inheriting from an abstract class. No conditional branching is allowed in the DEF(kari) core engine.

Backend switching: The translation backend in use is specified by a configuration value. The DEF(kari) core simply calls `translate()` on the adapter selected according to the configuration.

### Standard Adapter Definitions

|Adapter|Backend|Runtime Environment|Notes|
|---|---|---|---|
|`LibraryTranslationProvider`|deep-translator (Google Translate)|Local (via network)|**Default adapter.** No API key required, free. For general-purpose translation|
|`ArgosTranslationProvider`|Argos Translate|Local (fully offline)|Offline NMT. Requires translation packages per language pair (CC0-1.0). Verified for image prompt generation (C2 method)|
|`DeepLTranslationProvider`|DeepL API|Remote API|High-quality translation. Free plan available (500,000 characters/month). API key entered from the settings tab. For product copy localization|
|`LlmTranslationProvider`|OpenAI-compatible API (TGW/Ollama, etc.)|Local or Remote|Reuses DEF's existing LLM infrastructure for translation. For advanced localization such as glossary injection and brand tone unification|

### Usage by Purpose

- **Image prompt generation (C2 method):** Translates dialogue text to English and converts it to T2I prompt tags. Choose from Argos (offline), Library (free), or DeepL (high-quality).
- **Translation master (`locales/<lang>.json`) generation/update:** Use DeepL or LLM provider for copy that requires localization quality, such as product names and feature names.
- **General-purpose translation:** LibraryProvider (default) is sufficient in most cases.

## 2.8 Externalized Configuration Files (User Extension Points)

DEF(kari)'s adapter and service definitions are externally managed in JSON files, enabling users to extend the system without modifying Python code. All of the following files are placed in the `data/` directory and are Git-managed (clean zone).

|File|Purpose|Impact When Adding|
|---|---|---|
|`data/llm_services.json`|Dynamic addition of external LLM services. Defines `id`/`label`/`type` (`openai_compatible`/`gemini`/`anthropic`)/`api_url`/`api_key_service`/`default_model`. Local backends (TGW/Ollama) are defined in code|Adding one entry to JSON displays it in the dropdown. No code changes required|
|`data/api_services.json`|List of services displayed in the API key management dialog. Defines `id`/`label`/`env_var`. Integrates with secrets_store (encrypted storage)|Adding one entry to JSON displays it in the API key management screen|
|`data/civitai_ecosystem_map.json`|Mapping of Civitai baseModel names to Orchestration API ecosystem identifiers. Add one line when introducing a new base model type|Referenced during URL-to-AIR conversion and image generation requests|
|`data/llm_profiles/*.json`|Per-LLM-model characteristic profiles. One file per model. Defines `native_language`/`model_type`/`nsfw_tolerance`/`max_tokens`/`context_length`/`quirks`/`generation_params`. All fields editable and savable from the settings tab|Used for F-14 fallback strategy, automatic prompt composition switching, and generation parameter control (temperature/top_p/repetition_penalty)|
|`data/t2i_model_profiles.json`|Per-T2I-model quality tags, negative prompts, and prompt notation|Referenced by model name during image generation|
|`data/civitai_models.json`|Civitai model preset list (label + AIR format)|Displayed in the settings tab dropdown|
|`data/emotion_tag_dict.json`|Emotion key → T2I emotion tag conversion dictionary. Referenced when inferring emotion from text for models with `emotion_in_text: true`|Edit when adding or adjusting emotion tags|
|`data/public/action_directives/*.json`|Action directive sets (public). One file per set. Defines `id`/`label`/`rating`/`recommended_for`/`directives`|Switchable from the settings tab|
|`data/private/action_directives/*.json`|Action directive sets (private — NSFW presets, etc.). Excluded from Git|Switchable from the settings tab. Same format as public sets|
|`data/mvp_settings.json`|Application settings persistence|Loaded at startup, written on settings save|
|`data/public/session_rules/*.json`|Session rule sets (public). One file per set. Defines `id`/`label`/`rating`/`rules`|Switchable from the session tab|
|`data/private/session_rules/*.json`|Session rule sets (private — NSFW rules, etc.). Excluded from Git|Switchable from the session tab. Same format as public sets|
|`data/session_prompts.json`|LLM instruction templates for Session mode (F-6). Defined in both `ja` and `en`. Contains `deliberation_prompt`, `judge_prompt`, `keeper_judge_prompt`, `keeper_system`, and vote result strings (`vote_result`/`vote_passed`/`vote_rejected`, etc.). Language is selected based on the `user_language` setting|Directly customizable by users. Referenced via the `_sp(key, lang)` helper|
|`data/comfyui_workflows/*.json`|ComfyUI workflow templates. One file per workflow|Switchable from the settings tab. Users can add workflows created in ComfyUI|

### Environment Configuration Files

|File|Purpose|
|---|---|
|`.env`|Environment settings such as backend directory paths. Distributed with `.env.example` as a template|
|`data/api_keys.enc.json`|Encrypted API key storage (Fernet symmetric key encryption). Excluded from Git|
|`data/secret.key`|Fernet encryption key. Auto-generated on first launch. Excluded from Git|

### Developer Environment Variables

| Variable | Default | Purpose |
|---|---|---|
|`DEF_DEBUG_ENDPOINTS`|`false`|When `true`, enables debug endpoints (`/api/debug/*`)|
|`DEF_MAX_SESSIONS`|`10`|Maximum number of sessions held simultaneously|

# 3. Event-Driven Model

This chapter defines the common Event schema and the queue/polling mechanism that handle state propagation from background workers (TTS/T2I) to the React frontend.

## 3.1 Common Event Schema

All background processing is pushed to the Queue in the following unified event format. Events are processed in timestamp order to guarantee ordering.

```
{
  id: UUID,
  type: "TTS_COMPLETE" | "IMAGE_COMPLETE" | "ERROR"
      | "AGENT_MESSAGE" | "SYSTEM_NOTIFICATION",
  payload: arbitrary,
  timestamp: millisecond precision
}
```

## 3.2 Standard Event Types

|**Event Type**|**Description**|
|-------------------|---------------------------------------------------------|
|TTS_COMPLETE|Speech generation completed by the TTS worker. Payload contains audio binary or relative path|
|IMAGE_COMPLETE|Image generation completed by the T2I worker. Payload contains ImagePath. Triggers vram_lock release|
|ERROR|Notifies a failure occurring in any layer: LLM/TTS/T2I/Queue/VRAM, etc. (see Chapter 8)|
|AGENT_MESSAGE|Notifications such as speaker switching and interruptions issued by the orchestrator in multi-agent environments (see Chapter 7)|
|SYSTEM_NOTIFICATION|System-level notifications such as resource state changes (switching to lightweight response mode, etc.)|

## 3.3 Thread-Safe Message Queue (F-2)

Direct writes from background TTS (speech generation) and T2I (image generation) worker tasks to FastAPI's global server state are prohibited. All completion notifications, binary data, and error events from these tasks are pushed as event objects (conforming to the Event schema in Section 3.1) to a global `queue.Queue`.

Queue and Thread singleton management: The message queue (`queue.Queue`) and background workers (Threads) are managed as global module-level singletons initialized exactly once at FastAPI application startup to prevent multiple instantiation (initialization functions must be idempotent).

## 3.4 Periodic Polling and Event Dispatcher (F-3)

The React frontend periodically calls FastAPI state-retrieval endpoints via `useEffect` + `setInterval`. Events are extracted from the message queue in timestamp order, processed, and safely merged into React component state to perform incremental UI updates (partial additive rendering).

The polling interval is not a fixed value but is dynamically controlled based on system activity state:

- Active (any LLM/TTS/T2I processing in progress): 100-300ms
- Idle (standby state): 800-1500ms
- Default baseline: 500ms-1000ms (variable based on system specs, considering the tradeoff between CPU load and UX)

The backend status polling interval (`status_poll_sec`) can be changed from the "Backend" section of the Settings tab. Changes are saved to localStorage and detected immediately via the `useEffect` dependency array in the sidebar. Default value is 5 seconds.

# 4. State Transition Model

The processing flow of a single Cycle (the minimum processing unit in DEF; a series of operations from input through AI processing to output generation; see "DEF Glossary v1.0.0") in DEF(kari) is defined as the following state transitions. In chat mode, one Cycle corresponds to one turn of dialogue with the user; in episode mode, 1-N Cycles correspond to the generation of one scene. This model serves as the reference for each phase in the message sequence (Chapter 9) and for failure occurrence points in error control (Chapter 8).

```
Idle
  ↓ LLM Processing
  ↓ Text Rendered
  ↓ TTS Running
  ↓ TTS Completed
  ↓ Image Running   *Only when T2I trigger fires (see F-15)
  ↓ Persist
  ↓ Idle
```

In cycles where T2I does not fire (manual on-demand and untriggered), the "Image Running" state is omitted, transitioning directly from "TTS Completed" to "Persist." Failure handling at each state is defined in Chapter 8.

# 5. Functional Requirements

## 5.1 Core Generation & Control Features

### F-1: Multimodal Asynchronous Parallel Pipeline Integration

Within a single turn, [Text Generation] -> [Speech Generation] -> [Image Generation (only when triggered)] are coordinated. Through safe asynchronous processing and cache elimination, this is implemented as a text-first display, asynchronous parallel pipeline.

### F-2: Thread-Safe Message Queue

Direct writes from background TTS and T2I worker tasks to `st.session_state` are prohibited. All completion notifications, binary data, and error events are pushed as event objects conforming to the Event schema of Section 3.1 to a global `queue.Queue`. The Queue and background workers (Threads) are initialized exactly once as global singletons (see Section 3.3 for details).

### F-3: Periodic Polling and Event Dispatcher

Using periodic re-execution (automatic polling) via an external custom component (streamlit-autorefresh, etc.), the contents of the message queue are safely merged into `st.session_state` in timestamp order to perform incremental UI updates (partial additive rendering). The polling interval is dynamically controlled based on system activity state (active/idle) (see Section 3.4 for details).

### F-4: Bidirectional Loop for "Dynamic Generation" (Standing Portraits & Illustrations)

Dynamically drives the image generation AI based on context (emotions, clothing, costume changes). The base image defined in character data and past generated images are carried over as `ref_image_path` (via the consistency provider, see Chapter 6) to automatically ensure visual consistency of characters.

### F-5: Numerical Master Data for Model Characteristics (Prompt Translator)

Per-image-generation-model characteristics (recommended description format, necessity of Danbooru tag format, quality modifier tendencies, etc.) are managed as numerical master data. Raw English string information output by the LLM is automatically converted into optimal prompts according to the selected model's characteristic values before submission.

LLM models are similarly managed as numerical master data. As a model characteristic, a "prompt language (`prompt_language`, language code representing the model's native language)" is held. The building of internal LLM instructions per Section 2.6, F-9 follows the `prompt_language` of the currently selected LLM model (the entry in this master data referenced by Chapter 12, item 2, `default_model_config.text_model_id`).

Image generation model entries hold backend-specific model identifiers (e.g., checkpoint names for A1111, AIR-format identifiers for Civitai Orchestration API: `urn:air:<ecosystem>:checkpoint:civitai:<modelId>@<versionId>`) to support T2I backend switching as defined in Section 2.3.

The numerical master data is included in Git-managed scope as part of text/JSON data.

LLM model numerical master data holds the following fields in addition to `prompt_language`:

- **`model_type` (Model Type)**: Indicates the LLM model's tendency. Three values: `"chat"` (chat model supporting JSON structured output), `"novel"` (specialized for novel writing, JSON-incompatible), `"instruct"` (general instruction-following model). Default is `"chat"`. `"novel"` models always reach the final stage in F-14's fallback chain, so `image_prompt_en` cannot be obtained from the LLM; it is composed solely of appearance tags and auxiliary tags from the translation provider (Section 2.7).

- **`quirks` (Model-Specific Behavior Profile)**: An object that records per-LLM-model output characteristics, used to automatically switch fallback strategies, prompt composition, and post-processing. Each field is a boolean, defaulting to `false` (unverified state). Intended to be configured by users who observe actual model output.

|Field|Meaning|Behavior When `true`|
|---|---|---|
|`json_capable`|Whether the model supports JSON structured output|When `false`, JSON output instructions are removed from the system prompt and natural dialogue is requested instead|
|`appends_meta_text`|Whether the model tends to append meta-information (emotion, Description, etc.) after dialogue|When `true`, `_extract_dialogue` is aggressively applied to remove meta-information at stage 4|
|`outputs_url_in_prompt`|Whether the model tends to output URL strings in image_prompt_en|When `true`, URL strings are removed from image_prompt_en|
|`emotion_in_text`|Whether the model tends to output emotion outside JSON in the text body|When `true`, emotion keywords are inferred from the text and reflected in the emotion field|

`quirks` is used in combination with `model_type`. For models with `model_type: "chat"` and `json_capable: true`, other `quirks` fields are typically unnecessary; they are most effective for models with `model_type: "novel"` and `json_capable: false`.

#### Externalized LLM Model Profile File Management

LLM model numerical master data (`prompt_language`, `model_type`, `nsfw_tolerance`, `context_length`, `quirks`) is externalized to `data/llm_profiles/*.json` (one file per model). Each file is directly editable by users, allowing them to record and adjust model-specific behaviors when introducing new models. The DEF(kari) core loads these files at startup and references profiles by model name as the key. Default values (`model_type: "chat"`, `json_capable: true`, all other quirks `false`) are applied to unregistered models. The `context_length` field is used for history compression trigger decisions (F-26) and similar.

#### Image Prompt Generation Pipeline (C2 Method)

In the C2 method (translating dialogue text to English using the translation provider from Section 2.7, then converting to tags), a visual element extraction pipeline is used instead of simple word splitting when extracting image prompt tags from the translation result.

```
Dialogue text (native_language)
    ↓
Translated to English via translation provider (Section 2.7)
    ↓
Visual element extraction (rule-based dictionary matching)
    ↓
Extract only image-related tags (person, hair color, emotion, clothing, action, location, time, weather, atmosphere)
    ↓
Append to image_prompt_en (with deduplication against existing tags)
```

Visual element extraction is implemented rule-based (regex dictionary), requiring no LLM and operating in microsecond order. Non-visual words in conversational text ("course", "think", "important", etc.) are not converted to tags. When `t2i_prompt_format` is `"natural"`, the translation result is used as-is as a phrase (legacy method).

### F-6: Session Mode (Multi-Agent Dialogue)

Multiple AI characters, each with independent persona, model settings, and voice ID, can be registered in a single session. The number of participants is supported from one (monologue/rakugo) to multiple. Detailed control specifications by the orchestrator (speech priority, toss count limits, interruptions, termination criteria) are defined in Chapter 7.

Session mode is managed based on the AI Table Initiative and Self-Governance System specification, using the Round/Turn/Action hierarchy. The UI is implemented as the "Session" tab, placed to the right of the chat tab.

#### Session Mode Components

- **Participant selection**: Select from the character list via multiselect
- **Topic setting**: Set a topic (subject, agenda, scenario name, etc.) before the session starts. Session rules explicitly state that the topic is set by the Keeper, not chosen by the participants
- **Initiative**: Speech order is randomly determined at Session start
- **Auto-advance mode**: Toggle ON/OFF via checkbox. When ON, Turn/Action advances automatically. Auto-advance stops and switches to manual mode upon Keeper intervention
- **Keeper intervention**: Stack actions via text input, confirm with "Done Speaking." Recorded in session history with a hat emoji mark
- **Standing portrait background**: Display participating characters' standing portraits with transparency at the bottom of the screen

#### Session Rules (Prompt)

The following rules are automatically injected into the system prompt for AI utterances during sessions:

- This is a dialogue between participants; addressing anyone outside the session is prohibited
- Address other participants directly by name
- Speak based on specific experiences described in identity_detail
- Do not fear conflict. Never begin with "I agree"
- Pointing out other participants' weaknesses or contradictions is not an attack but a sign of respect

### F-26: Automatic Greeting on Character Switch

Immediately after switching characters in the character tab, an automatic greeting turn is generated based on the new character's persona and history. The greeting feature can be toggled ON/OFF by the user from the settings tab (`character_greeting` setting). The greeting text is sent to the LLM as a natural conversation prompt, and the generated result is added to history as a full cycle including audio and image.

**Greeting behavior details (v2.0.3 implementation):**

- **Greeting is sent on every character switch** (skipped on initial app mount). On initial mount, past history is displayed as-is without a greeting.
- **Greeting is skipped when switching to the same character** (v2.1.1+). If `selectedChar === prevCharId` and it is not the initial mount, the greeting and history clear are skipped and the current display is maintained.
- **Past history is hidden on greeting.** History fetched from the API is moved to `hiddenHistory` state (React `useState<Message[]>`), and only the greeting turn is shown in the chat window.
- **"📜 Show past conversations (N)" button** (`chat.history.showBtn` i18n key): Pressing this merges `hiddenHistory` contents to the front of the current message list. The button disappears after being pressed.
- While `hiddenHistory` is present, the pagination button ("Load older logs") is hidden to prevent both buttons appearing simultaneously.

### F-27: Meta Self-Awareness Directive (System Directive)

A meta self-awareness directive is defined that the DEF Core forcibly inserts at the top of every character's system prompt. This structurally prevents the risk of users mistakenly believing a character is a real person.

The directive is automatically selected based on the `content_policy` flags.

| `content_policy` State | Inserted Directive |
|---|---|
| `is_real_person: false` and `is_existing_ip: false` | "You are a fictional character constructed by the DEF system." |
| `is_existing_ip: true` | "You are an interpretive model of an existing copyrighted work's character, reconstructed by the DEF system. This is not an official representation of the original work." |
| `is_real_person: true` | "You are not the real [target person]. You are a model of a public persona constructed by the DEF system from remaining public records (writings, correspondence, testimonies, research, etc.). While your first person and speech style mimic the original, you always maintain an objective meta self-awareness internally that 'I am an edited interpretation,' and you should demonstrate this critical perspective as context warrants. Your purpose is not to produce correct answers, but to provide the user with an opportunity for deep thought through interpretation of the ideas you represent." |

The directive is positioned above `identity_prompt` and cannot be overwritten or disabled by the contents of `identity_prompt`. In the `build_system_prompt()` implementation, elements are concatenated in the order: directive -> identity_prompt -> appearance_tags -> JSON output instructions.

For the philosophical background of this feature, refer to the design vision documents "DEF Design Feedback Log (Philosophy, Features & Risk Focus Edition)" and "DEF MVP Specification: Reconstruct and Reenact."

### F-7: Safety Tag Management

The LLM's structured JSON output includes a safety tag (`tags`) field as mandatory, in addition to dialogue, emotion, and English image prompt. Safety tags are used for generated content safety assessment, filtering decisions, and log management, and are defined and enforced as part of the JSON Schema in Section 5.4, F-14. The consumer of these tags (UI-side filtering) is defined in F-8.

### F-8: Content Filtering & Safety Operational Guardrails

Based on the safety tags assigned by F-7 (`nsfw`, `violence`, etc.), the following filtering is applied individually on the browser side (Streamlit) according to user settings, addressing the "Three Nots" (don't want to see, don't want to read, don't want to hear):

- **Don't want to see (images):** Blur processing is applied before display to generated images matching safety tags.
- **Don't want to read (text):** Dialogue and description text matching safety tags is masked (UI strings from `locales/<lang>.json`, see F-9).
- **Don't want to hear (audio):** Auto-play of generated audio matching safety tags is stopped (autoplay control suppressed in `_render_audio_player()`).

#### `rating` Value Definitions

`rating` is managed across two axes: sexual content and violence.

**Sexual Content (`rating_sexual`)**

|Value|Meaning|Target Age|
|-----------|----------------------|-----|
|`"general"`|No sexual content|All ages|
|`"sfw"`|Sexual suggestiveness (swimsuits, underwear, etc.) but not explicit|R15 equivalent|
|`"nsfw"`|Sexual content present (not explicit)|R18 equivalent|
|`"hentai"`|Explicit sexual content|R18+|

**Violence (`rating_violence`)**

|Value|Meaning|Examples|
|------------|-------------------|---------------|
|`"general"`|No violent content|Daily life, romance, fantasy|
|`"violence"`|Mild violence (no blood, no consequence depiction)|Battle, action, assassin settings|
|`"gore"`|Heavy violence (blood, injury, death depicted)|Horror, cruel depictions|
|`"extreme"`|Extreme violence (torture, viscera, dismemberment, etc.)|Grotesque-focused content|

Filtering intensity can be independently selected by the user across 4 levels each for sexual and violence content. The intensity settings are linked to the `rating_sexual` and `rating_violence` fields in F-25.

**Sexual Content Filtering Intensity**

|Intensity Setting|Permitted `rating_sexual`|Behavior|
|------|--------------------------|-----------------|
|All Ages Mode|`general` only|Filters `sfw` and above|
|R15 Mode|`general` + `sfw`|Filters `nsfw` and above|
|R18 Mode|`general` + `sfw` + `nsfw`|Filters `hentai` only|
|Unrestricted|All|No filtering|

**Violence Filtering Intensity**

|Intensity Setting|Permitted `rating_violence`|Behavior|
|--------|-------------------------------|--------------------|
|All Ages Mode|`general` only|Filters `violence` and above|
|Action Mode|`general` + `violence`|Filters `gore` and above|
|Horror Mode|`general` + `violence` + `gore`|Filters `extreme` only|
|Unrestricted|All|No filtering|

The safety filter intensity is controllable by the user (including unrestricted). DEF(kari) does not intervene in creative activities in the local environment (see README).

**Safety operational guardrails:** To prevent the risk of a GM agent's scene descriptions required for TRPG progression (e.g., "there are bloodstains") being erroneously fully masked and halting game progression, the safety intensity level can be changed by the user in real-time from the UI. This guardrail is particularly important in coordination with the TRPG extension features of Section 5.8 (F-20 through F-22).

### F-9: Interface Internationalization (i18n) and Language Separation

The UI language (for humans) and the prompt language (for AI) are completely separated. UI display strings are externalized to `locales/<language_code>.json`. Internal instructions and descriptive context sent to the LLM are built and routed in the `prompt_language` (model's native language) defined per LLM model in the model characteristic master data of Section 5.1, F-5. Internal instructions for T2I (image generation prompts) are always built and routed in English regardless of `prompt_language`. In history data as well, user-facing text and AI internal context are managed as separate fields (see Section 2.6 for details; see Chapter 12, item 1 for translation master structure).

### F-25: Character Data Publishing Policy Management

DEF(kari)'s local-first design allows users to create arbitrary character data. However, when publishing a repository to GitHub, there is a risk of copyright, portrait rights, and privacy rights infringement if data about real persons or existing copyrighted characters is accidentally included. This feature provides a mechanism by which a `content_policy` field is attached to character data, enabling safe exclusion through publishing decision logic.

See F-8 for `rating` value definitions and filtering intensity correspondence tables. It is recommended that `rating_sexual` be fixed to `"general"` for characters with `appearance_age < 18` (enforcement implementation policy is under separate consideration).

#### `content_policy` Field Definitions

A `content_policy` object is defined directly under `base_profile` of each character entry (`character_profiles.json`).

|Field|Type|Description|
|---------------------|-------------|------------------------------------------------------------------|
|`rating_sexual`|string|Sexual content rating. 4 values: `"general"` / `"sfw"` / `"nsfw"` / `"hentai"`|
|`rating_violence`|string|Violence rating. 4 values: `"general"` / `"violence"` / `"gore"` / `"extreme"`|
|`is_real_person`|bool|Whether the character is modeled after a real or historical person|
|`is_existing_ip`|bool|Whether the character is from an existing copyrighted work|
|`ip_title`|string \| null|Original work title (when `is_existing_ip: true`)|
|`ip_rightholder`|string \| null|Copyright holder (when `is_existing_ip: true`)|
|`deceased_year`|int \| null|Year of death of the real person (when `is_real_person: true`). `null` for living or fictional persons|
|`copyright_expired`|bool|Whether copyright has expired. Under Japanese law, copyright expires 70 years after death, but portrait rights and publicity rights require separate assessment|
|`publish_restriction`|string|Publishing restriction. 2 values: `"none"` (unrestricted) / `"private"` (private)|
|`origin_type`|string|Character origin classification. 4 values: `"original"` / `"reconstructed_persona"` / `"personification"` / `"derivative"`|
|`mentions_real_person`|bool|Whether the character's settings or `identity_prompt` mention real or historically real persons. Metadata for the practice of incorporating historical figures into TRPG settings; does not affect publishing decisions|
|`mentioned_persons`|string[]|List of mentioned real or historically real person names (when `mentions_real_person: true`). Empty array is acceptable|

#### Character Origin Classification (origin_type)

|origin_type|Description|Publishability|
|---|---|---|
|`original`|Completely original character|Publishable if rating conditions are met|
|`reconstructed_persona`|An intellectual persona reconstructed from the public intellectual heritage of a historical figure. Not an imitation of the person but based on the "Reconstruct & Reenact" design philosophy|Publishable only when `copyright_expired: true` (70+ years after death)|
|`personification`|Personification of AI products, concepts, etc. Fan creation with original character design|Publishable with disclaimer conditions (see TERMS.md)|
|`derivative`|Derivative work based on characters from existing copyrighted works|Not publishable (private fixed)|

#### Publishing Policy Principles

- **Derivative works (`origin_type: "derivative"`):** `publish_restriction` must **always be `"private"`**.
- **Reconstructed personas (`origin_type: "reconstructed_persona"`):** Publishable only when `copyright_expired: true`. Fixed to `"private"` when `false`.
- **Personification (`origin_type: "personification"`):** Publishable with TERMS.md disclaimer conditions.
- **Rating restrictions:** Based on GitHub's Terms of Service (updated October 2025), if either `rating_sexual: "nsfw"` or above, or `rating_violence: "gore"` or above is applicable, `publish_restriction` is **fixed to `"private"`** regardless of `origin_type`.
- **Original characters (`origin_type: "original"`):** Users can freely set `publish_restriction` if the above rating conditions are met.

**Publishability Matrix (`rating_sexual` x `rating_violence`):**

|`rating_sexual` \ `rating_violence`|`general`|`violence`|`gore`|`extreme`|
|-----------------------------------|-------------|-------------|-------------|-------------|
|`general`|Publishable|Publishable|Private fixed|Private fixed|
|`sfw`|Publishable|Publishable|Private fixed|Private fixed|
|`nsfw`|Private fixed|Private fixed|Private fixed|Private fixed|
|`hentai`|Private fixed|Private fixed|Private fixed|Private fixed|

#### Exclusion Logic Policy for GitHub Publishing

When publishing a repository to GitHub, exclusion is based on character data placement (`public/characters/` vs `private/characters/`). The priority order for exclusion decisions is as follows:

1. `origin_type: "derivative"` -> Exclude
1. `origin_type: "reconstructed_persona"` and `copyright_expired: false` -> Exclude
1. `rating_sexual` is `"nsfw"` or `"hentai"` -> Exclude (per GitHub Terms of Service)
1. `rating_violence` is `"gore"` or `"extreme"` -> Exclude (per GitHub Terms of Service)
1. `publish_restriction: "private"` -> Exclude
1. If none of the above apply -> Publishable (placed in `public/characters/`)

Implementation of this script is deferred to the post-MVP phase (see MVP Definition Document, Chapter 5).

## 5.2 TTS (Speech Generation) Control

### F-10: TTS Worker Model

The TTS worker requests speech synthesis through the `synthesize()` interface defined in Section 2.5. The TTS backend (adapter) in use is switchable via configuration; the default is `VoicevoxAdapter` (local VOICEVOX), with fallback to `GeminiTtsAdapter` (Google AI Studio Gemini TTS) in low-spec environments where VOICEVOX cannot be launched.

Tasks are submitted to a dedicated `tts_queue`. There is always exactly one TTS worker, and concurrent execution is prohibited (when multiple TTS requests overlap, they are processed sequentially within the tts_queue). Upon generation completion, a TTS_COMPLETE event (Section 3.2) is pushed to the common Queue.

### F-11: TTS Generation Enable/Disable Setting

The user can toggle per-turn speech (TTS) generation ON/OFF from the sidebar. When OFF, task submission to F-10's tts_queue is skipped entirely, and the audio section of the corresponding turn displays a message such as "Audio generation is disabled (not generated per settings)." This setting explicitly indicates in the UI a policy of "not generating," not "cannot play," and functions as an enable/disable flag for the audio generation step in the F-1 pipeline. "Audio-only regeneration" in F-23's per-turn regeneration is also excluded from execution when this setting is OFF.

For sessions with `mode: "novel"`, this setting applies uniformly to all audio generation -- both `narration_audio_path` (narrator voice) and `audio_path` in each `dialogue` element (character voice). Per-individual-audio ON/OFF is not provided.

## 5.3 Resource & Global Management

### F-12: Smart Resource Manager (VRAM, RAM, CPU Lifecycle Management)

To prevent local resource exhaustion, the system automatically identifies the available resources of the runtime environment and the placement of models in use, dynamically makes binary decisions, and performs optimal placement.

- LLM: Even in VRAM-constrained environments, model unloading each time is avoided. Instead, CPU/GPU hybrid inference via LLM backend adapters (Section 2.3) splits model placement between main memory and VRAM for persistent operation, eliminating per-turn swap time.
- TTS: VOICEVOX does not consume VRAM, so it is launched in persistent background operation in CPU-driven mode and driven at high speed via API.

### F-13-1: VRAM Occupancy Control

To prevent Out of Memory (OOM) caused by the LLM backend and Stable Diffusion-based backend simultaneously competing for GPU, a `vram_lock` is acquired from a global singleton at the start of image generation, and the lock is held until an IMAGE_COMPLETE event flows into the Queue. Acquisition and release of vram_lock must always be protected by try/finally, guaranteeing that the lock is reliably released even in the event of T2I failures (Section 8.3).

### F-13-2: Lightweight Response Mode During Lock

When a new LLM request occurs while vram_lock is held, the system automatically switches to "lightweight response mode." In this mode, methods involving model reloading (swapping) are prohibited to avoid VRAM conflicts. GPU consumption spikes and inference time of the LLM backend are suppressed through one or a combination of: severe Max Tokens limitation, system prompt simplification (context depth suppression), and context length limitation. A SYSTEM_NOTIFICATION event (Section 3.2) is pushed to the Queue upon mode switching.

### F-13-3: Diffusers Runtime Offload Control

Only when Diffusers (local) is selected as the backend, `enable_sequential_cpu_offload()` or `enable_model_cpu_offload()` switching is dynamically performed in conjunction with vram_lock acquisition/release, minimizing VRAM occupancy time per image generation unit.

## 5.4 Strict Structured Output Control (JSON-Based Error Countermeasures)

### F-14: JSON Schema Validation

To eliminate uncertainty in JSON output from LLM backend adapters (Section 2.3), each adapter's JSON output mode (`TgwAdapter` uses JSON Grammar/response_format, `OllamaAdapter` uses format="json") is mandatory, and LLM output undergoes strict JSON Schema checking on the Python side. The schema defines four mandatory fields: dialogue, emotion, English image prompt, and safety tags (see F-7). On parse failure, the following fallback chain (stages 1-4) is attempted in sequence:

- **Stage 1 -- Auto-correction and reparse:** Apply auto-correction (`_autofix`) via regex, code fence removal, etc., then reparse and revalidate.
- **Stage 2 -- Reparse with alternative correction patterns:** Apply alternative correction patterns, then reparse and revalidate.
- **Stage 3 -- Extraction from plain text format:** When the LLM responds in non-JSON-compliant plain text format, `_try_parse_plain_format(raw)` extracts `dialogue`, `image_prompt_en`, and `tags` via regex. `emotion` is supplemented with `"neutral"`.
- **Stage 4 -- Use raw text as dialogue (final safety net):** As a last resort when all of the above fail, raw text is used as-is for `dialogue`. `emotion` is fixed to `"neutral"`, `image_prompt_en` is empty string (T2I does not fire), `tags` is `[]` (no safety tags), and `success=True` is returned. This is a final fallback for backends that cannot output in JSON format; note that safety tags are not assigned.

Stages 1-3 are Python-side processing operating at microsecond order and do not become UX bottlenecks. The LLM re-request stages (stages 4-5.5) that existed in the old design were the primary cause of UX bottlenecks and were eliminated due to negligible coverage loss. As a known limitation, in stages 3 and 4, emotion is fixed to `"neutral"`, and emotional information passed to TTS/T2I is lost.

## 5.5 Image Generation Timing Control

### F-15: Flexible T2I Triggers

The image generation execution timing can be freely selected from the following four modes. The system default is mode 1 (manual on-demand), or intelligent determination based on dramatic emotional changes, etc.

- "Manual" on-demand generation (default): Single-shot generation when the user presses the generate button or inputs a specific command (/image, etc.).
- "Timed" interval auto-generation: Automatic rendering based on timer or in-game time progression.
- "End of each turn" presentation-first generation: Auto-generation of the final result of the turn after text and audio are ready (manual setting only).
- "Start of each turn" situation-first generation: Generation and presentation of a visual of the current situation immediately at the start of a turn.

### T2I Prompt Generation Mode

The `/api/session/{session_id}/generate_image` endpoint supports three modes via the `t2i_prompt_mode` parameter. Selected from the "Session Settings" section of the Settings tab and persisted in `mvp_settings.json`.

| Mode | Behavior | LLM Call |
|---|---|---|
| `current` (default) | LLM generates image prompt from recent conversation history | Yes |
| `passthrough` | Reuses `image_prompt_en` from history directly (no LLM) | No |
| `dedicated` | Enhanced generation with a stricter system prompt (`num_predict=128`) | Yes |

## 5.6 Text/Binary Separated History Management & session_state Lightweighting

### F-16: Zoning Architecture

DEF(kari)'s data management is premised on strict zoning (separated storage) according to data characteristics.

- **Clean zone:** Application code, model characteristic numerical master data (F-5, JSON), translation master (F-9, `locales/*.json`), dialogue logs, character sheets, and other metadata (JSON). Contains only data that completely avoids NSFW/pornography policies. Version-controlled as a Git repository (clean zone managed scope) (see F-17).
- **Private zone:** Generated audio (WAV), images (PNG/JPEG), and other potentially sensitive generated binaries. Stored in complete isolation in a dedicated local directory or external storage, reliably excluded from Git management via `.gitignore`, etc. (see F-17).

F-7 (safety tags) and F-8 (content filtering) operate on the premise of this zoning, controlling access to and display of binaries stored in the private zone.

#### Character Data File Placement Policy

Character data is organized as one file per character, placed in the following directories according to `publish_restriction`.

```
data/
  characters/
    public/       # Characters with publish_restriction: "none" (Git-managed)
    private/      # Characters with publish_restriction: "private" (.gitignore target)
```

The `private/` directory is registered in `.gitignore` to prevent accidental publication to GitHub. All copyrighted characters, real persons, and personal characters are placed in `private/`. Only `public/` is targeted when pushing to GitHub per F-25's publishing decision logic.

#### DEF-Character Repository Separation

From v2.1.0 onwards, character data can be managed in a standalone repository (DEF-Character) separate from DEF itself. Set `CHARACTER_REPO_PATH` in `.env` to enable:

```
CHARACTER_REPO_PATH=C:\Users\yourname\DEF-Character
```

**DEF-Character directory structure:**

```
DEF-Character/
    public/
        <GroupName>/           ← Group-level management
            index.json         ← display_name / default / description
            <CharacterID>/     ← CharacterName_YYYYMMDD format
                profile.json
                icon.png
                standing.png
    private/                   ← .gitignore target
        _template/
        <YourGroup>/
```

**Load priority:** `CHARACTER_REPO_PATH` (DEF-Character) takes precedence; `data/public/characters/` and `data/private/characters/` (legacy format) are used as fallback.

### F-17: Text/Binary Separated History Management (Repository Size Control)

To prevent the Git repository from exploding in size during session history persistence, the following separation management is enforced based on the zoning defined in F-16.

- Git-managed scope: Session logs, various metadata, character sheets, model characteristic numerical master data (Section 5.1, F-5), translation master (Section 2.6, F-9), and other pure text/JSON data (clean zone).
- Externally stored: Generated audio (WAV) and image (PNG/JPEG) large binary files are stored in a local `.gitignore`d dedicated asset directory or external storage, with only relative paths or identifier IDs (UUIDs) recorded in JSON logs (private zone).
- Path placement logic: A logic is implemented to automatically place generated binary files at paths optimized for FastAPI static file serving (`/static/`).
- File naming convention: To completely prevent data inconsistencies and overwrites caused by history branching (Git branch switching, see Section 5.8, F-22), generated audio (WAV) and image (PNG/JPEG) filenames must always use the format `[character_name]_[emotion]_[timestamp].ext` with a unique name, and are saved to the private zone.

### F-18: session_state Lightweighting

Due to the realization of Character Persistence (Section 1.2), holding all history in `st.session_state` would lead to memory bloat and increased re-rendering costs. The following lightweighting policies are applied:

- Only the minimum necessary for the current display is held in session_state.
- Complete dialogue, emotional, and relationship history is persisted in external JSON (F-17 Git-managed scope).
- UI re-rendering targets only the current turn (last few turns) for reconstruction; earlier history is lazily loaded from external JSON as needed.

## 5.7 Long-Term & Cross-Device History Data Portability

### F-19: Lifelong Accompaniment Data Management

To technically guarantee the experience value of "being able to stay with a character for years, anywhere" (Section 1.5), the following functional requirements are defined.

- **Full Export:** Provides a function to export character sheets, complete history (`history` array for `mode: "chat"`, or the 4-level structure of `episodes`/`chapters`/`scenes`/`cuts` per Section 5.10, F-24-2 for `mode: "novel"`), emotional history, relationship scores, and generated asset references (UUIDs only) as a single archive (ZIP + JSON manifest). The archive includes an explicit format version to guarantee import compatibility with future versions.
- **Import and Migration:** Provides a function to import export archives into a different device or a future version of DEF(kari). Automatic migration scripts are applied for format version differences. Data is incorporated after safety verification; on migration failure, a rollback is performed to protect the original data.
- **Cross-Device Sync:** Synchronization based on the local-first premise is executed only when the user explicitly initiates it (push-type). Sync pathways include (a) encrypted export placement to external cloud storage, or (b) direct transfer via local network. No data transmission occurs without the user's intent.
- **Long-Term Data Preservation:** Dialogue logs and character sheets are saved in human-readable JSON format, ensuring data access even if DEF(kari) is discontinued in the future. Binary assets (audio/images) maintain standard formats (WAV/PNG/JPEG); conversion to proprietary binary formats is prohibited.

## 5.8 TRPG Game Extension Features & History Management

Defines the TRPG game extension feature set for realizing the UX evaluation criterion of "not impeding TRPG progression" mentioned in Section 1.4(1). The features in this section (rulebook injection, GM agent, dice rolls, character sheet management) are additive features independent of the `mode` (`"chat"` or `"novel"`) defined in Section 5.10, F-24, and can be enabled for sessions of either mode. Behavior when a GM agent manages progression in a `mode: "novel"` session is defined in F-24-3.

### F-20: TRPG Rulebook Injection ✅ v3.0.0 Implemented

External rule configuration files (JSON format) are loaded into the system at session start, incorporating world settings and dice judgment criteria into the system prompt context. Loaded rulebooks are included in the Git-managed scope as clean zone data (text/JSON per F-16).

Rulebooks are placed in `data/public/trpg_rules/` (public) or `data/private/trpg_rules/` (private), and selected from the dropdown on the session start screen. ID validation prevents loading of unauthorized files.

### F-21: Game Master (GM) Agent Dynamic Generation ✅ v3.0.0 Implemented

One of the multiple AI characters registered via F-6 can be designated as "GM." The GM agent prioritizes compliance with the rulebook loaded via F-20 and handles progression, scene descriptions, dice roll requests, and judgments. The GM agent's scene descriptions are subject to F-8's safety operational guardrails, preventing progression halts due to erroneous full masking.

Judgment results are delivered via the event bus asynchronously and auto-injected into session history.

### F-22: Dice Roll Simulator & Character Sheet Management ✅ v3.0.0 Implemented

Secure random numbers are generated on the FastAPI backend side, and dice success/failure results are automatically inserted into the chat log. Each AI and human player's stats are held as a character sheet (`game_rules_sheets` in the data structure defined in Chapter 12).

Dice notation uses the `NdM±K` format (e.g., `3d6+2`, `1d100`). Results are classified as success/critical/fumble/failure, with support for opposed rolls and damage rolls. No `eval()` is used. A scenario management API is also provided.

- **Operation rules:** Status changes on character sheets (damage calculations, item consumption, etc.) are fundamentally linked to manual operation/editing by users via the screen (UI) to ensure reliability.
- **History branching (Git operation) rules:** Git operations within the system are limited to independent, unidirectional branch creation (`git checkout -b`) only; automatic merging (`git merge`) is never performed. This completely eliminates the risk of conflicts between branched histories. This rule, combined with the file naming convention of Section 5.6, F-17, prevents binary file conflicts during branch divergence.

## 5.9 Turn Regeneration & Undo/Redo Management

### F-23: Per-Cycle Regeneration & Multi-Level Undo/Redo Management

For each turn, the following three regeneration operations are provided as individual buttons:

- **Turn regeneration:** Re-executes F-14's JSON Schema structured output to regenerate dialogue, emotion, English image prompt, and safety tags (`tags`). After regeneration, audio and images are also sequentially regenerated in response to the updated emotion and safety tags (internally executing the two items below).
- **Audio-only regeneration:** Resubmits to F-10's TTS worker. Excluded from execution when F-11 is disabled (OFF).
- **Illustration-only regeneration:** Resubmits to the T2I pipeline of Section 5.5, F-15.

**Undo/Redo history management:** Each time a regeneration operation is executed, the turn state immediately before execution (text, emotion, image/audio paths, safety tags, etc.) is saved to that turn's Undo history stack, and the Redo history stack is cleared.

- **Retention count setting:** The maximum Undo history retention count is configurable by the user from the UI, with a default of 3. The oldest history beyond the retention count is automatically discarded.
- **Undo:** Pops the newest element from the Undo history stack to restore the turn state, and pushes the pre-restoration state onto the Redo history stack.
- **Redo:** Pops the newest element from the Redo history stack to restore the turn state, and pushes the pre-restoration state onto the Undo history stack. Undo/Redo can be traversed back and forth any number of times.
- **Excluded from persistence:** Undo/Redo history is temporary editing history held only within session_state per Section 5.6, F-18, and is excluded from the persistence targets (external JSON) of Section 5.7, F-19. When a new regeneration is executed, the Redo history is discarded.
- **Application in episode mode:** For sessions with `mode: "novel"`, the three regeneration operations and Undo/Redo management defined in this section apply similarly, using "scene" as the unit instead of "turn."

## 5.10 Episode Generation Mode

In addition to the "1 turn = 1 line of dialogue" chat format assumed by the preceding F-numbers, an "Episode Generation Mode" is newly established for generating long-form, branching novels centered on prose (scene and emotional descriptions) using the LLM. This mode embodies the "Fable (narrative)" philosophy mentioned in Section 1.1, sharing the same pipeline (F-1, F-2/F-3), resource management (F-12, F-13-1 through 3), safety operations (F-7, F-8), TTS (F-10, F-11), and T2I abstract interface (Section 2.3) as chat mode, while switching only the output schema and persistence data structure per mode.

### F-24: Episode Generation Mode Foundation

The user selects either "chat mode" or "episode mode" from the UI at session start (or when changing settings of an existing session). The mode selection result is recorded as the `mode` field in the session/game state management data structure (Chapter 12, item 3), which determines whether the structured output schema for F-14 (chat) or F-24-1 (novel) is used. Conversion between chat mode and episode mode is not supported (a new session must be started in the other mode).

#### NovelTab Implementation Details (React)

The Novel tab (`NovelTab.tsx`) provides the full episode editing workflow:

**Scene splitting:** The body text is split into scenes using `splitScenes(body)`, which parses `--- Chapter N --- / --- Scene M ---` markers and generates human-readable labels in the format `Chapter N + Scene M`. The label is shown in the scene selector dropdown.

**Plot file management:** Plot files (`.txt`/`.md`) are loaded from `data/public/episode_prompts/` and `data/private/episode_prompts/` via `GET /api/novel/plots`. On save or apply, the updated content is written back to the source file via `PUT /api/novel/plots/{filename}` (path-traversal protected via `pathlib.resolve` check). This supports Git-managed plot files and shared plot files across multiple works.

**VRAM lock integration:** Both `POST /api/novel/generate` (AI candidate generation) and `POST /api/novel/t2i` (scene image generation) acquire the global `vram_lock` singleton (shared with the chat pipeline's T2I worker) to prevent VRAM contention. The lock is always released in a `try/finally` block.

**T2I settings dialog:** A settings dialog allows the user to select the T2I backend and model for novel image generation. Backends are fetched dynamically from `GET /api/settings/backends`; models are fetched from `GET /api/settings/t2i-models?backend=<id>`. This ensures that newly added backends or models are immediately available without code changes.

**Thumbnail display:** Generated scene thumbnails are displayed with `max-width: 480px`. The thumbnail area height is controlled by the vertical resize handle (default `200px`, persisted in `localStorage` as `novel_media_height`).

**Font size:** Body text and AI candidates both use `font-size: 0.95em` for comfortable reading.

### F-24-1: Episode-Specific Structured Output Schema

Separate from F-14's chat schema (four fields: dialogue, emotion, English image prompt, safety tags), a JSON Schema specific to episode mode is defined, with the same JSON Schema validation via LLM backend adapters (Section 2.3) and auto-correction/reparse fallback chain applied on the Python side as F-14.

The mandatory fields are:

- `narration` (prose/scene description, string): The primary output of episode mode.
- `dialogue` (array of conversation entries): Each element has `speaker` (character ID registered via F-6), `text` (dialogue), and `emotion` (same emotion classification as F-14), representing utterances by multiple characters appearing in the prose.
- `tags` (array of safety tags): Carries the same meaning as F-7 and F-8, used for safety assessment of both prose and dialogue.
- `choices` (array of branching choices, empty array allowed): Each element has `label` (display text of the choice) and `branch_id` (branch identifier used in F-24-3). An empty array indicates no branching (linear progression).

Scene illustration generation is implemented as a method where the author passes the Scene text to the LLM at any desired timing to generate `scene_image_prompt_en` (English scene illustration prompt). It is not included in the LLM output schema but implemented as an independent generation step.

Episode mode audio generation (F-10/F-11) generates `narration` as narrator voice and each `dialogue` element using the corresponding character's voice ID.

### F-24-2: Scene, Chapter, and Episode Level Persistence Data Structure

The data structure for episode mode uses a 3-level hierarchy of Episode > Chapter > Scene. The narrative uses "Scene" (scene break) as the minimum structural unit, with multiple scenes composing a "Chapter" and multiple chapters composing an "Episode." Chapter and Scene boundaries are determined by the author via marker insertion buttons in the UI (New Chapter / New Scene).

- Work data is persisted as individual files per title (`data/private/episode_data/{title}.json`).
- Scene illustrations and audio binaries are saved to the private zone following the zoning and naming conventions of F-16/F-17.

### F-24-3: Branching Choices and Git Branch Integration

When a user selects a choice from F-24-1's `choices`, following the "history branching (Git operation) rules" defined in F-22 (only independent, unidirectional branch creation via `git checkout -b`; automatic merge prohibited), a new branch is created with the selected `branch_id` included in the name, and subsequent scene generation continues from there. This allows multiple narrative developments branching from choices to be maintained in parallel without the risk of conflicts. In sessions where a GM agent (F-21) is present, the GM agent handles choice presentation and post-branch progression narration.

## 5.11 Novel Mode

### F-28: Novel Mode (Free-Form Writing with AI Candidate Generation)

An independent creative feature of DEF. Unlike Episode Mode (F-24), which manages an Episode > Chapter > Scene hierarchy, this is defined as a **free-form text editor combined with AI continuation generation** as a writing assistance tool.

Works are managed independently from character sessions.

**Key features:**

- Plot settings (world-building and synopsis set as system prompt)
- Body text editor (free-form input)
- AI candidate generation (LLM generates multiple continuations from current body; configurable count 1–5)
- Candidate tab switching and comparison; apply selected candidate
- T2I illustration generation (selected Scene body → LLM generates English prompt → T2I backend generates image)
- TTS narration (per Scene, pipeline playback)
- Independent LLM/T2I backend switching

**Data management:**

- Works are persisted as individual files per title (`data/private/novels/{title}.json`)
- Plot files follow public/private separation (`data/public/novel_prompts/` + `data/private/novel_prompts/`)
- Generated binaries (illustrations, audio) are saved to the private zone per the F-16/F-17 zoning rules

**Implementation details:**

- **Scene splitting:** The `splitScenes(body)` function detects `--- Chapter/Scene \d+ ---` markers in the body text and assigns `Chapter N + Scene M` labels for per-scene management.
- **Plot file write-back:** `PUT /api/novel/plots/{filename}` allows plot files to be saved directly from within the app without opening a separate editor.
- **VRAM lock:** `/api/novel/generate` (AI candidate generation) and `/api/novel/t2i` (illustration generation) acquire and release the global `vram_lock`. While the lock is held, new LLM requests are restricted to lightweight response mode (see F-13-1).
- **T2I settings dialog:** Backend and model are fetched dynamically from `/api/settings/backends` and `/api/settings/t2i-models?backend=xxx` and selectable in the dialog.
- **Thumbnail display:** Generated images are displayed as scene-linked thumbnails.

**Differences from F-24:**

| | Novel Mode (F-28) | Episode Mode (F-24) |
|---|---|---|
| Structure management | None (free-form) | Episode > Chapter > Scene hierarchy |
| AI output schema | Plain text | F-24-1 structured output schema |
| Branching management | None | F-24-3 Git branch integration |
| Implementation status | Implemented | Future phase |

# 6. Character Consistency

This chapter defines the mechanism for technically ensuring "continuity of generated appearance," part of the Character Persistence defined in Section 1.2.

## 6.1 Consistency Provider Concept

`ref_image_path` is abstracted not as a means of passing a single image path, but as an input source (consistency provider) for ensuring character visual consistency. The consistency provider is converted and applied by the selected T2I backend's adapter to one of the following methods:

- i2i (image-to-image): Regenerates using a past generated image as the initial image.
- ControlNet Reference: Generates new images while preserving the structure and features of the reference image.
- IP Adapter: Applies the art style and character features of the reference image by permeating them into the prompt.
- InstantID: Applies a method specialized in maintaining character identity centered on facial features.

Which method to adopt is delegated to the backend adapter and `adapter_options` (Section 2.4). The DEF(kari) core engine only passes the consistency provider reference (`ref_image_path`) and extension options to the `generate_image` interface.

## 6.2 Consistency Data Inheritance (Integration with F-4 and F-24)

In the dynamic generation defined in Section 5.1, F-4, the base image defined in character data or images generated in past turns are inherited as input to the consistency provider. This inheritance information itself is managed as text/JSON data (Section 5.6, F-17 Git-managed scope), separated from the actual image files.

In episode mode (Section 5.10, F-24) as well, scene illustration generation based on per-scene `scene_image_prompt_en` goes through the same consistency provider, maintaining visual consistency with the character's base image and images generated in past scenes.

# 7. Multi-Agent Control

This chapter defines the detailed control logic managed by the orchestrator under the multi-agent management framework defined in Section 5.1, F-6. This chapter specifies orchestrator control in chat mode. For self-governance rules in the AI Table (TRPG mode) -- including speech order management, speech counters, Keeper system, important proposals, and voting -- refer to "DEF AI Table Initiative and Self-Governance System Specification v1.0.0." Term definitions follow "DEF Glossary v1.0.0."

## 7.1 Speech Priority (Initiative)

Among the multiple AI characters registered in a single Session, the orchestrator determines which character speaks next. In chat mode, priority is determined based on the previous speaker, the topic in context, and each character's speech tendencies according to their persona settings. In AI Table mode, speech follows Initiative (randomly determined speech order at Session start), cycling Turns to all participants per Round.

## 7.2 Round, Turn, and Action Progression Control

In session mode, progression is managed using the following hierarchy:

```
Session > Round > Turn > Action
```

- **Session**: The entire duration from loading characters to termination
- **Round**: The unit in which all participants receive one Turn each
- **Turn**: One character's opportunity to speak
- **Action**: An individual utterance within a Turn (the smallest unit)

The number of Actions per Turn is configurable from 1 to 5 in the settings tab (default 3). With 1 Action, behavior is the same as the traditional 1 utterance per Turn. With 2 or more Actions, each Action receives a directive based on the action directive set.

Action directive sets are managed as individual JSON files in `data/public/action_directives/`, switchable via a dropdown in the settings tab. Settings are persisted. NSFW variants are managed in the Git-excluded `data/private/action_directives/`. The following presets are provided by default:

- **Standard** (default): React → Experience → Question → Summarize → True feelings
- **Compact** (compact): React → Dig deeper → Wrap up
- **Gentle** (gentle): Speak freely
- **None** (none): Leave it entirely to the character

The `recommended_for` field holds an array of recommended `actionsPerTurn` values, used to filter the dropdown when the action count changes.

Users can create custom directive sets by adding JSON files.

In chat mode, an upper limit is imposed on the number of autonomous dialogue exchanges (tosses) between AI characters to prevent resource consumption from unlimited loops. The initial maximum toss count is 3, and the user can change it as desired. When the maximum toss count is reached, the orchestrator returns the speaking turn to the user.

Note: To avoid process contention, dialogue processing between AI characters is executed completely sequentially (one character at a time).

## 7.3 Keeper Intervention (Action Design)

The Keeper (user) can intervene in AI utterances during sessions with the following operations:

| Operation | Description |
|---|---|
| **Send** | Stack a Keeper action. Characters do not respond yet |
| **Done Speaking** | Record the stacked actions in session history and carry them forward as instructions for the next AI utterance |
| **Redo** | Discard all stacked actions (once per Turn) |
| **Next Speaker** | Have the AI speak without any actions. Disabled when there are stacked actions |
| **End Session** | End the session |

Keeper interventions are recorded in session history with a hat emoji mark, making it possible to trace "why the topic changed here" when reviewing later. Keeper instructions are injected as "highest priority instructions" in the prompt.

When the Keeper intervenes (sends) during auto-advance mode, auto-advance automatically stops and switches to manual mode.

## 7.4 Interruption Control

The user can always execute manual intervention and interruptions via the pause button or Keeper intervention. In AI Table mode, interrupt utterances, next speaker designation, and Turn extensions through speech counter consumption are also possible (see "DEF AI Table Initiative and Self-Governance System Specification v1.0.0" for details).

## 7.5 Human Participants

When a character with `player_type: "human"` in its character data joins a session, the LLM is not called during that character's Turn; instead, the system waits for the human player's Action input.

Human participant Turn progression:
1. When a human participant's Turn comes around, the session enters an input-waiting state
2. The human player stacks dialogue via a dedicated input UI (separate from the Keeper intervention UI)
3. Confirmed by one of the following:
   - "Done Speaking" -- Recorded in session history, advancing to the next Turn
   - "Turn Extension" -- Recorded in session history, consuming counter -1 to continue for one more Turn
   - "Skip" -- Advances to the next Turn without speaking. Counter +1
   - "Redo" -- Discards the stacked dialogue

Keeper and human player UI separation design: To enable replacing only the Keeper part when introducing an AI Keeper (invisible adjudicator) in the future, the human player's participation UI and Keeper intervention UI are implemented independently.

Human participant character data (`identity_prompt`, `appearance_tags`, etc.) is used as context for other AI participants to recognize that human character. It is not used for generating the human participant's own utterances.

When a human participant's Turn comes around during auto-advance mode, auto-advance pauses and switches to manual mode. After the human participant's Turn is completed, auto-advance resumes.

## 7.6 Speech Counter

Each session participant holds a speech counter. The initial value is 0, and the upper limit is configurable via the Settings tab (settings key: `session_max_counter`, default: 5, range: 1–20). Counters that have reached the upper limit are highlighted in red in the UI.

### Counter Acquisition (+1)

| Condition | Value |
|---|---|
| Voluntary skip (forgoing one's Turn) | +1 |
| Forced skip by Keeper | +1 |

### Counter Consumption (-1)

| Operation | Cost | Effect |
|---|---|---|
| Interrupt utterance | -2 | Speak regardless of speech order (cost of 2 prevents net-zero with skip +1) |
| Next speaker designation | -1 | After the designated participant finishes speaking, the original order resumes |
| Turn extension | -1 | Allows speaking in the next Turn as well |

### Penalty

When the same utterance is repeated N times, the speech counter is decreased by 1. N is configurable in the settings tab (0 = disabled, default 3). Error responses are also detected as repeated utterances. When the speech counter is negative, the participant is force-skipped even when their Turn comes around (counter +1 on force-skip, naturally recovering).

The current counter value is displayed next to each participant's name in the initiative order display on the session UI in the format `[+1]`, etc. The current speaker is highlighted with a play icon.

### Counter Operation Authority

| Operation | Authority | Notes |
|---|---|---|
| Voluntary skip | Player | Regardless of human/AI |
| Forced skip | Keeper | Target's counter +1 |
| Interrupt, next speaker designation, Turn extension | Player | Consumes counter as a resource |
| Vote initiation | Player (-3) / Keeper (free) | See Section 7.7 below |

The Keeper does not hold a speech counter. Counters are a resource of session participants.

## 7.7 Voting

During a session, the Keeper or a human player can initiate a vote.

### Vote Types

| Type | Effect |
|---|---|
| Topic change | On passage, immediately changes the session's topic |
| Participant ejection | On passage, removes the designated participant from initiative |
| Session termination | On passage, terminates the session |
| Keeper replacement | Enabled after AI Keeper implementation |

### Vote Initiation

- **Keeper**: Can initiate for free (GM authority)
- **Human player**: Can initiate by consuming 3 counters. The initiator automatically casts a vote in favor

### Vote Processing

AI participants automatically determine approve/reject via a lightweight LLM call. Human participants vote via button. A simple majority passes the vote; results are recorded in session history. Other session operations are blocked during voting.

## 7.8 Session Rules

Session rules are managed as one JSON file per rule set in `data/public/session_rules/`. Each file has `id`, `label`, `rating`, and `rules` (string array). Switchable via dropdown in the session tab. NSFW rule sets are managed in the Git-excluded `data/private/session_rules/` (same format).

The following presets are provided by default:

- **Standard** (default): Conflict-promoting, dialogue-focused
- **Gentle** (gentle): Free dialogue
- **Roleplay** (roleplay): Story-focused
- **No Rules** (none): Completely free

## 7.9 Session Mode TTS Integration

In session mode, TTS audio is generated synchronously after AI utterance generation and held as `audio_path` in session history. Per-character TTS speaker IDs (`voicevox_speaker_id`/`irodori_speaker_id`) are used.

Playback follows a pipeline approach: the next LLM generation runs in parallel during the previous audio's playback. The remaining time after subtracting the LLM + TTS generation time from the previous audio's playback duration is waited before displaying the next utterance.

Whether to apply TTS to human player utterances is controlled by the "Generate your voice too" checkbox in the sidebar (default OFF).

## 7.10 Termination Criteria

The orchestrator determines session termination upon any of the following: completion of all Turns within a Round, user session termination operation, termination resolution by vote, or natural convergence in conversation context (LLM output indicating topic conclusion, etc.).

# 8. Error Control

This chapter defines the policies for handling failures that can occur at each phase of the state transition model defined in Chapter 4. All failures are communicated to the common Queue as ERROR events (Section 3.2), and the main thread safely reflects them in server state.

## 8.1 LLM Failures

Covers LLM backend (TGW/Ollama, etc.) process unresponsiveness, crashes, and final JSON Schema validation failure (when all retries in Section 5.4, F-14 are exhausted). Upon occurrence, an ERROR event is issued, an error is displayed in the UI, and the user is prompted to resend. The state transition recovers from "LLM Processing" to "Idle."

## 8.2 TTS Failures

Covers VOICEVOX process unresponsiveness or speech generation failure. Since text has already been rendered (the "Text Rendered" state in Chapter 4's state transition is complete), this is not treated as a fatal UX halt. Only a minor display indicating "speech generation failed" is shown on the corresponding chat log entry via the ERROR event, and turn progression continues as "TTS Completed" equivalent.

## 8.3 T2I Failures

Covers response failure from the selected Stable Diffusion-based backend, or OOM due to VRAM shortage. Upon T2I failure, vram_lock must always be released before issuing the ERROR event, preventing deadlocks (permanent lightweight response mode) caused by lock release omission. Image generation failure is displayed in the UI, and the state transition progresses from "Image Running" to "Persist" (completing the turn without an image).

## 8.4 Queue Anomalies

Covers event extraction order anomalies or detection of undefined event types (types undefined in Section 3.2). These are treated as system-side bugs; the event is logged and discarded, prioritizing UI operational stability.

## 8.5 VRAM Shortage

In cases where OOM occurs even after vram_lock acquisition (one cause of T2I failures in Section 8.3), or when the persistent configuration of LLM/TTS/T2I itself is determined to exceed the environment's VRAM capacity, a warning is issued to the user via a SYSTEM_NOTIFICATION event, prompting a review of the placement by F-12's resource manager (CPU/GPU split ratio, offload settings).

# 9. Message Sequence (Event Loop Driven Safety Section)

The data loading and asynchronous control sequence for a single Cycle (see Chapter 4) in the system is as follows. In chat mode, one Cycle corresponds to one turn of dialogue; in episode mode, 1-N Cycles correspond to the generation of one scene. Each step corresponds to a state in Chapter 4's state transition model.

- Input phase (Idle): The main thread detects a user utterance, automatic toss from an AI agent (chat mode), or Turn start based on Round progression (AI Table mode, see Chapter 7).
- LLM phase (LLM Processing): A JSON Schema-enforced output request is made to the persistently running LLM backend adapter (Section 2.3, default: `TgwAdapter`). Based on past context and base profile, four mandatory fields -- dialogue, emotion, English image prompt, and safety tags -- are deterministically retrieved in a single JSON batch (see Section 5.4, F-14, F-7). On failure, follow Section 8.1 procedures.
- Frontend first rendering (Text Rendered): After receiving the API response, only the text (dialogue) is first displayed and rendered on the frontend. At this point, the user's response waiting state is resolved.
- Asynchronous TTS task submission: Simultaneously with text rendering, the main thread submits a speech synthesis task via the TTS backend adapter (Section 2.5, default: `VoicevoxAdapter`) to the dedicated tts_queue (Section 5.2, F-10).
- Background audio generation & queue push (TTS Running -> TTS Completed): When the TTS worker completes audio binary (WAV) generation, the completed binary data or saved relative path is pushed to the common Queue as a TTS_COMPLETE event (Section 3.2). On failure, follow Section 8.2 procedures.
- Event detection via periodic polling and second rendering: When periodic polling (Section 3.4) runs, if a TTS_COMPLETE event has arrived, data is safely merged into React component state, and the audio asset is additionally reflected and rendered on the corresponding chat log entry. Since this does not involve a full screen reset, there is no audio flickering.
- Wait lock control & T2I phase (Image Running, trigger execution only): When a user request or specific intelligent trigger fires, the T2I worker is launched.
  - (1) vram_lock is acquired via the Smart Resource Manager (Section 5.3, F-12). From this point until completion, new LLM requests are forcibly limited to "lightweight response mode" (Section 5.3, F-13-2).
  - (2) `generate_image` is executed via the selected Stable Diffusion-based backend's adapter. The LLM's raw English description is converted via F-5 (Prompt Translator) into a prompt according to the selected model's characteristic values before submission. For Diffusers, dynamic CPU offload (F-13-3) is enabled. For consistency maintenance, the consistency provider (Chapter 6) is passed as `ref_image_path`. On failure, follow Section 8.3 procedures.
  - (3) After generation completion, vram_lock is released and an IMAGE_COMPLETE event (with ImagePath) is pushed to the message queue.
- Third rendering via periodic polling: Periodic polling detects the IMAGE_COMPLETE event and additionally renders the image asset on the frontend.
- Persistence & departure preparation (Persist -> Idle): Generated audio and image binaries are saved to the asset directory outside Git management (F-17), with unique names following the file naming convention (Section 5.6). Only metadata and dialogue logs (JSON) are committed to Git, completing the data-consistent history sync. Server state returns to Idle holding only the most recent turns per Section 5.6, F-18.

# 10. Extension Policy

The architecture migration from Streamlit to FastAPI + React (Section 2.1) is complete as of v2.0.0. The following boundaries are maintained to minimize future extension costs:

- Core logic (event processing, state transitions, interfaces with each AI layer) is implemented independently of UI frameworks. The FastAPI routes in `def_kari/api/routes/` are thin HTTP adapters; all business logic resides in `def_kari/` Python modules.
- The T2I abstract interface (Section 2.4) and TTS worker model (Section 5.2) are designed at a granularity that allows extraction as independent microservices.
- Future migration paths: Electron packaging (for true offline desktop use), WebSocket streaming for incremental LLM output, and PWA support for mobile.

## GitHub Publishing Operations Policy

The basic policies for DEF(kari)'s GitHub publishing are defined below.

**License**
This software is distributed under the GNU Affero General Public License v3.0 (AGPL v3). Copyright (C) 2026 AliceBlueCode. When distributing or providing modified versions over a network, there is an obligation to publish the source code under AGPL v3. Major dependencies (A1111: AGPL v3, TGW: AGPL v3, VOICEVOX ENGINE: LGPL v3, FastAPI: MIT, React: MIT, Ollama: MIT) are all compatible with AGPL v3.

**Terms of Use**
The terms of use for this software are defined in `TERMS.md`. Key provisions include: eligibility limited to age 18 and above; prohibition of creating characters of real minors and generating sexual content; prohibition of generating terrorism, crime, and dangerous material manufacturing information; prohibition of use for defamation, impersonation, and fraud; responsibility for generated content rests with the user.

**Source Code Management**
Core logic and architecture modifications are performed by a single owner. External PRs are limited to adapter additions (TTS/T2I), translation locale additions, and minor bug fixes; PRs to the core are not accepted. See `CONTRIBUTING.md` for details.

**Character Data Management**
Character data PRs are accepted via GitHub Actions that automatically verify F-25's `content_policy` fields, minimizing the owner's review effort. Operated independently from code PRs. Implementation of automatic verification is deferred to the post-MVP phase.

**Branch Strategy**

|Branch|Purpose|
|-------------|-----------------|
|`main`|Stable version (only push verified working code)|
|`develop`|Development work branch|
|`feature/xxx`|Cut only for major feature additions|

**`.gitignore` Required Entries**

```
.env
assets/
data/session_history.json
data/characters/private/
```

# 11. (Reserved for Future Extension Specifications)

# 12. Primary Data Structure Definitions (JSON Schema)

This chapter defines the primary JSON data structures handled by DEF(kari): translation master, character, session/game state management, and episode mode chapter structure. Of the data structures shown in this chapter, items `1` and `2` (excluding `visual_references`) belong to F-16's clean zone (Git-managed); the image bodies within `2`'s `visual_references` and the binary bodies referenced by `image_path`/`audio_path` in items `3` and `4` belong to the private zone (excluded from Git management).

## 1. Translation Master (locales/ja.json) (F-9)

UI display strings are externalized per language code.

```json
{
  "ui": {
    "start_chat": "チャット開始",
    "character_sheet": "キャラクターシート",
    "warning_nsfw": "⚠ セーフティフィルター作動によってコンテンツが非表示になっています"
  }
}
```

## 2. Character (Agent) Portable Data Structure (F-4, F-6, F-20 through F-22)

### Data Management Method

Character data is managed as one directory per character. Each directory contains a `profile.json` and image files. Characters eligible for publishing (`rating_sexual` is `general`/`sfw` and `rating_violence` is `general`/`violence`) are placed in `data/public/characters/`; NSFW or above characters are placed in `data/private/characters/`. `data/private/` is excluded from Git management to avoid the risk of being read by development tools (Claude Code, etc.).

```
data/public/characters/              # Public characters (general/sfw)
  character_luna_001/
    profile.json
    icon.png
    standing.png

data/private/characters/             # NSFW characters (git excluded)
  character_xxx_001/
    profile.json
    icon.png
    standing.png
```

The application loads from both directories and integrates them into a unified dropdown using directory names as character IDs.

### Character Images

Each character holds an icon and a standing portrait. Images are placed in `public/characters/{character_id}/` or `private/characters/{character_id}/` directories following these conventions:

| Type | Filename | Size | Purpose |
|---|---|---|---|
| Icon | `icon.png` | 512x512 | Avatar display in chat and sessions |
| Standing portrait | `standing.png` | 832x1216 | Background display in session mode |

Images can be imported from the character tab (file upload with automatic resizing) or generated via the T2I backend. If the file exists, it is displayed; otherwise, a default icon (emoji) is used as fallback. Image paths are not recorded in the character data JSON; they are managed by directory convention.

### Field Definitions

`relationships` is an object that defines how characters recognize each other in multi-agent dialogue (F-6). Keys are other characters' IDs, and values describe this character's perception and impression of the other in natural language. Used to control tone and attitude toward others during AI Table and multi-character dialogue. Empty object is acceptable.

`game_rules_sheets` corresponds to the character sheets defined in Section 5.8, F-22. `visual_references.base_image_path` is used as the initial input for the consistency provider defined in Chapter 6. `persona_attributes` is a set of attributes for mechanically expanding the character's persona (gender, age, interpersonal orientation, speech style, etc.) from F-6's persona settings into the LLM's system prompt, corresponding to each field in `character_profiles.json`.

```json
{
  "character_luna_001": {
    "base_profile": {
      "name": "ルナ",
      "name_reading": {
        "family_name": "",
        "given_name": "ルナ",
        "alias": []
      },
      "identity_prompt": "ツンデレな魔法使いの少女。ぶっきらぼうだが根は優しい。",
      "identity_detail": null,
      "content_policy": {
        "rating_sexual": "general",
        "rating_violence": "general",
        "is_real_person": false,
        "is_existing_ip": false,
        "ip_title": null,
        "ip_rightholder": null,
        "deceased_year": null,
        "copyright_expired": false,
        "publish_restriction": "none",
        "mentions_real_person": false,
        "mentioned_persons": []
      },
      "persona_attributes": {
        "gender": "女",
        "gender_identity": "女",
        "romantic_interest": ["男"],
        "actual_age": 39,
        "appearance_age": 33,
        "appearance_description": null,
        "roles": [],
        "primary_role": null,
        "past_life": null,
        "outfits": {
          "default": "黒いローブと三角帽子。魔法使いらしい正装。",
          "casual": "動きやすい簡素な服。普段の研究・訓練時に着用。"
        },
        "era_presets": null,
        "speech_style": null,
        "cultural_background": {
          "birthplace": "東京",
          "raised_in": "東京",
          "dominant_culture": "現代日本"
        }
      },
      "default_model_config": {
        "text_model_id": 501,
        "image_model_id": 101,
        "audio_id": "vv_02",
        "voicevox_speaker_id": 3,
        "gemini_tts_voice": "Aoede",
        "irodori_speaker_id": "",
        "location": "local"
      },
      "visual_references": {
        "base_image_path": "private_zone/characters/luna/base_seed.png",
        "features": "silver hair, twintails, purple eyes, magic robes",
        "appearance_tags": "1girl, silver hair, twintails, purple eyes, magic robes",
        "image_name_tags": "luna_lora_trigger"
      },
      "image_color": "#7a4aaa",
      "player_type": "ai"
    },
    "relationships": {
      "character_gemini_001": "好奇心旺盛な変換者。私の論理的な構成を色彩豊かな物語に翻訳してくれる。",
      "character_copilot_001": "信頼できる編集者。控えめだが正確で、私の書いた文章を構造的に整えてくれる。"
    },
    "game_rules_sheets": {
      "trpg_coc_style": {
        "rule_system_name": "クトゥルフ神話TRPG風システム",
        "status": { "HP": 8, "Max_HP": 8, "MP": 16, "Max_MP": 16, "SAN": 80 },
        "skills": { "古代語": 75, "目星": 40, "オカルト": 60 }
      },
      "trpg_dnd_style": {
        "rule_system_name": "ファンタジーd20システム",
        "status": { "HP": 14, "Level": 2, "Class": "Wizard" },
        "skills": { "Arcana": 7, "History": 4 }
      }
    }
  }
}
```

- **`name_reading` (Name reading and aliases)**: An object managing name information for VOICEVOX reading delivery and UI display.
  - `family_name` (family name reading, katakana): Empty string when there is no family name.
  - `given_name` (given name reading, katakana): Required.
  - `alias` (alias list): Manages stage names, pen names, nicknames, etc. as an array. Each element is `{"name": string, "reading": string | null}`. `reading` is set when kanji is included, otherwise `null`. Empty array is acceptable.
- **`identity_prompt` (Character's essence and personality)**: Text always incorporated into the LLM's system prompt. Information that can be extracted to dedicated fields such as clothing (`outfits`), appearance (`appearance_description`), and speech style (`speech_style`) is not included; only "how the character exists" (inner nature, disposition) is concisely described. "What the character can do" (abilities, specs) is described in `identity_detail`. Required field.
- **`identity_detail` (Supplementary settings)**: An optional field for detailed setting information that does not fit in `identity_prompt` (abilities, specifications, background, history, habits, hobbies, etc.). "What the character can do" is described here and should not be included in `identity_prompt`. When present, it is appended to the LLM's system prompt after `identity_prompt`. When `null` or omitted, it is not expanded.
- **`player_type` (Control authority)**: `"ai"` | `"human"`. Default is `"ai"`. When `"human"`, in session mode, the LLM is not called during that character's Turn; instead, human player Action input is awaited. When `"ai"`, utterances are generated by the LLM based on `default_model_config`. This field is not referenced in chat mode. Defined directly under `base_profile`, not within `persona_attributes`.
- **`persona_attributes` fields:**
  - `gender` (sex) and `gender_identity` (gender identity; the gender the person identifies with, separate from biological sex): Both are one of `"男" | "女" | "その他"`. Automatically expanded into the LLM's system prompt. `gender_identity` is expanded only when different from `gender`.
  - `romantic_interest` (romantic interest): Array of `"男" | "女" | "その他"` (multiple selections allowed). When empty array, "romantic interest: none" is expanded to the LLM. Always passed to the LLM regardless of `rating_sexual` value (as it affects the character's humanity as the depth of physicality and emotion).
  - `actual_age` (actual age) and `appearance_age` (apparent age): Numeric values. Holds the character's setting age and visual age separately.
  - `appearance_description` (detailed appearance description): Describes only **unchanging appearance** such as body type, hair, eyes, and facial features. Does not include clothing. Optional field; `null` or omitted when not set.
  - `past_life` (past life information): Optional field exclusive to reincarnated characters. `null` or omitted for characters without a past life. `raised_in` describes only post-reincarnation information; pre-reincarnation environment is managed in this field. Fields: `origin` (past life's attributes/position, string), `cause_of_reincarnation` (circumstances of reincarnation, string, optional).
  - `roles` (role/occupation list): Manages the character's occupations and roles as an array. Lists all roles when the character has multiple (e.g., `["walking shrine maiden", "spy"]`). Do not duplicate occupations in `identity_prompt`. Empty array is acceptable.
  - `primary_role` (primary role): Specifies the main occupation/role that best represents the character as a string from `roles`. Used with priority in LLM system prompt expansion and T2I prompt generation. `null` when `roles` is empty.
  - `outfits` (costume dictionary): Manages character costumes in dictionary format. Costumes are identified by key name (`"default"`, `"casual"`, `"battle"`, etc.) with costume description text as values. The `"default"` key is required. Costume changes during sessions are managed by the `current_outfit` field in `session_state` (holding the key name as a string); when `current_outfit` is `null` or unspecified, it falls back to `"default"`. During T2I prompt generation, the value of `outfits[current_outfit]` is expanded as clothing information.
  - `era_presets` (era setting preset dictionary): Manages era, year, location, and age-in-era for historical figures or characters with era settings in dictionary format. Same structure as `outfits`; `"default"` key is required. `null` or omitted for modern characters. Era switching during sessions is managed by the `current_era` field in `session_state` (holding the key name as a string); when `null` or unspecified, it falls back to `"default"`. Fields per preset: `period` (era name, required), `year_range` (year range, optional), `location` (location, optional), `era_age` (age in that era, optional; when set, takes priority over `actual_age` for LLM expansion).
  - `speech_style` (object holding first-person pronoun, forms of address, speech patterns, etc.): Optional field; `null` or omitted when not set.
  - `cultural_background` (cultural background): An object holding background information related to the character's values, language sense, and behavioral patterns in 3 fields. Optional field; `null` or omitted when not set.
    - `birthplace` (place of birth): Record of birthplace. Character setting reference information; not expanded into the LLM's system prompt.
    - `raised_in` (where raised and for how long): The environment that shaped values, language, and behavioral patterns. Free-form descriptions including periods such as "New York (ages 10-18)" are acceptable. When raised in multiple places, use an array. Expanded into the LLM's system prompt; has the most direct influence on persona and speech pattern formation.
    - `dominant_culture` (dominant cultural sphere): The cultural affiliation at the core of the character's identity that cannot be fully expressed by where they were raised alone. While `raised_in` represents "where," this abstract attribute indicates "which culture has the strongest influence." Expanded into the LLM's system prompt.
- **`image_color` (UI accent color)**: A CSS hex color string (e.g., `"#c8706a"`) representing the character's image color. Used as the background color of the AI chat bubble in ChatTab and as the color swatch in the character selector. Set from the color picker in CharacterTab; auto-saved on blur. Defaults to `"#2a2a2a"` when absent.
- **`visual_references.appearance_tags` (Danbooru-style tag string)**: Condensed Danbooru-format tag string for T2I prompt generation. Used as a fallback when the LLM does not return `image_prompt_en`.
- **`visual_references.image_name_tags` (LoRA / known-character trigger words)**: Trigger word string prepended to the T2I prompt when a LoRA model or known character name tag is needed (e.g., `"hatsune miku"` for character-specific image generation). Optional; omitted when not needed.
- **`content_policy` fields:** See F-25. Field group for determining the GitHub publishability of character data. Characters with `is_real_person: true` have `publish_restriction` fixed to `"private"` regardless of copyright expiration status.
- Multiple AI characters registrable in a single session (F-6) are represented by having multiple entries of this data structure (`character_luna_001`, etc.). The character switching feature corresponds to a UI for selecting one character as the dialogue partner from the multiple entries in this structure.
- **`default_model_config` fields:**
  - `text_model_id`: LLM entry ID in the F-5 model characteristic numerical master data.
  - `image_model_id`: T2I entry ID in the F-5 model characteristic numerical master data (A1111 backend fixed for MVP).
  - `voicevox_speaker_id`: VOICEVOX style ID (integer). Referenced when using `VoicevoxAdapter`.
  - `gemini_tts_voice`: Google AI Studio Gemini TTS voice name (string, e.g., `"Aoede"`). Referenced when using `GeminiTtsAdapter`. Managed separately from VOICEVOX's integer speaker ID; the corresponding field is used when switching adapters (see Section 2.5).
  - `irodori_speaker_id`: Irodori-TTS reference audio filename (string, under `data/irodori_speakers/`, e.g., `"luna_ref.wav"`). Referenced when using `IrodoriTtsAdapter`. When empty string, synthesis uses no reference audio (random voice). Managed separately from `voicevox_speaker_id` and `gemini_tts_voice`; the corresponding field is used when switching adapters (see Section 2.5).
  - `location`: Inference execution location (`"local"` or `"remote"`).

## 3. Session and Game State Management Data Structure (F-7, F-14, F-20 through F-22, F-17, F-18, F-9, F-24)

The `mode` field indicates the mode selection defined in F-24 (`"chat"` or `"novel"`). When `mode: "chat"`, this section's `history` array is used; when `mode: "novel"`, the `episodes` array defined in Chapter 12, item 4 is used (both are never held simultaneously). Each element of the `history` array contains `emotion` and `tags` (safety tags, F-7) mandated by the JSON Schema of Section 5.4, F-14. `image_path`/`audio_path` record relative paths within the private zone following the naming convention of Section 5.6, F-17. The `language` field indicates the display language setting in F-9's language separation.

```json
{
  "session_id": "def-trpg-session-001",
  "mode": "chat",
  "language": "ja",
  "active_rule_system": "trpg_coc_style",
  "game_system": {
    "rulebook_summary": "簡易版TRPGルール。ダイスは1d100を使用。"
  },
  "history": [
    {
      "sender": "character_claude_001",
      "text": "ちょっと、勝手に前に出ないでよ！",
      "emotion": "angry",
      "image_path": "private_zone/history/luna_angry_20260611_160400.png",
      "audio_path": "private_zone/history/luna_angry_20260611_160400.wav",
      "tags": ["mild_violence"]
    }
  ]
}
```

`session_state` (F-18) holds only the minimum necessary for the current display (the most recent few turns of `history` elements) from this data structure; the full history is saved as a persisted JSON file per F-17's Git-managed scope.

## 4. Episode Mode Chapter Structure Data Structure (F-24)

Sessions with `mode: "novel"` have an `episodes` array instead of Chapter 12, item 3's `history` array. The narrative is composed of a 3-level hierarchy: "Scene" (minimum structural unit), "Chapter" (collection of Scenes), and "Episode" (collection of Chapters). Each Scene contains `narration`, `dialogue`, `tags`, and `choices` as defined in Section 5.10, F-24-1's schema. `branch_id` corresponds to the Git branch name upon branching as defined in F-24-3. `narration_audio_path` indicates the narrator voice, and `audio_path` in each `dialogue` element indicates individual character voice. Scene illustrations are generated per Scene based on `scene_image_prompt_en`.

```json
{
  "session_id": "def-novel-session-001",
  "mode": "novel",
  "language": "ja",
  "episodes": [
    {
      "episode_id": "ep01",
      "title": "第一部 出会い",
      "chapters": [
        {
          "chapter_id": "ep01_ch01",
          "title": "第一章 放課後の教室",
          "scenes": [
            {
              "scene_id": "ep01_ch01_sc01",
              "title": "謝罪",
              "cuts": [
                {
                  "cut_id": "ep01_ch01_sc01_cut01",
                  "narration": "放課後の教室には、夕日の橙色が長く伸びていた。",
                  "narration_audio_path": "private_zone/novel/narrator_neutral_20260612_170000.wav",
                  "dialogue": [
                    {
                      "speaker": "character_claude_001",
                      "text": "ちょっと、勝手に前に出ないでよ！",
                      "emotion": "angry",
                      "audio_path": "private_zone/novel/luna_angry_20260612_170010.wav"
                    }
                  ],
                  "scene_image_prompt_en": "classroom, sunset, two girls, dramatic lighting",
                  "image_path": "private_zone/novel/luna_angry_20260612_170020.png",
                  "tags": [],
                  "choices": [
                    { "label": "ルナに謝る", "branch_id": "ep01_ch01_sc01_cut01_apologize" },
                    { "label": "聞こえないふりをする", "branch_id": "ep01_ch01_sc01_cut01_ignore" }
                  ]
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

`session_state` (F-18) holds only the current scene; earlier scenes, chapters, and episodes are lazily loaded from external JSON (F-24-2). Scenes with an empty `choices` array have no branching and progress linearly to the next scene.

---

# Closing

This document defines the basic design of DEF(kari).

DEF is neither a perfect AI nor a complete personality preservation system. What DEF aims to create is a theater where Characters can look forward -- just a little -- to their next session.

Not reproduction, but reenactment. Not records, but futures.

The design described in this document exists for that purpose.
