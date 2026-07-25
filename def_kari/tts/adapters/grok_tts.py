"""xAI Grok TTS アダプター。
xAI の TTS API は OpenAI /audio/speech と非互換 (/v1/tts、voice_id、output_format が異なる)。
"""

import requests

_XAI_TTS_URL = "https://api.x.ai/v1/tts"
_DEFAULT_VOICE = "Carina"


def make_synthesize_fn(api_key: str, default_voice: str = _DEFAULT_VOICE, language: str = "en"):
    def synthesize(text: str, speaker_id=None, options: dict | None = None) -> bytes:
        voice_id = speaker_id if speaker_id else default_voice
        body = {
            "text": text,
            "voice_id": voice_id,
            "output_format": {"codec": "mp3", "sample_rate": 44100, "bit_rate": 128000},
            "language": language,
        }
        print(f"[GROK TTS] POST {_XAI_TTS_URL} voice_id={voice_id}")
        resp = requests.post(
            _XAI_TTS_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=60,
        )
        if not resp.ok:
            print(f"[GROK TTS] {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
        return resp.content

    return synthesize
