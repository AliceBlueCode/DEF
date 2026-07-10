"""TTSバックエンド切替(基本設計2.5節)"""

import os

from def_kari.tts.adapters import voicevox, irodori, gemini, kokoro, openai_tts

TTS_BACKENDS = {
    "voicevox":   voicevox.synthesize,
    "irodori":    irodori.synthesize,
    "gemini_tts": gemini.synthesize,
    "kokoro":     kokoro.synthesize,
    "openai_tts": openai_tts.synthesize,
}

TTS_BACKEND_LABELS = {
    "voicevox":   "VOICEVOX (ローカル)",
    "irodori":    "Irodori-TTS (ローカル)",
    "gemini_tts": "Gemini TTS API",
    "kokoro":     "Kokoro TTS (ローカル)",
    "openai_tts": "OpenAI TTS API",
}

DEFAULT_TTS_BACKEND = os.environ.get("TTS_BACKEND", "openai_tts")
if DEFAULT_TTS_BACKEND not in TTS_BACKENDS:
    DEFAULT_TTS_BACKEND = "openai_tts"
