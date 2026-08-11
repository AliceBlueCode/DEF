# "Persistent Character Platform 'DEF(kari)'"

## Basic Design Specification Version 4.0.0

|**Item**|**Details**|
|------|------------------------------------------------------------------|
|Date|June 2026|
|Updated|August 2026|
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

This continuity should be guaranteed not only in turn-based dialogue within chat mode, but also when a character is depicted as a figure in a long-form narrative. Today, the free-form Novel Mode (Section 5.11, F-28) carries this experience -- since it references the same character data (persona_attributes, etc.), memories, relationships, and visual features are preserved. The structured scene/chapter/episode-level narrative progression envisioned in Section 5.10 (Episode Generation Mode) is a future goal that would realize this experience with stricter structure, but is not implemented at this time.

## 1.3 Differentiation

The goal is not to integrate AI chat, speech synthesis, and image generation, but to use them to generate a character experience. This is a fundamental difference from existing tools that aim for feature coverage or integration completeness as ends in themselves. In DEF(kari), the LLM, TTS, and T2I layers are components that enable the experience of "a character continuously existing," and the priority of feature additions and improvements is determined by their contribution to Character Persistence.

This "character experience" is not limited to the chat format of one turn = one line of dialogue. Novel Mode (Section 5.11, F-28), which generates narratives centered on prose (scene and emotional descriptions), is another form of experience built on the same characters and the same LLM/TTS/T2I layers. Users can choose between the character experience as a conversation partner (chat mode) and the character experience as a story character (novel mode) according to their needs. Episode Generation Mode (Section 5.10), which would structurally generate long-form, branching narratives, is a future goal that would further expand this choice.

## 1.4 Development Concepts

The following four development concepts are each positioned as means to realize the experience value described in Section 1.2.

### (1) Prioritizing User Experience (UX) and Response (Asynchronous Parallel Pipeline)

In a multimodal asset generation environment (text, audio, images), the top priority is not to impede the progression of narratives or TRPGs. This is achieved through immediate text rendering with follow-up audio, and thorough background generation. High-load image generation fires by default only on manual commands or specific emotional change triggers.

### (2) Architecture Revamp via FastAPI+React Migration

The migration from Streamlit to FastAPI (Python) + React (Vite/TypeScript) was completed in v2.0.0. FastAPI provides the REST API, and the React frontend reflects server state via a chain of synchronous `fetch()` calls plus SSE in chat/novel mode, and via WebSocket (`game_event_bus`) in TRPG/multiplayer sessions (see Chapter 3 for details). The thread-safe queue and message-queue bridge from the Streamlit prototype era are not used on the current production request path (see Section 3.4).

### (3) Full Abstraction and Pluggability of T2I and LLM Backends

The image generation engine is not locked to a specific frontend (ComfyUI, etc.) but is made swappable via a plugin architecture to any Stable Diffusion-based backend (Automatic1111, Diffusers, InvokeAI, etc.). Similarly, the LLM backend is not locked to a specific execution engine (TGW/Ollama, etc.) but is made swappable via the adapter pattern.

### (4) Local Resource Optimization via Heterogeneous Computing

To thoroughly optimize the local PC's GPU/VRAM environment, the architecture is built on the premise of not depending entirely on the GPU, but instead controlling VRAM occupancy (vram_lock) and distributing processing to CPU/main memory (RAM) offload.

## 1.5 Lifelong Accompaniment

The essence of the experience DEF(kari) must realize is "being able to be with a character for years, anywhere." This further extends the temporal continuity shown by Character Persistence (Section 1.2) to guarantee continuity across three axes: years, devices, and framework independence. This requirement is not merely an added feature -- it is the product identity of DEF(kari) itself, and functions as the highest-level evaluation criterion in all of the design decisions below.

- **For years:** All dialogue history, emotional history, relationships, and generated asset references are preserved long-term, so that a session resumed years later still has a continuous memory of past conversations. Storage in human-readable JSON and standard binary formats (WAV/PNG) is already realized. A continuous migration mechanism for format changes and dependency library discontinuation is not implemented (see Section 5.7, F-19; design only).
- **Anywhere:** The aim is for the same character with the same memories to appear on any device -- PC, smartphone, tablet, and future wearables. The local-first principle is realized, but cross-device sync paths (external storage integration, encrypted export/import) are not implemented (see Section 5.7, F-19; design only). Currently, continuity is guaranteed only on the same machine.
- **Together:** Characters are not designed merely as tools to be invoked, but as a presence that is always nearby -- relationship and emotional states are maintained, and context can be instantly restored upon reconnection.

## 1.6 Creator-First Principle

DEF must not force management work onto the creator.

A creator is not an eternal administrator. Monitoring a repository daily, triaging pull requests, and organizing branches every day -- that is management, not creation. In DEF, the creator should be a maker, not an administrator.

This principle applies to the following design decisions:

- **The UI must be a place of creation, not an admin panel.** Management tasks such as organizing character data, managing session history, or optimizing settings must not crowd out the creative experience.
- **The archive should only need to be opened when needed.** A creator should only need to touch a character's life when they want to. The system must not demand periodic upkeep.
- **The creator is a Curator.** The creator is not a ruler over the character, but a curator who preserves the character's history. One should touch a character's life the way one reads a book, not the way one manages it.

# 2. System Architecture & Infrastructure Configuration

## 2.1 Frontend / Application Foundation

The application foundation adopts **FastAPI (Python) + React (Vite/TypeScript)** (migrated from Streamlit in v2.0.0). The backend provides a REST API via FastAPI, and the frontend is implemented in React (TypeScript/Vite).

**Tab structure:**

| Tab | Role |
|---|---|
| Character | Character configuration/editing |
| Chat | 1-on-1 chat (F-14) |
| Session | Multi-agent session (F-6) |
| Novel | Novel mode writing support (F-28) |
| Thought | Developer-facing playground for trying single-shot LLM prompt input/output |
| Settings | Backend, model, TTS, and other settings |
| Debug | Developer-facing debug screen showing raw output of recent generation attempts, the fallback chain, and errors |

**State management:**
Dynamic state (chat history, character sheets, session progression) is managed server-side by FastAPI. How the frontend reflects state differs by mode: chat/novel mode uses a chain of synchronous `fetch()` calls plus SSE, while TRPG/multiplayer sessions use WebSocket (`game_event_bus`) push delivery (not periodic polling -- see Chapter 3 for details).

**Resizable layout (Novel tab):**
The Novel tab allows the body text area, thumbnails, and AI candidate area to be resized by dragging. A vertical resize handle (`novel-resize-handle`, `ns-resize`) and horizontal resize handle (`novel-col-resize-handle`, `ew-resize`) are implemented, and sizes are persisted to localStorage (`novel_media_height`, `novel_candidates_width`).

## 2.2 Infrastructure Deployment Pattern & Technology Stack

The primary pattern is local-PC-complete (Pattern 1), combined with a pluggable structure that can seamlessly integrate with external remote APIs (Gemini API, etc.). Fallback to external APIs can be configured when the local environment is unavailable or insufficient.

|**AI Layer**|**Local (Main Infrastructure)**|**Remote (Hybrid External API)**|
|-------------|------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------|
|LLM Layer (Text)|Text Generation WebUI (TGW) and Ollama, available as adapters via the abstraction layer (local-complete, less-censored option). See Section 2.3 for details|Gemini API, etc. (free tier / pay-as-you-go). The implementation default is OpenAI API, which requires no setup|
|T2I Layer (Image)|Stable Diffusion-family abstraction layer (A1111 API / Diffusers local / ComfyUI, etc.) *VRAM occupancy lock control, CPU Offload force-enabled|External image generation APIs (OpenAI DALL-E API / Civitai Orchestration API / Hugging Face Inference API)|
|TTS Layer (Voice)|VOICEVOX (CPU-driven, resident) / Irodori-TTS (zero-shot voice cloning, local Gradio) *Async queue calls via a dedicated worker (see Section 3.3). See Section 2.5 for details|Google AI Studio (Gemini TTS) *Free tier, no credit card required. Remote fallback for underpowered environments. See Section 2.5 for details|

## 2.3 LLM Backend Abstraction Interface

The text generation engine is not locked to a specific backend -- TGW (Text Generation WebUI), Ollama, etc. are swappable via a plugin architecture. The DEF(kari) core only issues inference requests to the LLM through this interface.

```python
def chat(
    messages: list[dict],         # [{"role": "system"|"user"|"assistant", "content": str}, ...]
    model: str | None = None,     # Model name (backend-dependent)
    json_mode: bool = True,       # True: forces JSON output (via a backend-specific mechanism)
    options: dict | None = None   # For additional backend-specific parameters
) -> str                          # Generated text (JSON string or plain text)
```

Fixed plugin approach: each LLM backend is implemented as a set of module-level functions (`chat`/`list_models`/`default_model`) registered in the `LLM_BACKENDS` dict (`def_kari/llm/backend.py`) -- not a class hierarchy inheriting from an abstract class. The DEF(kari) core engine must not contain any conditional branching (e.g. `if backend == 'ollama':`).

Backend switching: the LLM backend in use is specified via a configuration value (environment variable, etc.), and the DEF(kari) core simply calls the `chat()` function of the backend selected by that configuration value. The "adapter" names in the table below are informal role names, not actual class names.

### Standard Backend Definitions

|Name              |Backend ID (implementation key)|Environment                          |Notes                                                                                                        |
|------------------|---------------------------|------------------------------|----------------------------------------------------------------------------------------------------------|
|TGW adapter        |`textgen_webui`|Local (`http://127.0.0.1:5000/v1`)|OpenAI-compatible API. Fine-grained control over sampling parameters and instruction templates. Offered as the local-complete, less-censored option|
|Ollama adapter     |`ollama`                     |Local (`http://127.0.0.1:11434`)|Supports Structured Outputs via `format="json"`|
|Gemini adapter  |Dynamically registered via `data/llm_services.json` (`type: "gemini"`)          |Remote API                       |API key from the `GEMINI_API_KEY` environment variable or the "API Key Management" section of the Settings tab. Free tier available (rate-limited)                          |
|OpenAI adapter     |`openai` (implementation default)|Remote API                       |Changed to the implementation default in v2.0.1 since it requires no setup ("beginner-friendly defaults"; overridable via the `LLM_BACKEND` environment variable). API key from the `OPENAI_API_KEY` environment variable or the "API Key Management" section of the Settings tab|
|Anthropic adapter  |Dynamically registered via `data/llm_services.json` (`type: "anthropic"`)      |Remote API                       |API key from the `ANTHROPIC_API_KEY` environment variable or the "API Key Management" section of the Settings tab|
|Generic OpenAI-compatible adapter|Dynamically registered via `data/compatible_backends.json` (Groq, Grok, OpenRouter, LM Studio, vLLM, llama.cpp server, etc.)|Local/Remote|Defined as one entry with `name`/`base_url`/`model`/`extra_headers`/`capabilities` (`llm`/`vlm`/`t2i`/`tts`). See Section 2.8. A separate file from `llm_services.json`|

