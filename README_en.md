# DEF(kari) — Multimodal AI Creative Platform

> **Dialogue × Emotion × Fable**
> With your characters, for years to come, wherever you go.

-----

## What is DEF(kari)?

DEF(kari) is a local-first AI creative platform that integrates text, voice, and image generation.

Rather than entrusting your creative content to the terms of service and content policies of cloud services, DEF(kari) provides the foundation for generating and sustaining the characters and stories you desire, in your own environment, with your own hands.

-----

## Our Stance on Creative Freedom

**Creators are free to create whatever they wish. However, creators bear full responsibility for their creations.**

DEF(kari) is designed based on this principle.

When a tool preemptively intervenes in creative content, it infringes on the creator's freedom of expression. DEF(kari) does not censor or block content for local creative activities.

### Clear Separation of Public and Private

What DEF(kari) protects is the **boundary between public and private**, not the private creative act itself.

**Private (local creation):**
This is the domain where the creator's freedom is fully guaranteed. DEF(kari) does not intervene here at all. The safety filter (F-8) is merely a "display control tool" that users can turn off. It never prevents generation itself. The content and scope of private creation are entirely up to the creator and should not be restricted by the tool.

**Public (publishing to GitHub or external platforms):**
This is the domain where social rules, copyright, and public decency apply. DEF(kari) provides technical support through `content_policy` fields, zoning (F-16), and publication judgment scripts (F-25) to prevent creators from unintentionally publishing private content. However, the final decision to publish or not also rests with the creator.

DEF(kari)'s responsibility as a tool is limited to **providing mechanisms to protect this boundary**. Restricting the freedom of private creation goes against DEF(kari)'s design principles.

All judgment and responsibility regarding creative content, publication, and usage belong to the creator.

-----

## Screenshots

### Chat Mode
![Chat](docs/images/chat.png)

### Session Mode
![Session](docs/images/session.png)

### Episode Mode
![Episode](docs/images/episode.png)

### Character
![Character](docs/images/character.png)

-----

## Key Features

- **3-Modality Integration:** Text, voice, and image work together as a continuous creative experience
- **3 Modes:** Chat (1-on-1 dialogue), Session (multiple AIs + humans at the same table), Episode (novel writing + AI candidate generation)
- **Character Persistence:** Dialogue history, emotions, and generated assets are persisted — resume from where you left off after restart
- **Local-First:** LLM, TTS, and T2I all run locally. Fallback to external APIs is also supported
- **Adapter Pattern:** Freely swap between 4 LLM, 4 TTS, and 4 T2I backends
- **Zoning:** Clear separation of public and private data. Generated assets are excluded from Git

-----

## Requirements

- Python 3.10+
- LLM backend (one or more):
  - [Text Generation WebUI](https://github.com/oobabooga/text-generation-webui) — default
  - [Ollama](https://ollama.com/)
  - OpenAI / Google Gemini / Anthropic Claude API
- TTS backend (one or more):
  - [VOICEVOX](https://voicevox.hiroshiba.jp/) — default
  - [Kokoro TTS](https://github.com/hexgrad/kokoro)
  - Irodori-TTS / Gemini TTS API
- T2I backend (one or more):
  - [Automatic1111 WebUI](https://github.com/AUTOMATIC1111/stable-diffusion-webui) — default
  - [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
  - Hugging Face Inference / Civitai API

-----

## Setup

```bash
git clone https://github.com/AliceBlueCode/DEF.git
cd DEF
pip install -r requirements.txt
cp .env.example .env   # Set backend directory paths, etc.
streamlit run def_kari/app.py
```

-----

## License

This software is distributed under the [GNU Affero General Public License v3.0 (AGPL v3)](https://www.gnu.org/licenses/agpl-3.0.html).

Copyright (C) 2026 AliceBlueCode

- Free to use, modify, and distribute
- If distributing modified versions, you must release the source code under AGPL v3
- If providing modified versions over a network, source code disclosure is also required

> See the `LICENSE` file for details.

-----

## Contributing

See `CONTRIBUTING.md`.

-----

## Terms of Use

See `TERMS.md`. This software is intended for **users aged 18 and above only**.
