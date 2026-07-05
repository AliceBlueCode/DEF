"""KokoroTtsAdapter: Kokoro TTS（ローカル、OpenAI互換API）"""

import os

import requests

URL = os.environ.get("KOKORO_TTS_URL", "http://127.0.0.1:8766")
DEFAULT_SPEAKER = os.environ.get("KOKORO_DEFAULT_VOICE", "jf_alpha")


def synthesize(text: str, speaker_id=None, options: dict | None = None) -> bytes:
    voice = speaker_id or DEFAULT_SPEAKER
    resp = requests.post(
        f"{URL}/v1/audio/speech",
        json={"model": "kokoro", "input": text, "voice": voice, "response_format": "wav"},
        timeout=120,
    )
    if resp.status_code != 200:
        print(f"[KOKORO TTS] error {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    return resp.content
