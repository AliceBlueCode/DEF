"""IrodoriTtsAdapter: Irodori-TTS-Server（ローカル、ゼロショット音声クローン）"""

import os

import requests

URL = os.environ.get("IRODORI_TTS_URL", "http://127.0.0.1:8088")
DEFAULT_SPEAKER = os.environ.get("IRODORI_DEFAULT_SPEAKER", "sample")


def synthesize(text: str, speaker_id=None, options: dict | None = None) -> bytes:
    voice = speaker_id if (speaker_id and str(speaker_id).isascii()) else DEFAULT_SPEAKER
    resp = requests.post(
        f"{URL}/v1/audio/speech",
        json={"model": "irodori-tts", "input": text, "voice": voice, "response_format": "wav"},
        timeout=300,
    )
    resp.raise_for_status()
    return resp.content
