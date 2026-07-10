"""OpenAITtsAdapter: OpenAI TTS API (tts-1 / tts-1-hd)"""

import os

import requests

DEFAULT_VOICE = os.environ.get("OPENAI_TTS_DEFAULT_VOICE", "alloy")
DEFAULT_MODEL = os.environ.get("OPENAI_TTS_MODEL", "tts-1")

_VOICES = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}


def _get_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        try:
            from def_kari.secrets_store import get_api_key
            key = get_api_key("openai")
        except Exception:
            pass
    if not key:
        raise RuntimeError("OpenAI APIキーが設定されていません。APIキー管理から設定してください。")
    return key


def synthesize(text: str, speaker_id=None, options: dict | None = None) -> bytes:
    voice = speaker_id if speaker_id in _VOICES else DEFAULT_VOICE
    model = (options or {}).get("model", DEFAULT_MODEL)
    resp = requests.post(
        "https://api.openai.com/v1/audio/speech",
        headers={
            "Authorization": f"Bearer {_get_key()}",
            "Content-Type": "application/json",
        },
        json={"model": model, "input": text, "voice": voice, "response_format": "wav"},
        timeout=60,
    )
    if resp.status_code != 200:
        print(f"[OPENAI TTS] error {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    return resp.content
