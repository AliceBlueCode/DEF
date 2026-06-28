# DEF(kari) User Guide v1.0.0

## 1. Starting the Application

```bash
cd DEF
streamlit run def_kari/app.py
```

Your browser will open `http://localhost:8510`.

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
| 📖 Episode | Novel writing + AI candidate generation |
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

## 6. Episode Tab

### Basic Usage
1. Select "+ New" and enter a title
2. Write in the body text area
3. Press "✍ Generate" to generate AI candidates (based on configured count)
4. Compare candidates using tabs in the right column
5. Press "⬇ Append" to add a chosen candidate to the body
6. Press "💾 Save" to save

### Plot Settings
- Press "📝 Plot" button to open the dialog
- 📂 to load a plot file, or edit directly
- "💾 Save" saves to the episode JSON
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
- Use the dropdown next to the Plot button to select an episode-specific LLM backend

---

## 7. Settings Tab

### Sections
- **Language** — UI display language (Japanese, English, Chinese, Korean, Spanish, French, German)
- **LLM Backend** — TGW / OpenAI / Gemini / Anthropic
- **TTS Backend** — VOICEVOX / Kokoro / Irodori / Gemini TTS
- **T2I Backend** — A1111 / ComfyUI / HuggingFace / Civitai
- **C2 Method** — Image prompt translation provider
- **Chat Mode** — Greeting ON/OFF, undo history count
- **Session Mode** — Actions per turn, repeat penalty, illustration size
- **Episode Mode** — Candidate count, illustration size
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
│   ├── characters/      # Public characters
│   ├── action_directives/
│   ├── session_rules/
│   └── episode_prompts/
├── private/             # Private data (git-excluded)
│   ├── characters/      # NSFW characters
│   ├── episodes/        # Episode works
│   ├── episode_prompts/ # Private plots
│   ├── session_history/
│   ├── session_rules/
│   ├── action_directives/
│   └── thoughts/
└── llm_profiles/        # LLM model profiles
```

---

## 10. Adding Characters

1. Create a new directory in `data/public/characters/` (or `data/private/characters/`)
2. The directory name becomes the character ID (e.g., `character_mychar_001`)
3. Create `profile.json` (use an existing character as a template)
4. Optionally place `icon.png` (512x512) and `standing.png` (832x1216)
5. Reload the app and the character appears in the dropdown

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
