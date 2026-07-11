# DEF(kari) User Guide v2.1.1

## 1. Starting the Application

Double-click `start_def.bat`, or run the two commands below in separate terminals:

```bash
# Terminal 1: FastAPI backend
cd E:\tools\DEF
python -m uvicorn def_kari.api.main:app --host 127.0.0.1 --port 8511 --reload

# Terminal 2: React frontend
cd E:\tools\DEF\frontend
npm run dev
```

Open your browser at `http://localhost:3000`.  
(The FastAPI API runs at `http://127.0.0.1:8511`)

---

## 2. Initial Setup

1. Copy `.env.example` to `.env`
2. Set backend directory paths in `.env` (only for the backends you use)
3. Set external API keys from the Settings tab > "🔑 API Key Management" (if needed)
4. Press "💾 Save" at the bottom of the Settings tab

---

## 3. Tab Overview

| Tab | Purpose |
|---|---|
| 👤 Character | View and edit character profiles |
| 💬 Chat | 1-on-1 dialogue |
| 🎭 Session | Multi-AI + human table |
| 📖 Novel | Novel writing + AI candidate generation |
| 🤔 Thought | Free-text AI thought experiments |
| ⚙ Settings | Backends, ratings, and configurations |
| 🐛 Debug | Raw LLM responses and fallback chain inspection |

---

## 4. Chat Tab

### Basic Usage
1. Select a character from the sidebar
2. Type a message and send
3. AI responds with text + voice + image

### Main Buttons
- **🔄 Regenerate** — Regenerate the last response
- **↩ Undo / ↪ Redo** — Undo/Redo
- **🗑 Delete** — Delete the last response

---

## 5. Session Tab

### Starting a Session
1. Select participating characters (multiple allowed)
2. Select session rules
3. Press "▶ Start" to begin

### During a Session
- **Auto-advance checkbox** — AI automatically progresses the conversation
- **Done Speaking** — Complete the AI's turn and advance to the next
- **Interrupt** — Interrupt with Speech Power -2
- **Designate Next Speaker** — Designate the next speaker with Speech Power -1
- **Vote** — Initiate voting for topic change, removal, or session end
- **🎨 Illustration** — Generate an illustration of the current scene

### Human Player
- Add a character with `player_type: "human"` to enable human input mode
- A text input field appears during your turn

---

## 6. Novel Tab

### Basic Usage
1. Select "+ New Work" and enter a title
2. Write in the body text area
3. Press "✍ Generate" to generate AI candidates (based on configured count)
4. Compare candidates using tabs in the right column
5. Press "⬇ Append" to add a chosen candidate to the body
6. Press "💾 Save" to save

### Plot Settings
- Press the "Edit Plot" button to open the dialog
- 📂 to load a plot file, or edit directly
- "💾 Save" saves to the novel JSON
- "✅ Apply" saves + applies as the AI system prompt

### Chapter/Scene
- **New Ch** — Inserts `--- Chapter N ---` + `--- Scene 1 ---` into the body
- **New Sc** — Inserts `--- Scene N ---` into the body

### TTS Narration & T2I Illustration
- **🔊 Current** — Read aloud the last Scene
- **🔊 Select** — Read aloud a Scene chosen from the dropdown
- **🎨 Current** — Generate an illustration for the last Scene
- **🎨 Select** — Generate an illustration for a chosen Scene
- **⚙ T2I** — Switch T2I backend and model

### LLM Backend Switching
- Use the dropdown next to the Plot button to select a novel-specific LLM backend

---

## 7. Settings Tab

### Sections
- **Language** — UI display language (Japanese, English, Chinese, Korean, Spanish, French, German)
- **LLM Backend** — TGW / Ollama / OpenAI / Gemini / Anthropic
- **TTS Backend** — VOICEVOX / Kokoro / Irodori / Gemini TTS / OpenAI TTS
- **T2I Backend** — A1111 / ComfyUI / HuggingFace / Civitai
- **Backend** — Backend status polling interval (`status_poll_sec`, default 5s)
- **C2 Method** — Image prompt translation provider
- **Chat Settings** — Greeting ON/OFF, undo history count
- **Session Settings** — Actions per turn, repeat penalty, illustration size, T2I prompt mode (current/passthrough/dedicated)
- **Novel Settings** — Candidate count, illustration size
- **API Key Management** — Encrypted storage for external API keys

### Saving
Always press "💾 Save" after changing settings. Press F5 (browser reload) to apply saved settings.

---

## 8. Sidebar

- **Character Selection** — Switch chat target
- **Rating Settings** — Sexual/violence tolerance level (4 levels each)
- **Safety Level** — off / warn / mask
- **TTS Settings** — Voice generation ON/OFF, human player voice ON/OFF
- **T2I Trigger** — End of each cycle / Start of each cycle / Manual / Interval
- **D-mode** — Emotion auxiliary tags ON/OFF

---

## 9. Data Layout

```
data/
├── public/              # Public data (git-tracked)
│   ├── characters/      # Public characters (legacy format)
│   ├── action_directives/
│   ├── session_rules/
│   └── episode_prompts/ # Novel plot files (public)
├── private/             # Private data (git-excluded)
│   ├── characters/      # Private characters (legacy format)
│   ├── novels/          # Novel mode work data
│   ├── episode_prompts/ # Novel plot files (NSFW)
│   ├── session_history/
│   ├── session_rules/
│   ├── action_directives/
│   └── thoughts/
├── sessions/            # Session history
├── session_prompts.json # Session LLM instruction templates
└── llm_profiles/        # LLM model profiles
```

### DEF-Character Repository (Recommended)

To manage character data separately from the DEF application, set up a `DEF-Character` repository and configure it in `.env`:

```
CHARACTER_REPO_PATH=C:\Users\yourname\DEF-Character
```

DEF-Character directory structure:

```
DEF-Character/
└── public/
    └── <GroupName>/
        ├── index.json
        └── <CharacterName_YYYYMMDD>/
            ├── profile.json
            ├── icon.png
            └── standing.png
```

---

## 10. Adding Characters

### Using the DEF-Character Repository (Recommended)

1. Create a character directory under `DEF-Character/public/<GroupName>/`
2. Use the format `CharacterName_YYYYMMDD` for the directory name (e.g., `Hanfei_20260611`)
3. Create `profile.json` (use an existing character as a template)
4. Optionally place `icon.png` (512×512) and `standing.png` (832×1216)
5. Reload the app and the character appears in the dropdown

### Placing Directly in data/

1. Create a directory in `data/public/characters/` (or `data/private/characters/`)
2. Place `profile.json`, `icon.png`, and `standing.png`
3. Reload the app and the character appears in the dropdown

---

## 11. Troubleshooting

| Symptom | Solution |
|---|---|
| Backend won't start | Check directory paths in `.env`. Backends with empty paths are skipped |
| Settings reset on F5 | Press "💾 Save" in the Settings tab before reloading |
| No audio playback | Check that TTS is ON in the sidebar |
| No image generation | Check that T2I trigger is not set to "Manual" |
| LLM not responding in your language | Check the language setting in the Settings tab |
| Context limit error | Session history is too long. Start a new session |
