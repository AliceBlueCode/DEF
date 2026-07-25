"""OpenAI TTS互換アダプター — 任意のベースURLで動作"""

import requests


def _split_text(text: str, max_chars: int) -> list[str]:
    """max_chars以下のチャンクに分割。文末句読点優先。"""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        cut = max_chars
        for punct in ("。", "！", "？", "!", "?", "、", ",", " "):
            pos = text.rfind(punct, 0, max_chars)
            if pos > 0:
                cut = pos + 1
                break
        chunks.append(text[:cut])
        text = text[cut:]
    return chunks


def make_synthesize_fn(
    base_url: str,
    api_key: str,
    default_voice: str = "alloy",
    default_model: str = "tts-1",
    max_chars_per_request: int | None = None,
    response_format: str = "mp3",
):
    def synthesize(text: str, speaker_id=None, options: dict | None = None) -> bytes:
        voice = speaker_id if speaker_id else default_voice
        model = (options or {}).get("model", default_model)
        url = f"{base_url.rstrip('/')}/audio/speech"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        chunks = _split_text(text, max_chars_per_request) if max_chars_per_request else [text]
        audio_parts: list[bytes] = []

        for i, chunk in enumerate(chunks):
            body = {"model": model, "input": chunk, "voice": voice, "response_format": response_format}
            print(f"[COMPATIBLE TTS] POST {url} model={model} voice={voice} chunk={i+1}/{len(chunks)}")
            resp = requests.post(url, headers=headers, json=body, timeout=60)
            if not resp.ok:
                print(f"[COMPATIBLE TTS] {resp.status_code}: {resp.text[:500]}")
            resp.raise_for_status()
            audio_parts.append(resp.content)

        return b"".join(audio_parts)

    return synthesize