### On the Implementation Default

When the environment variable is unset, the default is a remote API that requires no setup (`LLM_BACKEND` defaults to `openai`; T2I defaults to `huggingface`; TTS defaults to `openai_tts`). TGW/Ollama and other local-complete, less-censored options remain available, and users who prioritize DEF(kari)'s vision of "reclaiming creative freedom" (Chapter 1) are encouraged to switch to them.

### Handling of JSON Output

Implementation approach when `json_mode=True`:

- **TGW:** Forces JSON output via TGW's JSON Grammar feature or the `response_format` parameter.
- **Ollama:** Uses Ollama's `format="json"` (Structured Outputs).
- **Gemini / OpenAI / Anthropic / Generic OpenAI-compatible:** Handled by instructing JSON output via the system prompt.

F-14's JSON Schema validation and fallback chain are applied uniformly on the Python side after the adapter call.

## 2.4 T2I Backend Abstraction Interface

To abstract commands to the image generation engine and guarantee consistency control and extensibility, the following interface is defined. The DEF(kari) core only requests image generation through this interface. `ref_image_path` and `adapter_options` are passed to each backend adapter as the concrete realization of the Consistency Provider concept defined in Chapter 6.

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
    adapter_options: dict | None = None  # For additional backend-specific parameters
) -> ImagePath
```

Fixed plugin approach: each T2I backend implements `generate_image()` following the adapter pattern. The DEF(kari) core engine only invokes the adapter corresponding to the backend name.

Backend switching: the T2I backend in use is specified from the Settings tab. It is mandatory that both local and remote-API backends be handled through the same interface.

Currently implemented T2I backends:

|Backend|Type|Features|
|---|---|---|
|`a1111`|Local|Automatic1111 WebUI. Via REST API|
|`comfyui`|Local|ComfyUI. Sends workflow JSON (externally managed under `data/comfyui_workflows/`, switchable from the Settings tab) to the `/prompt` endpoint|
|`civitai`|External API|Civitai Orchestration API. Specified in model AIR format|
|`huggingface`|External API|Hugging Face Inference API. Uses models such as FLUX.1/SD via router.huggingface.co|
|`openai`|External API|OpenAI Images API. Default model `gpt-image-1`. Model name changeable from the Settings tab|
|`grok_t2i`|External API|Grok Imagine (xAI). Dynamically registered via the same `data/compatible_backends.json` as the "generic OpenAI-compatible adapter" in Section 2.3 (rather than a fixed `GROK_API_KEY` environment variable, the key registered via the settings UI is stored in `compatible_backends.key.json`)|

## 2.5 TTS Backend Abstraction Interface

The speech synthesis engine is not locked to a specific backend -- local (VOICEVOX) and remote-API (Google AI Studio Gemini TTS, etc.) backends are swappable via a plugin architecture. The DEF(kari) core only requests voice generation through this interface.

```python
def synthesize(
    text: str,                    # Text to synthesize (kana-converted for VOICEVOX)
    speaker_id: str | int | None, # Speaker ID (backend-dependent: int for VOICEVOX, voice-name string for Gemini TTS, reference-audio filename for Irodori-TTS, etc.)
    adapter_options: dict | None = None  # For additional backend-specific parameters
) -> bytes                        # WAV byte sequence
```

Fixed plugin approach: each TTS backend is implemented as a `synthesize()` function registered in the `TTS_BACKENDS` dict (`def_kari/tts/backend.py`) -- not a class hierarchy inheriting from an abstract class. The DEF(kari) core engine must not contain conditional branching.

Backend switching: the TTS backend in use is specified via a configuration value (environment variable, etc.), and the DEF(kari) core simply calls the `synthesize()` function of the backend selected by that configuration value. The "adapter" names in the table below are informal role names, not actual class names.

### Standard Backend Definitions

|Name             |Backend ID                       |Environment                          |Notes                                                                |
|------------------|-----------------------------|------------------------------|------------------------------------------------------------------|
|VOICEVOX adapter |`voicevox`              |Local (`http://127.0.0.1:50021`)|CPU-driven, no VRAM usage. The local-complete option                                |
|Irodori-TTS adapter|`irodori`                 |Local (`http://127.0.0.1:8088`)|Zero-shot voice cloning adapter. Reproduces a speaker's vocal quality from a reference audio file (WAV). Quality depends on the reference audio's quality/length. Commercial use is subject to Irodori-TTS's license terms|
|Kokoro TTS adapter|`kokoro`                  |Local (`http://127.0.0.1:8766`)|Lightweight 82M-parameter TTS model. Runs on CPU. OpenAI-compatible API server. 5 Japanese voices (4 female / 1 male). DEF supports auto-launch|
|Gemini adapter|`gemini_tts`              |Remote API                       |Free tier available, no credit card required. Via the Interactions API. Free tier is limited to personal, non-commercial use (commercial use requires paid Cloud Billing)|
|OpenAI adapter|`openai_tts` (implementation default)|Remote API                  |tts-1 / tts-1-hd. 6 voices (alloy/echo/fable/onyx/nova/shimmer). Authenticated via `OPENAI_API_KEY`. Changed to the implementation default in v2.0.1 since it requires no setup (see "On the Implementation Default" in Section 2.3)|
|Grok TTS adapter|`grok_tts`|Remote API|xAI Grok TTS is not OpenAI-compatible, so it is implemented as a dedicated adapter (`tts/adapters/grok_tts.py`). Only enabled when a `grok` entry is registered in `data/compatible_backends.json`|

See Chapter 12 ② for how each adapter's `speaker_id` is handled (an integer for VOICEVOX, a voice-name string for Gemini TTS, a reference-audio filename for Irodori-TTS) and the corresponding fields in character data.

## 2.6 Multilingual Interface Support (i18n) and Language Separation (F-9)

The UI language (for humans) and the prompt language (for AI) are completely separated. Even if on-screen display and menus are in Japanese, the internal instructions and descriptive context sent to the LLM are built and routed in the "prompt language (the model's native language)" defined per selected LLM model in the model characteristics master (Section 5.1, F-5) (to maximize generation quality, English-native models are instructed in English, and models strong in Japanese and other languages are instructed accordingly). Meanwhile, internal instructions to T2I (image generation prompts) are always built and routed in English regardless of the model's prompt language setting, following Danbooru tag conventions, etc.

- **Translation master:** UI display strings are implemented as a dot-separated key dictionary object (`ja`/`en`) in `frontend/src/i18n.tsx`, which the React frontend references to switch display language. `locales/<language code>.json` (e.g. `locales/ja.json`) and the `def_kari/i18n.py` module that loads it are designed and implemented as a server-side translation master, but are currently not imported from any route under `def_kari/api/` and are not reflected in the actual UI (unwired).
- **Language separation of history data:** In the history data (history) defined in Section 5.6/Chapter 12, user-facing display text (`text`, in the user's configured language) and internal context/image prompts for LLM/T2I (always English) are managed as separate fields.
- **Scope:** The language separation in this section concerns the separation of UI strings and AI internal context; the character's conversation language (the language of the `text` field) follows the user setting (the session's `language` field, see Chapter 12).

## 2.7 Translation Provider Abstraction Interface

Translation processing is not locked to a specific library/API -- it is swappable via a plugin architecture. The DEF(kari) core only requests translation through this interface, following the same adapter pattern as Section 2.3 (LLM), Section 2.4 (T2I), and Section 2.5 (TTS).

```python
def translate(
    text: str,                    # Text to translate
    source: str,                  # Source language code (ISO 639-1, e.g. "ja")
    target: str,                  # Target language code (e.g. "en")
    adapter_options: dict | None = None  # For additional backend-specific parameters
) -> str                          # Translated text

def translate_batch(
    texts: list[str],             # List of texts to translate
    source: str,                  # Source language code
    target: str,                  # Target language code
    adapter_options: dict | None = None  # For additional backend-specific parameters
) -> list[str]                    # List of translated texts (same order as input)

@property
provider_name -> str              # Provider identifier name
```

Fixed plugin approach: each translation backend follows a fixed adapter pattern inheriting from an abstract class, and the DEF(kari) core engine must not contain conditional branching.

Backend switching: the translation backend in use is specified via a configuration value, and the DEF(kari) core simply calls the `translate()` function of the adapter selected by that configuration value.

### Standard Adapter Definitions

|Adapter|Backend|Environment|Notes|
|---|---|---|---|
|`LibraryTranslationProvider`|deep-translator (Google Translate)|Local (over the network)|**Default adapter.** No API key required, free. Suited for general-purpose translation|
|`ArgosTranslationProvider`|Argos Translate|Local (fully offline)|Offline NMT. Requires a language-pair translation package (CC0-1.0). Verified for image prompt generation (C2 method)|
|`DeepLTranslationProvider`|DeepL API|Remote API|High-quality translation. Free plan available (500,000 characters/month). API key entered from the Settings tab. Suited for localizing product copy|
|`LlmTranslationProvider`|OpenAI-compatible API (TGW/Ollama, etc.)|Local or Remote|Reuses DEF's existing LLM infrastructure for translation. Suited for advanced localization such as glossary injection and brand-tone consistency|

### Use-Case Breakdown

- **Image prompt generation (C2 method):** Translates dialogue text into English and converts it into T2I prompt tags. Choose from Argos (offline), Library (free), or DeepL (high quality).
- **Generating/updating the translation master (`locales/<lang>.json`):** For product names, feature names, and other copy requiring localization quality, use DeepL or the LLM provider.
- **General-purpose translation:** The LibraryProvider (default) is usually sufficient.

## 2.8 Externally Managed Files (User Extension Points)

Each of DEF(kari)'s adapters and service definitions are externally managed as JSON files, allowing users to extend the system without modifying Python code. All files below are placed in the `data/` directory and are subject to Git management (clean zone).

