"""GeminiTtsAdapter: Gemini API TTS（リモートAPI）"""

import base64
import io
import os
import wave

import requests

TTS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
TTS_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_SPEAKER = os.environ.get("GEMINI_TTS_DEFAULT_VOICE", "Kore")


def _get_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        try:
            from def_kari.secrets_store import get_api_key
            key = get_api_key("gemini")
        except Exception:
            pass
    if not key:
        raise RuntimeError("Gemini APIキーが設定されていません。APIキー管理から設定してください。")
    return key


def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def synthesize(text: str, speaker_id=None, options: dict | None = None) -> bytes:
    voice = speaker_id or DEFAULT_SPEAKER
    body = {
        "model": TTS_MODEL,
        "input": text,
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }
    resp = requests.post(
        TTS_URL,
        headers={"x-goog-api-key": _get_key(), "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    if resp.status_code != 200:
        print(f"[GEMINI TTS] error {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()

    data = resp.json()
    audio_b64 = ""
    for step in data.get("steps", []):
        content = step.get("content")
        parts = content if isinstance(content, list) else [content] if isinstance(content, dict) else []
        for part in parts:
            if isinstance(part, dict) and part.get("data"):
                audio_b64 = part["data"]
                print(f"[GEMINI TTS] found audio, mime={part.get('mime_type', '')}, data_len={len(audio_b64)}")
                break
        if audio_b64:
            break

    if not audio_b64:
        print(f"[GEMINI TTS] could not find audio. response={str(data)[:500]}")
        raise RuntimeError("Gemini TTS: 音声データが返されませんでした")

    return _pcm_to_wav(base64.b64decode(audio_b64))
