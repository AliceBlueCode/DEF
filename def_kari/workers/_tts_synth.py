"""TTS合成バックエンド呼び出し — VOICEVOX / Irodori-TTS / Gemini API TTS"""

import base64
import io
import os
import struct
import wave

import requests

VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")
IRODORI_URL = os.environ.get("IRODORI_TTS_URL", "http://127.0.0.1:8088")
KOKORO_URL = os.environ.get("KOKORO_TTS_URL", "http://127.0.0.1:8766")
GEMINI_TTS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_TTS_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_VOICEVOX_SPEAKER = 2
DEFAULT_IRODORI_SPEAKER = ""
DEFAULT_GEMINI_VOICE = "Kore"
DEFAULT_KOKORO_VOICE = "jf_alpha"


def synthesize(text: str, speaker_id, backend: str) -> bytes:
    if backend == "voicevox":
        return _voicevox_synthesize(text, speaker_id or DEFAULT_VOICEVOX_SPEAKER)
    elif backend == "irodori":
        return _irodori_synthesize(text, speaker_id or DEFAULT_IRODORI_SPEAKER)
    elif backend == "gemini_tts":
        return _gemini_synthesize(text, speaker_id or DEFAULT_GEMINI_VOICE)
    elif backend == "kokoro":
        return _kokoro_synthesize(text, speaker_id or DEFAULT_KOKORO_VOICE)
    raise ValueError(f"Unknown TTS backend: {backend}")


def _voicevox_synthesize(text: str, speaker: int) -> bytes:
    query_resp = requests.post(
        f"{VOICEVOX_URL}/audio_query",
        params={"text": text, "speaker": speaker},
        timeout=30,
    )
    query_resp.raise_for_status()

    synth_resp = requests.post(
        f"{VOICEVOX_URL}/synthesis",
        params={"speaker": speaker},
        json=query_resp.json(),
        timeout=60,
    )
    synth_resp.raise_for_status()
    return synth_resp.content


def _irodori_synthesize(text: str, speaker: str) -> bytes:
    """Irodori-TTS-Server（OpenAI互換API）で音声合成する。

    speaker: voicesディレクトリ内の参照音声ファイル名（拡張子なし）。
    空の場合は"sample"を使用（voicesディレクトリに配置が必要）。
    """
    _voice = speaker if speaker and speaker.isascii() else "sample"
    body = {
        "model": "irodori-tts",
        "input": text,
        "voice": _voice,
        "response_format": "wav",
    }
    resp = requests.post(
        f"{IRODORI_URL}/v1/audio/speech",
        json=body,
        timeout=300,
    )
    resp.raise_for_status()
    return resp.content


def _get_gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        try:
            from def_kari.secrets_store import get_api_key
            key = get_api_key("gemini")
        except Exception:
            pass
    if not key:
        raise RuntimeError("Gemini APIキーが設定されていません。")
    return key


def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def _gemini_synthesize(text: str, voice: str) -> bytes:
    body = {
        "model": GEMINI_TTS_MODEL,
        "input": text,
        "response_format": {"type": "audio"},
        "generation_config": {
            "speech_config": [{"voice": voice}],
        },
    }
    resp = requests.post(
        GEMINI_TTS_URL,
        headers={
            "x-goog-api-key": _get_gemini_key(),
            "Content-Type": "application/json",
        },
        json=body,
        timeout=60,
    )
    if resp.status_code != 200:
        print(f"[GEMINI TTS] error {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    data = resp.json()
    audio_b64 = ""
    _mime = ""
    steps = data.get("steps", [])
    for step in steps:
        _content = step.get("content")
        if isinstance(_content, list):
            for part in _content:
                if isinstance(part, dict) and part.get("data"):
                    audio_b64 = part["data"]
                    _mime = part.get("mime_type", "")
                    break
        elif isinstance(_content, dict):
            if _content.get("data"):
                audio_b64 = _content["data"]
                _mime = _content.get("mime_type", "")
        if audio_b64:
            print(f"[GEMINI TTS] found audio, mime={_mime}, data_len={len(audio_b64)}")
            break
    if not audio_b64:
        print(f"[GEMINI TTS] could not find audio. response={str(data)[:500]}")
        raise RuntimeError("Gemini TTS: 音声データが返されませんでした")
    pcm_bytes = base64.b64decode(audio_b64)
    return _pcm_to_wav(pcm_bytes)


def _kokoro_synthesize(text: str, voice: str) -> bytes:
    body = {
        "model": "kokoro",
        "input": text,
        "voice": voice,
        "response_format": "wav",
    }
    resp = requests.post(
        f"{KOKORO_URL}/v1/audio/speech",
        json=body,
        timeout=120,
    )
    if resp.status_code != 200:
        print(f"[KOKORO TTS] error {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    return resp.content