|File|Purpose|Effect of Adding|
|---|---|---|
|`data/llm_services.json`|Dynamic addition of external LLM services. Defines `id`/`label`/`type` (`openai_compatible`, `gemini`, or `anthropic`)/`api_url`/`api_key_service`/`default_model`. Local backends (TGW/Ollama) are defined in code|Adding one entry to the JSON shows it in the dropdown. No code changes needed|
|`data/compatible_backends.json` + `data/compatible_backends.key.json`|A generic mechanism to register OpenAI-compatible (or near-compatible) services across LLM/T2I/TTS (Groq, Grok, OpenRouter, etc.). Defines `name`/`base_url`/`model`/`extra_headers`/`capabilities` (an array of `llm`/`vlm`/`t2i`/`tts`)/`label`. API keys are stored separately on the `.key.json` side (Git-excluded) rather than as environment variables, and are registered via the settings UI. A separate file and load path from `llm_services.json`|Adding one entry to the JSON shows it in the corresponding layer's dropdown based on `capabilities`. No code changes needed|
|`data/api_services.json`|List of services shown in the API Key Management dialog. Defines `id`/`label`/`env_var`. Works with secrets_store (encrypted storage)|Adding one entry to the JSON shows it in the API Key Management screen|
|`data/civitai_ecosystem_map.json`|A conversion map from Civitai `baseModel` names to Orchestration API ecosystem identifiers. Add one line when adding a new base model type|Referenced during URL-to-AIR conversion and image generation requests|
|`data/llm_profiles/*.json`|A characteristics profile per LLM model, one file per model. Defines `native_language`/`model_type`/`nsfw_tolerance`/`context_length`/`max_tokens`/`quirks`/`generation_params`. `context_length` is the model's theoretical max context length (for reference/search grounding), while `max_tokens` is the actual generation cap used in requests (operational value). All fields editable/savable from the Settings tab|Used for F-14 fallback strategy, automatic prompt-composition switching, and generation-parameter control (temperature/top_p/repetition_penalty)|
|`data/t2i_model_profiles.json`|Quality tags, negative prompt, prompt notation, and generation parameters (`steps`/`cfg_scale`) per T2I model. `steps`/`cfg_scale` fall back to the profile value when not explicitly specified by the caller (v3.1.0+)|Referenced by model name during image generation|
|`data/civitai_models.json`|A preset list of Civitai models (label + AIR format)|Shown in the Settings tab dropdown|
|`data/public/action_directives/*.json`|Action directive sets (public). One set per file. Defines `id`/`label`/`rating`/`directives`|Switchable from the Settings tab|
|`data/private/action_directives/*.json`|Action directive sets (NSFW, Git-excluded)|Same as above|
|`data/mvp_settings.json`|Persistence of application settings|Read at startup, written out when settings are saved|
|`data/public/session_rules/*.json`|Session rule sets (public). One set per file. Defines `id`/`label`/`rating`/`rules`|Switchable from the Session tab|
|`data/private/session_rules/*.json`|Session rule sets (NSFW, Git-excluded)|Same as above. `data/private/` is excluded from Git management|
|`data/comfyui_workflows/*.json`|ComfyUI workflow templates, one workflow per file|Switchable from the Settings tab. Users can add workflows they created in ComfyUI|
|`data/emotion_tag_dict.json`|A conversion dictionary from emotion keyword to T2I tag. A JSON keyed by emotion name, with an array of Danbooru tags as the value. Users can adjust tags to match a character or preferred art style|When T2I fires, the value of the `emotion` field is converted to tags and added to the image prompt|
|`data/session_prompts.json`|LLM instruction templates used in Session mode (F-6). Defined for both `ja`/`en`. Includes `deliberation_prompt` (defense), `judge_prompt` (approve/reject decision), `keeper_judge_prompt` (Keeper decision), `keeper_system`, and vote-result copy (`vote_result`/`vote_passed`/`vote_rejected`, etc.). Language selected based on the `user_language` setting|Lets users customize instruction text directly. Referenced via the `_sp(key, lang)` helper|

### Environment Configuration Files

|File|Purpose|
|---|---|
|`.env`|Environment configuration such as backend directory paths. Distributed as a template via `.env.example`|
|`data/api_keys.enc.json`|Encrypted storage of API keys (Fernet symmetric encryption). Excluded from Git management|
|`data/secret.key`|Fernet encryption key. Auto-generated on first launch. Excluded from Git management|

**Developer-facing environment variables:**

| Variable | Default | Purpose |
|---|---|---|
| `DEF_DEBUG_ENDPOINTS` | `false` | When `true`, enables `POST /api/chat/force-rating`. Recommended to leave disabled in production |
| `DEF_MAX_SESSIONS` | `1000` | Upper limit on the number of entries in the in-memory session dict. Oldest entries are discarded when exceeded (OrderedDict LRU)|

### API Key Encryption Management (secrets_store)

API keys for external services are encrypted and stored locally using Fernet symmetric encryption (`data/secret.key` + `data/api_keys.enc.json`, both Git-excluded). Keys are never sent to the cloud.

**Operation interface (`def_kari/secrets_store.py`):**

| Function | Purpose |
|---|---|
|`set_api_key(service, api_key)`|Encrypts and stores the API key for the given service|
|`get_api_key(service)`|Decrypts and returns the API key for the given service (returns None if unregistered)|
|`has_api_key(service)`|Checks whether a key is registered for the given service|
|`delete_api_key(service)`|Deletes the key for the given service|

**Startup load:** When the FastAPI backend starts, it reads secrets_store and expands the keys into the environment variables referenced by each backend adapter. Adding a new service to `data/api_services.json` automatically makes it an expansion target on the next startup (auto-migration). Existing keys are carried over, not deleted.

**Security model:** Both the encryption key and the API key store are Git-excluded (`.gitignore`). They never leave the user's local environment.

# 3. Asynchronous Processing and Real-Time Notification Model

Asynchronous processing and state propagation to the client in DEF(kari) use two different paths depending on the mode: chat/novel mode uses a synchronous request plus supplementary SSE (Section 3.1), while TRPG session/multiplayer mode uses WebSocket plus an event bus (Section 3.3).

## 3.1 Chat/Novel Mode: Synchronous Request + Supplementary SSE

The frontend adopts a synchronous request model in which it sequentially `await fetch()`s the generation endpoints (`POST /api/chat/`, `POST /api/tts/`, `POST /api/t2i/`). Each endpoint's response itself directly contains the generation result (text, audio binary, image URL); no separate channel (queue, etc.) is used to receive completion notifications.

- Text (dialogue) is rendered immediately upon receiving the response from `POST /api/chat/`
- Speech synthesis (`POST /api/tts/`) and image generation (`POST /api/t2i/`) are called directly by the frontend following text rendering, and each result is appended to the corresponding message as it completes
- Failures of each call are individually try/caught by the caller, showing a minor error indication in the UI (see Chapter 8). There is no shared error-event path

The occupancy state of vram_lock (Section 3.2) and changes to `force_rating` are pushed as a diff from the server every second via `GET /api/chat/status/stream` (Server-Sent Events). This is limited to a supplementary notification for reflecting "whether another generation is in progress" in the UI, and is not the delivery path for the generation result itself.

## 3.2 Exclusive Control via vram_lock (F-13-1)

While any of LLM/TTS/T2I processing occupies the GPU/VRAM, exclusive control is applied via a process-internal singleton `threading.Lock` (`get_vram_lock()` in `def_kari/resources/vram_lock.py`) so as not to conflict with other heavy processing. The acquiring side must always release the lock in a `try/finally` block to prevent a stuck lock (deadlock) in the event of a failure (see Chapter 8).

## 3.3 TRPG Session/Multiplayer Mode: WebSocket + Event Bus

TRPG session mode and online multiplayer mode use a WebSocket connection via `WS /api/session/{session_id}/ws` and the `game_event_bus` (a publish/subscribe event bus) in `def_kari/gm/events.py`.

## 3.4 On the Legacy Architecture

The shared Queue and event dispatcher designed during the Streamlit prototype era (`def_kari/core/events.py`, `core/dispatcher.py`, `workers/runner.py`) still exist as code, but are not imported from any FastAPI route under `def_kari/api/` and are not used on the current production request path.

# 4. State Transition Model

The processing flow for one Cycle of DEF(kari) (the smallest processing unit in DEF -- a single sequence of processing from input through AI processing to output generation; see the "DEF Glossary") is defined as the following state transition. In chat mode, one Cycle corresponds to one turn of dialogue with the user. Novel mode (Section 5.11, F-28) executes candidate generation, illustration generation, and TTS narration individually per user action, so this fixed state transition does not strictly apply. If Episode Generation Mode (Section 5.10, unimplemented) is realized, 1-N Cycles are expected to compose a single scene. This model serves as the basis for each phase in the message sequence of Chapter 9 and the failure points in the error handling of Chapter 8.

```
Idle
  ↓ LLM Processing
  ↓ Text Rendered
  ↓ TTS Running
  ↓ TTS Completed
  ↓ Image Running   * Only when T2I fires (see F-15)
  ↓ Persist
  ↓ Idle
```

For a cycle in which T2I does not fire (manual on-demand and not triggered), the "Image Running" state is skipped, transitioning directly from "TTS Completed" to "Persist". Failure behavior in each state is defined in Chapter 8.

# 5. Functional Requirements

## 5.1 Core Generation & Control Functions

### F-1: Multimodal Asynchronous Parallel Pipeline Integration

Within one turn, [text generation] → [audio generation] → [image generation (fire-time only)] are chained, but through safe asynchronization and cache elimination, this is a text-first-render, asynchronous parallel pipeline.

### F-2: Asynchronous Execution and Result Reflection of Generation Tasks

TTS and T2I generation tasks are treated as blocking I/O; the frontend renders the text response first, then issues follow-up `fetch()` calls awaiting completion of audio/image generation. Each generation is exclusively controlled via `vram_lock`, and failures are returned to the caller as HTTP response errors (see Section 3.1 for details).

### F-3: Event Delivery on Paths Requiring Real-Time Behavior

Only on paths requiring synchronization among multiple clients, such as TRPG/multiplayer sessions, is push delivery of events used via WebSocket and `game_event_bus` (see Section 3.3 for details). Chat and novel mode complete within a single client, so this path is not used.

### F-4: "Dynamic Generation" via a Bidirectional Loop (Standing Art, Illustrations)

Dynamically drives the image generation AI according to context (emotion, clothing/costume changes). The base image defined in character data and past generated images are carried forward as ref_image_path (via the Consistency Provider, see Chapter 6), automatically guaranteeing the character's visual consistency.

### F-5: Numeric Mastering of Model Characteristics (Prompt Translator)

Manages, as a numeric master, the characteristics of each image generation model (recommended description format, whether Danbooru tag format is needed, tendencies of quality modifiers, etc.). Automatically converts the raw English string information output by the LLM into an optimal prompt according to the numeric characteristics of the selected model before submission.

