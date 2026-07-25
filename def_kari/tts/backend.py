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


def _register_grok_tts():
    """xAI Grok TTS は OpenAI 非互換のため専用アダプターで登録。"""
    try:
        from def_kari.compatible_backends_store import all_backends_with_keys
        from def_kari.tts.adapters.grok_tts import make_synthesize_fn
        for entry in all_backends_with_keys():
            if entry["name"] != "grok":
                continue
            TTS_BACKENDS["grok_tts"] = make_synthesize_fn(api_key=entry["api_key"])
            TTS_BACKEND_LABELS["grok_tts"] = "Grok TTS (xAI)"
            print(f"[TTS] grok_tts registered")
            break
        else:
            print("[TTS] grok_tts: 'grok' entry not found in compatible_backends")
    except Exception as e:
        print(f"[TTS] grok_tts registration failed: {e}")


_register_grok_tts()

_COMPATIBLE_TTS_IDS: set[str] = set()


def _register_compatible_tts_backends():
    try:
        from def_kari.compatible_backends_store import all_backends_with_keys
        from def_kari.tts.adapters.compatible_tts import make_synthesize_fn
        for entry in all_backends_with_keys():
            if "tts" not in entry.get("capabilities", []):
                continue
            name = entry["name"]
            synth_fn = make_synthesize_fn(
                base_url=entry["base_url"],
                api_key=entry["api_key"],
                default_model=entry.get("model", "tts-1"),
                max_chars_per_request=entry.get("max_chars_per_request"),
                response_format=entry.get("response_format") or "mp3",
            )
            TTS_BACKENDS[name] = synth_fn
            TTS_BACKEND_LABELS[name] = entry.get("label", name)
            _COMPATIBLE_TTS_IDS.add(name)
            print(f"[TTS] compatible tts registered: {name}")
    except Exception as e:
        print(f"[TTS] compatible tts registration failed: {e}")


_register_compatible_tts_backends()

DEFAULT_TTS_BACKEND = os.environ.get("TTS_BACKEND", "openai_tts")
if DEFAULT_TTS_BACKEND not in TTS_BACKENDS:
    DEFAULT_TTS_BACKEND = "openai_tts"
