"""TTS合成エントリーポイント — def_kari.tts.backend へ委譲"""

from def_kari.tts.backend import TTS_BACKENDS


def synthesize(text: str, speaker_id, backend: str) -> bytes:
    if backend not in TTS_BACKENDS:
        raise ValueError(f"Unknown TTS backend: {backend}")
    return TTS_BACKENDS[backend](text, speaker_id)