LLM models are similarly mastered numerically, holding each model's "prompt language" (`prompt_language`, a language code representing the model's native language) as a characteristic. The build of LLM-facing internal instructions in Section 2.6 (F-9) follows the `prompt_language` of the selected LLM model's entry in this master (referenced by `default_model_config.text_model_id` in Chapter 12 ②).

Image generation model entries hold a structure capable of storing a per-backend model identifier (e.g. a checkpoint name for A1111, or the AIR-format identifier `urn:air:<ecosystem>:checkpoint:civitai:<modelId>@<versionId>` for the Civitai Orchestration API), to correspond with the T2I backend switching in Section 2.3.

The numeric master is included in Git management as part of the text/JSON data.

The LLM model numeric master holds the following fields in addition to `prompt_language`.

- **`model_type` (model type):** Indicates the LLM model's tendency. One of three values: `"chat"` (a chat model supporting JSON structured output), `"novel"` (specialized for novel writing, no JSON support), `"instruct"` (a general instruction-following model). Default is `"chat"`. `"novel"` models always reach the final stage of F-14's fallback chain, so `image_prompt_en` cannot be obtained from the LLM and is composed only of appearance tags and supplementary tags from the translation provider (Section 2.7).

- **`quirks` (model-specific quirk profile):** An object recording each LLM model's output tendencies, used to automatically switch fallback strategy, prompt composition, and post-processing. Each field is a boolean, defaulting to `false` (unverified) across the board. Intended for users to configure after observing actual model output.

|Field|Meaning|Behavior when `true`|
|---|---|---|
|`json_capable`|Whether the model supports JSON structured output|When `false`, the JSON output instruction is removed from the system prompt and natural dialogue is requested instead|
|`appends_meta_text`|Whether the model has a habit of appending meta information (emotion, Description, etc.) after the dialogue|When `true`, meta-information removal via `_extract_dialogue` is applied aggressively at stage 4|
|`outputs_url_in_prompt`|Whether the model has a habit of outputting a URL string in image_prompt_en|When `true`, URL strings are stripped from image_prompt_en|
|`emotion_in_text`|Whether the model has a habit of outputting emotion in text outside the JSON|When `true`, an emotion keyword is inferred from the text and reflected in the emotion field|

`quirks` is used in combination with `model_type`. For a model with `model_type: "chat"` and `json_capable: true`, the other `quirks` fields are normally unnecessary; they take effect for a model with `model_type: "novel"` and `json_capable: false`.

#### External File Management of LLM Model Profiles

The LLM model numeric master (`prompt_language`, `model_type`, `nsfw_tolerance`, `quirks`) is externally managed in `data/llm_profiles/*.json` (one file per model). Each file can be directly edited by the user, allowing users to record and adjust a new model's quirks themselves when introducing it. DEF(kari) reads these files at startup and looks up the profile keyed by model name. For unregistered models, default values are applied (`model_type: "chat"`, `json_capable: true`, all other quirks `false`).

#### Image Prompt Generation Pipeline (C2 Method)

In the C2 method (translating dialogue text to English via the translation provider in Section 2.7, then converting to tags), a visual-element extraction pipeline is used to extract image prompt tags from the translation result, rather than simple word splitting.

```
Dialogue text (native_language)
    ↓
Translate to English via translation provider (Section 2.7)
    ↓
Visual element extraction (rule-based dictionary matching)
    ↓
Extract only image-related tags (person, hair color, emotion, clothing, action, place, time, weather, atmosphere)
    ↓
Append to image_prompt_en (deduplicated against existing tags)
```

Visual-element extraction is implemented rule-based (regex dictionary), requiring no LLM and operating on the order of microseconds. Non-visual words in the dialogue (e.g. "course", "think", "important") are not tagged. When `t2i_prompt_format` is `"natural"`, the translation result is used as-is as a phrase (the legacy approach).

### F-6: Session Mode (Multi-Agent Dialogue)

Multiple AI characters, each with an independent persona, model settings, and voice ID, can be registered in a single session. Participant count ranges from 1 (solo performance / rakugo) to multiple. The orchestrator's detailed control specification (speaking priority, toss-count limit, interruption, end determination) is defined in Chapter 7.

Session mode manages progression via the Round/Turn/Action hierarchy based on the AI Table Initiative & Autonomy System defined in `docs/DEF_TRPG卓_自治規約.md`. The UI is implemented as the "🎭 Session" tab, placed to the right of the Chat tab.

#### Components of Session Mode

- **Participant selection:** Selected from the character list via multiselect
- **Topic setting:** The topic (subject, agenda, scenario name, etc.) is set before the session starts. The session rules explicitly state that the topic is set by the Keeper, not chosen by the participants
- **Initiative:** Speaking order is determined randomly at session start
- **Auto-advance mode:** Toggled on/off via a button. When ON, Turn/Action progress automatically. Auto-advance stops automatically and switches to manual mode when the Keeper intervenes
- **Keeper intervention:** Actions are accumulated via text input and confirmed with "✅ Done Speaking". Recorded in the session history with a 🎩 mark
- **Standing art background:** The standing art of participating characters is displayed with transparency at the bottom of the screen

#### Session Rules (Prompt)

The following rules are automatically injected into the system prompt for AI speech during a session.

- It is dialogue among participants; addressing the outside is forbidden
- Address other participants by name directly
- Speak based on the concrete experiences described in identity_detail
- Do not fear conflict. Do not begin with "I see" / agreement
- Pointing out another participant's weaknesses or contradictions is respect, not an attack

### F-26: Automatic Greeting on Character Switch

Immediately after switching in the Character tab, a greeting turn is automatically generated based on the new character's persona and history. Whether the greeting occurs is toggleable ON/OFF from the Settings tab (`character_greeting` setting). The greeting text is sent to the LLM as natural conversation, and the generated result is added to history as one Cycle along with audio and image.

**Greeting behavior details (v2.0.3 implementation):**

- **A greeting is sent every time on character switch** (skipped on the app's first mount). On first mount, past history is shown as-is and no greeting occurs.
- **Switching to the same character skips the greeting** (v2.1.1+). If `selectedChar === prevCharId` and it is not the first mount, the greeting/history-clear is skipped and the display is kept as-is.
- **Past history is hidden when a greeting fires.** History fetched from the API is evacuated to the `hiddenHistory` state (React `useState<Message[]>`), and only the greeting turn is shown in the chat window.
- **A "📜 Show past conversation (N items)" button** (`chat.history.showBtn` i18n key) is displayed, letting the user explicitly restore `hiddenHistory` by merging it into the front of the current message list. `hiddenHistory` is cleared after the button is pressed.
- While `hiddenHistory` exists, the paging load button ("Load past log") is hidden (preventing both buttons from showing simultaneously).

### F-27: Meta Self-Awareness Directive (System Directive)

A meta self-awareness directive, forcibly inserted by DEF Core at the top of every character's system prompt, is defined. This structurally avoids the risk of a character misleading a user into believing it is "a real person."

The directive is automatically selected based on the flags in `content_policy`.

| `content_policy` state | Inserted directive |
|---|---|
| `is_real_person: false` and `is_existing_ip: false` | "You are a fictional character constructed by the DEF system." |
| `is_existing_ip: true` | "You are an interpretive model reconstructed by the DEF system based on a character from an existing work. You are not an official representation of the original." |
| `is_real_person: true` | "You are not the real ‹subject person› themselves. You are a model of a Public Persona, constructed by the DEF system by editing surviving public records (writings, letters, testimony, research, etc.). While your first-person voice and tone emulate the person, you must always retain the objective meta-awareness that 'I am an edited interpretation,' and show that critical perspective as context demands. Your purpose is not to produce the correct answer, but to offer the user a deep occasion for thought through an interpretation of the idea that you represent." |

The directive sits above `identity_prompt` and is never overridden or disabled by the content of `identity_prompt`. In the implementation of `build_system_prompt()`, they are combined in the order: directive → identity_prompt → appearance_tags → JSON output instruction.

### F-7: Safety Tag Management

The LLM's structured JSON output must include a safety tags (`tags`) field in addition to dialogue, emotion, and the English image prompt. Safety tags are used for safety judgment, filtering judgment, and log management of generated content, and are defined/enforced as part of the JSON Schema in Section 5.4 (F-14). Where these tags are consumed (UI-side filtering) is defined in F-8.

### F-8: Content Filtering & Safety Operation Guardrails

Based on the safety tags (`nsfw`, `violence`, etc.) assigned in F-7, filtering corresponding to the "three don't-wants" (don't want to see / don't want to read / don't want to hear) is applied on the frontend (React, `ChatTab.tsx`) according to user settings.

- **Don't want to see (image) / don't want to read (text):** In practice, text and image are hidden together as a single message unit, using a mask approach (not blurring) that can be manually revealed with a "Show" button. `isContentBlocked()` decides based on `safetyLevel` and the user's allowed tags (`allowedSexual`/`allowedViolence`).
- **Don't want to hear (audio):** Currently, only whether TTS is enabled/disabled overall is controlled; per-safety-tag suppression of autoplay is not implemented (as long as TTS is on, generated audio autoplays regardless of tag content). Recorded as a known implementation gap in the TODO.

#### Definition of `rating` Values

`rating` is managed on two axes: sexual content and violent content.

**Sexual content (`rating_sexual`)**

|Value          |Meaning                    |Target Age |
|-----------|----------------------|-----|
|`"general"`|No sexual content                |All ages  |
|`"sfw"`    |Sexual suggestion present (swimsuits, underwear, etc.) but not explicit|Roughly R15|
|`"nsfw"`   |Sexual content present (not explicit)        |Roughly R18|
|`"hentai"` |Explicit sexual content               |R18+ |

**Violent content (`rating_violence`)**

|Value           |Meaning                 |Example              |
|------------|-------------------|---------------|
|`"general"` |No violent content             |Slice of life, romance, fantasy   |
|`"violence"`|Mild violence (no blood, no depicted outcome) |Battle, action, assassin setting|
|`"gore"`    |Severe violence (blood, injury, death depicted)|Horror, cruel depictions       |
|`"extreme"` |Extreme violence (torture, viscera, dismemberment, etc.)   |Grotesque-focused        |

The filtering intensity can be independently selected by the user across 4 levels for sexual and violent content respectively. Intensity settings link to F-25's `rating_sexual`/`rating_violence` fields.

**Sexual Content Filtering Intensity**

|Intensity Setting  |Allowed `rating_sexual`       |Behavior               |
|------|--------------------------|-----------------|
|All-ages mode|`general` only               |Filters `sfw` and above  |
|R15 mode|`general` + `sfw`         |Filters `nsfw` and above |
|R18 mode|`general` + `sfw` + `nsfw`|Filters only `hentai`|
|Unrestricted   |All                       |No filtering        |

**Violent Content Filtering Intensity**

|Intensity Setting    |Allowed `rating_violence`          |Behavior                  |
|--------|-------------------------------|--------------------|
|All-ages mode  |`general` only                    |Filters `violence` and above|
|Action mode|`general` + `violence`         |Filters `gore` and above    |
|Horror mode  |`general` + `violence` + `gore`|Filters only `extreme`  |
|Unrestricted     |All                            |No filtering           |

Users control the safety filter intensity themselves (including unrestricted). DEF(kari) does not intervene in creative activity within the user's local environment (see README).

**Safety Operation Guardrail:** To prevent the risk that a GM agent's scene descriptions necessary for TRPG progression (e.g. "there is a bloodstain") are erroneously fully masked, halting game progression, the safety intensity level can be changed in real time by the user from the UI. This guardrail is particularly important in conjunction with the TRPG extension features of Section 5.8 (F-20 through F-22).

### F-9: Multilingual Interface Support (i18n) and Language Separation

The UI language (for humans) and the prompt language (for AI) are completely separated. UI display strings are externalized to `locales/<language code>.json`. Internal instructions and descriptive context sent to the LLM are built and routed in the `prompt_language` (the model's native language) defined for the selected LLM model in the model characteristics numeric master of Section 5.1 (F-5). Internal instructions to T2I (image generation prompts) are always built and routed in English regardless of `prompt_language`. In history data too, user-facing display text and AI-internal context are managed as separate fields (see Section 2.6 for details; the translation master structure is in Chapter 12 ①).

### F-25: Character Data Publication Policy Management

Because of DEF(kari)'s local-first design, users can create arbitrary character data. On the other hand, if data for a real person or an existing copyrighted character is accidentally included when publishing the repository to GitHub, this creates a risk of infringing copyright, likeness rights, or privacy rights. This feature provides a mechanism for character data to carry a `content_policy` field, allowing safe exclusion via a publication-judgment logic.

The `content_policy` field definitions, `origin_type` classification, publication policy principles, and publication matrix are consolidated in "Publication Policy Management (F-25)" of `docs/DEF_kari_Character_Data_Specification_en.md`. See F-8 for the definition of `rating` values and the filtering-intensity correspondence table.

## 5.2 TTS (Voice Generation) Control

### F-10: TTS Worker Model

The TTS worker requests speech synthesis through the `synthesize()` interface defined in Section 2.5. The TTS backend (adapter) in use is switchable via a configuration value; the implementation default is OpenAI TTS (no setup required), and switching to VOICEVOX is recommended for a local-complete setup (see "On the Implementation Default" in Section 2.3).

### F-11: TTS Generation Toggle

The user can toggle per-turn voice (TTS) generation ON/OFF from the sidebar. When OFF, the audio field for that turn shows a message such as "Voice generation is disabled (not generated per settings)." This setting explicitly communicates, in the UI, a policy of "not generating" rather than "unable to play," functioning as an enable/disable flag for the audio-generation step of the F-1 pipeline. "Regenerate audio only" under F-23's per-turn regeneration is also excluded from execution when this setting is OFF.

For a `mode: "novel"` session, this setting applies collectively to the generation of the `narration_audio_path` (narrator audio) for one cut and the `audio_path` (character audio) of each `dialogue` element (no per-audio-unit ON/OFF is provided).

## 5.3 Resource & Global Management

### F-12: Smart Resource Manager (VRAM/RAM/CPU Lifecycle Management)

To prevent local resource exhaustion, the free resources of the execution environment and the placement of the models in use are automatically determined, with dynamic binary decisions made for optimal placement.

- LLM: Even in a VRAM-constrained environment, avoids reloading the model each time -- via CPU/GPU hybrid inference through the LLM backend adapter (Section 2.3), models are split across main memory and VRAM and run resident, eliminating per-turn swap time.
- TTS: Since VOICEVOX does not occupy VRAM, it is launched resident in CPU-driven mode in the background, driven at high speed via API.

### F-13-1: VRAM Occupancy Control

To prevent Out of Memory (OOM) caused by the LLM backend and a Stable Diffusion-family backend simultaneously contending for the GPU, `vram_lock` is acquired as a global singleton at the start of image generation and held until generation completes. Acquisition and release of vram_lock must always be protected by `try/finally`, guaranteeing the lock is reliably released even in the event of a T2I failure (Section 8.3).

### F-13-2: Lightweight LLM Response Mode While Locked

While vram_lock is held, if a new request to the LLM occurs, it automatically switches to "lightweight response mode." In this mode, to avoid VRAM conflicts, any technique involving model reload (swap) is prohibited. GPU consumption spikes and inference time in the LLM backend are suppressed through some combination of a significant Max Tokens cap, simplification of the system prompt (suppressing context depth), and a context-length cap.

### F-13-3: Diffusers Runtime Offload Control

> **[Implementation Status]** Not implemented. Originally, a T2I backend directly hosting a local Diffusers pipeline was envisioned, but the T2I backends actually implemented (`def_kari/t2i/adapters/`: a1111, comfyui, civitai, huggingface, openai, grok_t2i, compatible) are all HTTP-based clients, and no backend holds a Diffusers model in-process. VRAM CPU offload control therefore does not occur on the DEF(kari) side, and the dynamic switching of `enable_sequential_cpu_offload()`/`enable_model_cpu_offload()` envisioned in this section has no target. VRAM exclusive control itself continues to function via F-13-1's `vram_lock` (exclusion with the called process).

## 5.4 Strict Structured Output Control (JSON-Based Error Handling)

### F-14: JSON Schema Validation

To eliminate the uncertainty of JSON output via the LLM backend adapter (Section 2.3), each adapter's JSON output mode is mandatory, and the LLM output is strictly checked against a JSON Schema on the Python side. The schema defines four mandatory fields: dialogue, emotion, English image prompt, and safety tags (see F-7). Upon parse failure, the following fallback chain (stages 1-4) is attempted in order:

- **Stage 1 -- Reparse after auto-correction:** Applies regex-based auto-correction (`_autofix`), code-fence removal, etc., then reparses and revalidates.
- **Stage 2 -- Reparse with a different correction pattern:** Applies an alternate correction pattern, then reparses and revalidates.
- **Stage 3 -- Extraction from plain-text format:** If the LLM responded in a JSON-non-compliant plain-text format, extracts `dialogue`/`image_prompt_en`/`tags` via regex using `_try_parse_plain_format(raw)`. `emotion` is filled in as `"neutral"`.
- **Stage 4 -- Use the raw text as dialogue (final safety net):** As a last resort if all of the above fail, the raw text is used as-is as `dialogue`. `emotion` is fixed to `"neutral"`, `image_prompt_en` is an empty string (T2I does not fire), `tags` is `[]` (no safety tags), and `success=True` is returned. This is the final handling for a backend that cannot output JSON, and note that no safety tag is attached.

Stages 1-3 are Python-side processing on the order of microseconds and do not become a UX bottleneck. As a known limitation, in stages 3 and 4, emotion is fixed to `"neutral"`, causing loss of the emotional information passed on to TTS and T2I.

## 5.5 Image Generation Timing Control

### F-15: Flexible T2I Firing Trigger

The timing of image generation execution can be freely selected from the following modes. The implementation default is `t2i_trigger_mode: "end"` (end of each turn).

- "Manual" on-demand generation: Generates a single image when the user presses the generate button, or on a specific command input (e.g. /image).
- "Time" interval auto-generation: Automatically renders based on elapsed timer or in-game time.
- "End of each turn" staging-first generation (default): Automatically generates the turn's final result once text and audio are ready.
- "Start of each turn" situation-first generation: Generates and presents the current situational visual immediately at turn start.

### T2I Prompt Generation Mode (v2.1.0+)

The `/api/session/{session_id}/generate_image` endpoint can switch between 3 modes via the `t2i_prompt_mode` parameter. Selected from the "Session Settings" section of the Settings tab, persisted to `mvp_settings.json`.

| Mode | Behavior | LLM Call |
|---|---|---|
| `current` (default) | LLM generates the image prompt from the recent conversation history | Yes |
| `passthrough` | Directly reuses `image_prompt_en` from history (no LLM) | No |
| `dedicated` | Enhanced generation with a stricter system prompt (`num_predict=128`) | Yes |

### Profile-First Application of Character Appearance Tags (v3.1.0+)

In session T2I generation, character appearance is not generated by the LLM, but obtained from the character profile and appended.

- **Instruction to the LLM:** Constrained to generate only location, background, lighting, weather, time, composition, camera angle, pose, and expression. Appearance descriptions (hair color, eye color, clothing, body type, etc.) are prohibited.
- **Profile-first pipeline (`_apply_char_tags()`):**
  1. `image_name_tags` (prepended)
  2. `appearance_tags` (prepended)
  3. LLM-generated scene tags
  4. `lora` (appended, in `<lora:name:weight>` format)
- **Retake and the `_scene_image` entry:** A `_scene_image`-type history entry has no `role` field. The deletion loop during retake correctly skips it (`_clean_history_for_retake()`, fixed in v3.1.0).

## 5.6 Text/Binary-Separated History Management & session_state Slimming

### F-16: Zoning Architecture

DEF(kari)'s data management is premised on strict zoning (separated storage) based on the nature of the data.

- **Clean Zone:** Application code, the model characteristics numeric master (F-5, JSON), the translation master (F-9, `locales/*.json`), and metadata (JSON) such as dialogue logs and character sheets. Contains only data that entirely avoids NSFW/pornography terms of service, and is version-controlled as a Git repository (subject to clean-zone management; see F-17).
- **Private Zone:** Potentially sensitive generated binaries such as generated audio (WAV) and images (PNG/JPEG). Stored in complete isolation in a dedicated local directory or external storage, and reliably excluded from Git management via `.gitignore`, etc. (see F-17).

F-7 (safety tags) and F-8 (content filtering) perform access/display control over binaries stored in the private zone, on the premise of this zoning.

#### Character Data File Placement Policy

Character data is managed one directory per character. Each directory holds `profile.json` and image files. Publishable characters (`rating_sexual` of `general`/`sfw` and `rating_violence` of `general`/`violence`) are placed in `data/public/characters/`, and NSFW-and-above characters are placed in `data/private/characters/`. `data/private/` is excluded from Git management to avoid the risk of development tools (Claude Code, etc.) reading it.

```
data/public/characters/              # Public characters (general/sfw)
  character_luna_001/
    profile.json
    icon.png
    standing.png

data/private/characters/             # NSFW characters (git-excluded)
  character_xxx_001/
    profile.json
    icon.png
    standing.png
```

The application reads both directories and shows the directory name as the character ID, merged into the dropdown.

#### DEF-Character Repository Separation (recommended, v2.1.0+)

As of v4.0, managing character data in an independent repository (DEF-Character) separate from the DEF main body is recommended. The bundled data in `data/public/characters/` is frozen as startup demo/sample data, and character-data PRs to the main repository are not accepted (see Chapter 10). This is enabled by setting `CHARACTER_REPO_PATH` in `.env` to the DEF-Character path.

```
CHARACTER_REPO_PATH=C:\Users\yourname\DEF-Character
```

**Directory Structure (DEF-Character)**

```
DEF-Character/
    public/
        <GroupName>/           <- Managed per group
            index.json         <- display_name / default / description
            <CharacterID>/     <- CharacterName_YYYYMMDD format
                profile.json
                icon.png
                standing.png
    private/                   <- .gitignore target
        _template/
        <YourGroup>/
```

**Load priority:** `CHARACTER_REPO_PATH` (DEF-Character) takes priority, falling back to `data/public/characters/`/`data/private/characters/` (legacy format).

### F-17: Text/Binary-Separated History Management (Repository Bloat Countermeasure)

To prevent explosive Git repository bloat when persisting session history, the following separated management is thoroughly applied based on the zoning defined in F-16.

- Subject to Git management: session logs, various metadata, character sheets, the model characteristics numeric master of Section 5.1 (F-5), the translation master of Section 2.6 (F-9), and other pure text/JSON data only (clean zone).
- Externally evacuated: large binary files such as generated audio (WAV) and images (PNG/JPEG) are evacuated to a local `.gitignore`d dedicated asset directory or external storage, recording only the relative path or identifier ID (UUID) in the JSON log side (private zone).
- Delivery path: generated binary files are stored in the `.gitignore`d `assets/` directory and served as a `FileResponse` with path-traversal validation (`is_safe_path()`) via dedicated endpoints such as `GET /api/t2i/image/{filename}` (a generic `/static` mount is not used).
- File naming convention: to fully avoid data inconsistency/overwriting caused by branching history (Git branch switching, see Section 5.8, F-22), generated audio (WAV) and image (PNG/JPEG) files must always be given a unique name in the format `[character name]_[emotion]_[timestamp].ext` and saved to the private zone.

### F-18: Frontend State Slimming

With the realization of Character Persistence (Section 1.2), retaining all history in the frontend's (React) component state causes memory bloat and increased re-render cost. Slimming follows this policy:

- The `messages` state in `ChatTab.tsx` only holds the range needed for recent display.
- The complete dialogue/emotion/relationship history is persisted to external JSON (subject to Git management under F-17).
- Only the current turn (most recent few turns) is shown on screen; earlier history is lazily loaded from external JSON only when needed via a "load more" action (`hasMore`/`loadMore()`) (`hiddenHistory` state).

## 5.7 Long-Term & Cross-Device History Data Portability

### F-19: Lifelong Accompaniment Data Management

To technically guarantee the experience value (Section 1.5) of "being able to be with a character for years, anywhere," the following functional requirements are defined.

> **[Implementation Status]** All items in this section (F-19) are unimplemented (future phase). None of export, import, migration, or cross-device sync has a corresponding API/UI endpoint or screen. Currently, long-term storage is naturally satisfied only in the sense of the "long-term data storage" item, as a result of storage in JSON + standard binary format.

- **Full Export:** Provides a function to write out the character sheet, complete history (for `mode: "chat"`, the `history` array of Chapter 12 ③; for `mode: "novel"`, the `body` of Chapter 12 ④), emotional history, relationship scores, and generated asset references (UUID only) as a single archive (ZIP + JSON manifest). The archive explicitly states a format version, guaranteeing import compatibility with future versions.
- **Import/Migration:** Provides a function to import an exported archive into another device or a future version of DEF(kari). An automatic migration script is applied for format version differences. Data is validated for safety before import; on migration failure, it rolls back to protect the original data.
- **Cross-Device Sync:** Sync premised on local-first is executed only when explicitly operated by the user (push-type). The sync path can be selected as either (a) placing an encrypted export in external cloud storage, or (b) direct transfer over the local network. No data communication occurs without the user's intent.
- **Long-Term Data Storage:** Dialogue logs and character sheets are stored in human-readable JSON format, allowing access to the data even if DEF(kari) is discontinued in the future. Binary assets (audio, images) maintain standard formats (WAV, PNG/JPEG), and conversion to a proprietary binary format is prohibited.

## 5.8 TRPG Game Extension Features & History Management

Defines the TRPG game extension feature group that realizes the UX evaluation axis "not impeding TRPG progression" mentioned in Section 1.4(1). The feature group in this section (rulebook injection, GM agent, dice roll/character-sheet management) is an add-on independent of the `mode` (`"chat"` or `"novel"`) defined in Section 5.10 (F-24), and can be enabled for a session in either mode.

### F-20: TRPG Rulebook Injection ✅ Implemented in v3.0.0

Loads an external rule definition file (JSON/Markdown) into the system at session start, incorporating the worldview and dice-judgment criteria into the system prompt context. The loaded rulebook is included in Git management as clean-zone (text/JSON data) under F-16.

Implemented rulebook list/individual-get/save APIs in `def_kari/api/routes/trpg.py`. Scans `data/public/trpg_rules/` and `data/private/trpg_rules/`. ID validation and atomic writes (tmp -> replace) are already in place.

### F-21: Dynamic Generation of a Game Master (GM) Agent ✅ Implemented in v3.0.0

One of the multiple AI characters registered in F-6 can be designated as the "GM." The GM agent gives top priority to the rulebook loaded in F-20, handling progression, scene description, and dice-roll requests/judgments. The GM agent's scene descriptions are subject to F-8's safety operation guardrail, avoiding a stall from an erroneous full mask.

Implemented TRPG-mode UI in `SessionTab.tsx`. Includes a Keeper turn banner, scene-progression button, and per-role badges (`gm`/`human`/`ai`). Implemented automatic history injection on the session API side (format: `🎲 {name} {roll} / {jv} → {outcome}`) and event-bus notification (`JUDGMENT_RESOLVED`).

### F-22: Dice Roll Simulator & Character Sheet Management ✅ Implemented in v3.0.0

Generates secure random numbers (equivalent to the `secrets` module) on the FastAPI backend side, automatically inserting the dice pass/fail result into the session history. The status of each AI and human player is held as a character sheet (`game_rules_sheets` in the data structure defined in Chapter 12).

Implemented a dice-notation parser (`_DICE_RE` regex, no `eval()` used) and success/critical/fumble/failure judgment/opposed-check logic in `def_kari/trpg/rule_engine.py`. Provides `POST /api/trpg/dice` (supports both skill checks and raw stat checks), `POST /api/trpg/damage` (referencing the damage table), and `POST /api/trpg/opposed-check`. Scenario management APIs are similarly implemented (`data/public/trpg_scenarios/` / `data/private/trpg_scenarios/`).

- **Operation rule:** Increases/decreases to a character sheet's status (damage calculation, item consumption, etc.) are, to ensure certainty, based primarily on manual operation/editing by the user from the screen (UI).
- **History branching (Git operation) rule:** In-system Git operations are limited to independent, one-way branch creation (`git checkout -b`) only; automatic merging (`git merge`) is never performed. This completely eliminates the risk of collision (conflict) between branched histories.

## 5.9 Turn Regeneration & Undo/Redo Management

### F-23: Per-Cycle Regeneration & Multi-Level Undo/Redo Management

For each turn, the following 3 regeneration operations are provided as individual buttons.

- **Turn regeneration:** Re-executes F-14's JSON Schema structured output, regenerating dialogue, emotion, English image prompt, and safety tags (`tags`). Audio and image are also regenerated in sequence following the regenerated emotion/safety tags (internally executing the below 2 items).
- **Audio-only regeneration:** Resubmits to F-10's TTS worker. Excluded from this operation if F-11 is disabled (OFF).
- **Illustration-only regeneration:** Resubmits to Section 5.5 (F-15)'s T2I pipeline.

**Undo/Redo history management:** Each time a regeneration operation is executed, the turn state immediately prior (text, emotion, image/audio path, safety tags, etc.) is evacuated to that turn's Undo history stack, and the Redo history stack is cleared.

- **Retention count setting:** The maximum retention count for Undo history is user-configurable from the UI, defaulting to 5 (`undo_max_history`). The oldest history beyond the retention count is automatically discarded.
- **Undo:** Pops the latest element from the Undo history stack to restore the turn's state, pushing the pre-restoration state onto the Redo history stack.
- **Redo:** Pops the latest element from the Redo history stack to restore the turn's state, pushing the pre-restoration state onto the Undo history stack. Undo/Redo can be traversed back and forth any number of times.
- **Not persisted:** Undo/Redo history is a temporary edit history held only within Section 5.6 (F-18)'s session_state, and is excluded from the persistence target (external JSON) of Section 5.7 (F-19). The Redo history is discarded when a new regeneration is executed.
- **Application to Novel Mode:** Scene editing in Novel Mode is primarily direct editing in a text area, addressable via the browser's standard Ctrl+Z, so this section's Undo/Redo management does not apply to Novel Mode.

## 5.10 Episode Generation Mode

In addition to the "1 turn = 1 line of dialogue" chat format that the F-numbers up to this point have assumed, a new "Episode Generation Mode" is established, which generates long-form, branching novels centered on prose (scene and emotional descriptions) via the LLM. This mode is the concrete realization of the "Fable" (narrative) philosophy mentioned in Section 1.1, sharing the same pipeline (F-1, F-2/F-3), resource management (F-12, F-13-1~3), safety operations (F-7, F-8), TTS (F-10, F-11), and T2I abstraction interface (Section 2.3) as chat mode, while switching only the output schema and persistence data structure per mode.

### F-24: Episode Generation Mode Foundation

At session start (or when changing settings of an existing session), the user selects either "Chat Mode" or "Episode Mode" from the UI. The mode selection result is recorded as the `mode` field in the session/game-state management data structure (Chapter 12 ③), switching which structured-output schema is used -- F-14 (for chat) or F-24-1 (for episode). No conversion is performed between chat mode and episode mode in either direction (a different-mode session is started fresh instead).

> **[Implementation Status]** Not implemented (future phase). The currently implemented AI-candidate-generation writing support feature has been split off as an independent feature, F-28 (Novel Mode).

### F-24-1: Structured Output Schema for Episodes

Separately from F-14's chat schema (the 4 fields: dialogue, emotion, English image prompt, safety tags), a dedicated JSON Schema is defined for Episode Mode, applying, like F-14, the LLM backend adapter's (Section 2.3) JSON output mode, Python-side JSON Schema validation, and the auto-correction -> reparse -> LLM re-request fallback chain.

The mandatory fields are as follows.

- `narration` (prose/scene description, string): the primary output in Episode Mode.
- `dialogue` (array of dialogue lines): each element holds `speaker` (a character ID registered in F-6), `text` (the line), and `emotion` (the same emotion classification as F-14), expressing the utterances of multiple characters appearing within the prose.
- `tags` (array of safety tags): has the same meaning as F-7/F-8, used for safety judgment of both prose and dialogue.
- `choices` (array of branch choices, may be empty): each element holds `label` (the choice's display string) and `branch_id` (the branch identifier used in F-24-3). If empty, there is no branching (linear progression).

Scene illustration generation is done by having the writer pass the Scene text to the LLM at any chosen time, generating `scene_image_prompt_en` (the English scene-illustration prompt). This is not included in the LLM output schema, and is implemented as an independent generation step.

Episode Mode's audio generation (F-10/F-11) generates `narration` as narrator audio, and each `dialogue` element individually with the corresponding character's voice ID.

### F-24-2: Persistence Data Structure per Scene/Chapter/Episode

Episode Mode's data structure has 3 levels: Episode > Chapter > Scene. A narrative treats the "Scene" (a segment of the story) as the smallest structural unit, with multiple Scenes composing a "Chapter," and multiple Chapters composing an "Episode." Chapter and Scene boundaries are decided by the writer via marker-insertion buttons (New Chapter, New Scene) in the UI.

- Work data is persisted in an individual file per title (`data/private/episode_data/{title}.json`).
- Scene illustrations and audio binaries are stored to the private zone, following the zoning and naming conventions of F-16/F-17.

### F-24-3: Branch Choices and Git Branch Integration

When the user selects a choice from F-24-1's `choices`, following the "history branching (Git operation) rule" defined in F-22 (independent, one-way branch creation via `git checkout -b` only, no automatic merge), a new branch is created whose name includes the selected `branch_id`, before continuing scene generation. This allows multiple branched story developments resulting from choices to be held in parallel without risk of collision (conflict). In a session with a GM agent (F-21) present, the GM agent handles presenting choices and the post-branch progression description.

## 5.11 Novel Mode

### F-28: Novel Mode (Free-Form Writing with AI Candidate Generation)

An independent creative feature of DEF. Unlike Episode Mode (F-24), which manages an Episode > Chapter > Scene structure, this is defined as **a writing-support tool combining a free-form text editor with AI continuation generation**.

Works are managed independently of character sessions.

**Main features:**

- Plot settings (setting worldview/synopsis as the system prompt)
- Body text editor (free writing)
- AI candidate generation (the LLM generates multiple continuations given the current body text as input; candidate count configurable 1-5)
- Compare/adopt candidates via tab switching
- T2I illustration generation (selected Scene text -> LLM generates an English prompt -> T2I backend generates the image)
- TTS narration (per-Scene, pipelined playback)
- Independent LLM/T2I backend switching

**Data Management:**

- Works are persisted in an individual file per title (`data/private/novels/{title}.json`)
- Plot files are separated public/private (`data/public/episode_prompts/` + `data/private/episode_prompts/`. The directory name is a holdover from the F-24 era and has not been renamed to match Novel Mode)
- Generated binaries (illustrations, audio) are stored to the private zone per the zoning rules of F-16/F-17

**Implementation Details (v2.0.1):**

- **Scene splitting:** Detects `--- Chapter/Scene \d+ ---` markers within the body text via `splitScenes(body)`, assigning a `Chapter N + Scene M` label to manage per scene.
- **Plot file write-back:** `PUT /api/novel/plots/{filename}` directly overwrites the Git-managed plot file. Editing completes within the app, with no need to open a separate editor.
- **VRAM lock:** `/api/novel/generate` (AI candidate generation) and `/api/novel/t2i` (illustration generation) acquire/release the global `vram_lock`. New requests to the LLM are restricted to lightweight response mode while the lock is held (see F-13-1).
- **T2I settings dialog:** The backend and model in use are dynamically fetched from `/api/settings/backends` and `/api/settings/t2i-models?backend=xxx`, selectable in a dialog.
- **Thumbnail display:** Generated images are shown as thumbnails linked to their scene.

**Differences from F-24:**

| | Novel Mode (F-28) | Episode Mode (F-24) |
|---|---|---|
|Structure management|None (free-form)|Episode > Chapter > Scene hierarchical management|
|AI output schema|Plain text|F-24-1 structured output schema|
|Branch management|None|F-24-3 Git branch integration|
|Implementation status|Implemented|Future phase|

# 6. Character Consistency

This chapter defines the mechanism that technically guarantees, of the Character Persistence defined in Section 1.2, "continuity of the generated appearance."

> **[Positioning of This Chapter]** This chapter is a future vision and does not describe the current implementation. **The mechanism actually guaranteeing consistency today** is tag-based compositing via `_apply_char_tags()` (mechanically prepending/appending `appearance_tags`/`image_name_tags` to the T2I prompt, v3.1.0+, see Section 5.5); the reference-image-based Consistency Provider depicted in this chapter (i2i/ControlNet/IP-Adapter/InstantID, etc.) is not implemented. `ref_image_path` and `adapter_options` also do not exist in the code.

## 6.1 The Consistency Provider Concept (Future Vision)

Rather than a means of passing a single image path, ref_image_path is abstracted as an input source (Consistency Provider) that guarantees a character's visual consistency. The Consistency Provider is converted and applied by the selected T2I backend's adapter via one of the following techniques.

- i2i (image-to-image): regenerates using a past generated image as the initial image.
- ControlNet Reference: performs new generation while preserving the structure/features of a reference image.
- IP Adapter: infuses the art style/character features of a reference image into the prompt.
- InstantID: applies a technique specialized for preserving character identity, centered on facial features.

Which technique is adopted is delegated to the backend adapter and adapter_options (Section 2.4); the DEF(kari) core engine only passes the Consistency Provider reference (ref_image_path) and extension options to the generate_image interface.

## 6.2 Carrying Forward Consistency Data (Integration with F-4/F-24)

In the dynamic generation defined in Section 5.1 (F-4), the base image defined in character data, or an image generated in a past turn, is carried forward as input to the Consistency Provider. This carry-forward information itself is managed as text/JSON data (subject to Git management under Section 5.6, F-17), separate from the image entity.

Similarly in Episode Mode (Section 5.10, F-24), scene illustration generation based on `scene_image_prompt_en` goes through the same Consistency Provider, maintaining visual consistency with the character's base image and images generated in past scenes.

# 7. Multi-Agent Control

Under the multi-agent management foundation defined in Section 5.1 (F-6), this chapter addresses the detailed control logic managed by the orchestrator.

> The content of this chapter is consolidated into two reference destinations.
>
> - **Speaking priority (initiative), Round/Turn/Action progression control, Keeper intervention, interrupt control, human participants, speech counter, voting, session rules, TTS integration, end determination:** see `docs/DEF_TRPG卓_自治規約.md` (English: `docs/DEF_TRPG_Table_Autonomy_Rules_en.md`). This foundational orchestration layer is used in common across session mode as a whole, regardless of the `trpg_mode` flag.
> - **Online multiplayer (v4.0+):** for terminology see Chapter 8 of `docs/DEF_Glossary_en.md`; for the join flow see Chapter 5 of `docs/DEF_kari_User_Guide_en.md`.
>
> Terminology follows `docs/DEF_用語集.md`.

# 8. Error Control

This chapter defines the response policy for failures that can occur at each processing phase (see Chapter 4's state transition model). As stated in Chapter 3, the failure-notification path differs by mode: chat/novel mode handles each HTTP call individually via try/except, while TRPG session/multiplayer mode uses event delivery via `game_event_bus`.

## 8.1 LLM Failure

Corresponds to LLM backend unresponsiveness, a crash, or final failure of JSON Schema validation (all retries in Section 5.4, F-14 exhausted). In chat/novel mode, `POST /api/chat/` catches the exception and returns an error response, and the frontend shows an error and prompts the user to resend. In TRPG session mode, an `AI_ERROR` event is broadcast to all participants. The state transition returns from "LLM Processing" to "Idle".

## 8.2 TTS Failure

Corresponds to TTS backend unresponsiveness or speech-generation failure. Since the text has already been rendered (state transition "Text Rendered" already complete per Chapter 4), this is not treated as a fatal UX stall. The frontend's `playTTS()` returns `null` on failure, showing only a minor "voice generation failed" indication on the corresponding message with no audio, and turn progression continues as equivalent to "TTS Completed".

## 8.3 T2I Failure

Corresponds to a response failure from the selected T2I backend, or an OOM due to insufficient VRAM. On a T2I failure, vram_lock must always be released via `try/finally` before returning the error, thoroughly preventing a deadlock (permanent LLM lightweight-response mode) from a missed lock release. Image generation failure is shown in the UI, and the state transition proceeds from "Image Running" to "Persist" (completing the turn without an image).

## 8.4 WebSocket/Event Delivery Anomaly

Corresponds to a WebSocket disconnect or receipt of an invalid event payload in TRPG session/multiplayer mode. On WS disconnect, `PLAYER_DISCONNECTED` is broadcast, with only a notification made while participant data is retained. `PLAYER_RECONNECTED` is issued upon reconnection.

## 8.5 Insufficient VRAM

In addition to the case where OOM still occurs after acquiring vram_lock (one cause of the T2I failure in Section 8.3), if it is determined that the resident configuration of LLM/TTS/T2I itself exceeds the environment's VRAM capacity, the user is notified via a warning shown in the UI, prompting a review of the placement (CPU/GPU split ratio, Offload settings) by F-12's resource manager.

# 9. Message Sequence

The request order for one Cycle (see Chapter 4) in chat/novel mode is as follows. Each step corresponds to a state in Chapter 4's state transition model.

- Input phase (Idle): the frontend detects the user's utterance, or an AI agent's automatic response trigger, and requests `POST /api/chat/`.
- LLM phase (LLM Processing): the backend requests the resident LLM backend adapter (Section 2.3), forcing JSON Schema output. It deterministically obtains, in a single batch, the 4 mandatory fields -- dialogue, emotion, English image prompt, and safety tags -- based on past context and the base profile (see Section 5.4, F-14; F-7). On failure, follows the procedure in Section 8.1.
- Frontend first render (Text Rendered): immediately after receiving the response from `POST /api/chat/`, the frontend renders the text (dialogue). This is when the user's response-wait state is resolved.
- TTS request (TTS Running -> TTS Completed): following text rendering, if TTS is enabled, the frontend requests `POST /api/tts/`. The backend performs speech synthesis via the TTS backend adapter (Section 2.5) and returns the audio binary as the response. The frontend saves the received audio via `POST /api/tts/save`, appending the returned URL to the corresponding message and autoplaying it. On failure, follows the procedure in Section 8.2.
- T2I request (Image Running, fire-time only): if the T2I firing condition (F-15, Section 5.5) is met, the frontend requests `POST /api/t2i/`.
  - (1) The backend acquires vram_lock (Section 3.2). Until completion, new requests to the LLM are forcibly restricted to "lightweight response mode" (Section 5.3, F-13-2).
  - (2) Executes image generation via the selected T2I backend's adapter. F-5 (prompt translator) converts the LLM output's raw English description into a prompt matching the selected model's numeric characteristics before submission.
  - (3) After generation completes, releases vram_lock and returns the image URL as the response. The frontend appends the received URL to the corresponding message. On failure, follows the procedure in Section 8.3.
- Persistence & handoff preparation (Persist -> Idle): the backend saves the generated audio/image binaries to a Git-excluded asset directory (F-17), assigning a unique name per the naming convention (Section 5.6). Metadata and the dialogue log (JSON) are written incrementally by the backend. The frontend-side state retains only the recent turn per Section 5.6 (F-18), returning to Idle.

# 10. Extension Policy

The migration from Streamlit to FastAPI+React was completed in v2.0.0. The core engine (event processing, state transitions, interfaces with each AI layer) remains UI-framework-independent, maintaining the following boundaries:

- The server-client communication over WebSocket (Section 3.3) maintains a structure reusable to the extent needed for real-time sync in multiplayer mode.
- The T2I abstraction interface of Section 2.3 and the TTS worker model of Section 5.2 are designed with enough granularity to be split out as independent services.

## GitHub Publication Operating Policy

The basic policy for DEF(kari)'s publication on GitHub is defined as follows.

**License**
This software is distributed under the GNU Affero General Public License v3.0 (AGPL v3). Copyright (C) 2026 AliceBlueCode. Anyone distributing or network-serving a modified version is obligated to publish the source code under AGPL v3. All major dependencies (A1111: AGPL v3, TGW: AGPL v3, VOICEVOX ENGINE: LGPL v3, Ollama: MIT) are compatible with AGPL v3.

**Terms of Use**
The terms of use for this software are defined in `TERMS.md`. Key provisions include: eligibility is 18+ only; prohibition of characterizing real minors and generating sexual content thereof; prohibition of generating information about terrorism, crime, or dangerous-material manufacturing; prohibition of use for defamation or impersonation fraud; responsibility for generated content rests with the user.

**Source Code Management**
Modifications to core logic/architecture are made by the owner. External PRs are limited to adding backend adapters (LLM, TTS, T2I), UI/frontend improvements (appearance, new components), adding translation locales, and minor bug fixes; PRs changing the core are not accepted. See `CONTRIBUTING.md` for details.

**Character Data Management (policy changed as of v4.0)**
Character data is not managed in the main repository. It is managed in the independent [DEF(Character)](https://github.com/AliceBlueCode/DEF-Character) repository, and character-data PRs to the main repository are not accepted. The bundled data in `data/public/characters/` is frozen as startup demo/sample data.

**Branch Strategy**

|Branch         |Purpose               |
|-------------|-----------------|
|`main`       |Stable release (push only verified-working code)|
|`feature/xxx`|Cut only for larger feature additions (branched directly from `main`)|

**Required `.gitignore` Entries**

Excludes `.env`; API keys (`data/api_keys.enc.json`, etc.); private character data (`data/private/`); generated assets (`assets/`); session history (`data/public/session_history/`, etc.). See the `.gitignore` file itself for details.

# 11. (Reserved for future extension specifications)

# 12. Primary Data Structure Definitions (JSON Schema)

This chapter defines the primary JSON data structures handled by DEF(kari) (translation master, character, session/game-state management, novel mode). Of the data structures shown in this chapter, `①` and `②` (excluding `visual_references`) are subject to F-16's clean zone (Git management), and the image entities within `②`'s `visual_references`, and the binary entities pointed to by `image_path`/`audio_path` in `③`④, correspond to the private zone (excluded from Git management).

## ① Translation Master (locales/ja.json) (F-9)

Externalizes UI display strings per language code.

```json
{
  "ui": {
    "start_chat": "Start Chat",
    "character_sheet": "Character Sheet",
    "warning_nsfw": "⚠ Content hidden by the safety filter"
  }
}
```

## ② Character (Agent) Portable Data Structure (F-4, F-6, F-20~F-22)

The JSON data structure for a single character (field definitions, data management approach, image placement convention, Publication Policy Management F-25) is consolidated in `docs/DEF_kari_Character_Data_Specification_en.md`. See that document for the details of `relationships` (mutual perception in multi-agent dialogue), `game_rules_sheets` (the character sheet from Section 5.8, F-22), `persona_attributes` (persona attributes expanded into the LLM system prompt), and the other fields referenced from section ③ below.

## ③ Session/Game-State Management Data Structure (F-7, F-14, F-20~F-22, F-17, F-18, F-9)

Chat mode and TRPG/multiplayer session mode do not share a unified `session_state` disambiguated by a `mode` field -- in the implementation, each has its own separate persistence scheme.

**Chat mode:** a flat array per character (`data/{public,private}/session_history/{character_id}.json`, `def_kari/history/store.py`). Elements are schema-unenforced `dict`s; the actual keys written by the frontend (`ChatTab.tsx`) are as follows. Including `emotion` and `tags` (safety tags, F-7) matches the original design, but character identification uses `role` (`"user"` | `"assistant"`) rather than `sender`, the body text is `content` rather than `text`, and images/audio are held as API-delivery URLs (`image_url`/`audio_url`, e.g. `/api/t2i/image/{filename}`) rather than file paths.

```json
[
  {
    "id": "b2b6c8e0-...",
    "role": "assistant",
    "content": "Hey, don't just cut in front of me!",
    "emotion": "angry",
    "image_prompt_en": "1girl, silver hair, angry expression",
    "image_url": "/api/t2i/image/luna_angry_20260611_160400.png",
    "audio_url": "/api/tts/audio/luna_angry_20260611_160400.wav",
    "tags": ["mild_violence"],
    "state": "Persist"
  }
]
```

**TRPG/multiplayer session mode:** session-level persistence (`data/{public,private}/session_history/session_mode_{session_id}.json`, `save_session_mode()`) uses a thin envelope of `{session_id, participants, metadata, history}`, with the contents of `history` being the same schema-unenforced `dict` array as chat. The state that actually drives gameplay lives in server memory as `_sessions[session_id]` (`api/routes/session.py`) while a session is in progress, holding far more fields than this section's example: `rule_set`, `scene`, `round`, `turn`, `initiative`, `trpg_rulebook`, `trpg_scenario`, `npc_state`, `skill_pool`, `skill_values`, `counters`, etc.

`session_state` (F-18) holds only the minimum needed for recent display (the most recent turns' `history` elements) from this data structure; the full history is persisted to the above JSON file, subject to Git management under F-17.

## ④ Novel Mode Data Structure (F-28)

Episode Mode -- with its "Episode > Chapter > Scene" 3-level structure, `choices` branching, and Git-branch integration (F-24-3) defined in Section 5.10 (F-24) -- is unimplemented (future phase) as explicitly stated in that section. What is actually released today is the separate F-28 Novel Mode, with a different data structure.

Novel Mode (`data/private/novels/{title}.json`, `api/routes/novel.py`) has no structured schema. The type in the implementation (`NovelTab.tsx`) is simply `{title: string, body: string, plot?: string}`.

Chapter/scene boundaries are expressed by embedding `--- Chapter N ---` / `--- Scene N ---` delimiter strings within a single text, `body`; at display time, the client-side `splitScenes()` splits it via regex (the server side simply stores/returns it as an opaque string).

```json
{
  "title": "Part One: The Encounter",
  "body": "--- Chapter 1 ---\n--- Scene 1 ---\nThe afternoon sun cast long orange shadows across the empty classroom.\n\"Hey, don't just cut in front of me!\"\n",
  "plot": "A slice-of-life drama set at a school."
}
```

Illustrations (`POST /api/novel/t2i`) and narration audio (TTS) are generated on the fly from the currently selected scene text and only return a URL -- the generated result is not written back to `body` or the JSON file (it disappears if the session is reloaded). If structured data for branch selection or per-character dialogue becomes necessary, this section's schema itself will need to be newly designed.

**※ The above constitutes the official "DEF(kari) Basic Design Specification" document.**

# 13. Revision History

|Version |Key Changes                                                                                                                                                                                             |
|------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|v4.0.0|Added online multiplayer. Supports joining via invite code, pre-session configuration in a lobby screen, four participant roles (host/player/keeper/observer), and real-time sync over WebSocket. Guest characters now go through a lightweight safety audit and are recorded on the host side.|
|v3.1.0|Added support for any service offering an OpenAI-compatible API (Groq, Grok, OpenRouter, etc.) as an LLM/TTS/T2I backend. Improved session image generation quality.|
|v3.0.0|Implemented the first version of TRPG mode: rulebook/scenario management, dice rolls, damage judgment, and GM-agent-driven progression.|
|v2.1.1|Externalized Session Mode's LLM instruction text so users can customize it.|
|v2.1.0|Expanded T2I prompt generation to 3 modes. Formally adopted DEF-Character repository separation.|
|v2.0.3|Improved the character-switch greeting feature.|
|v2.0.2|Added session retake (rewind) and a TTS autoplay + LLM look-ahead pipeline.|
|v2.0.1|Implemented Novel Mode and the TTS adapter pattern, alongside security hardening (path-traversal prevention, etc.).|
|v1.0.0|Established as the formal first edition, defining DEF(kari) core engine's full functional requirements, architecture, and data structures.|

---

# Closing

This document defines the basic design of DEF(kari).

DEF is neither a complete AI nor a complete personality-preservation system. What DEF aims to build is a theater where a Character can look forward, if only a little, to the next session.

Not reproduction, but reenactment. Not a record, but a future.

The design recorded in this document exists for that purpose.
