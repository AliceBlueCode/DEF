"""VoicevoxAdapter: VOICEVOX ENGINE（ローカル）"""

import os

import requests

URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")
DEFAULT_SPEAKER = int(os.environ.get("VOICEVOX_DEFAULT_SPEAKER", "2"))


def synthesize(text: str, speaker_id=None, options: dict | None = None) -> bytes:
    speaker = speaker_id if speaker_id is not None else DEFAULT_SPEAKER
    query_resp = requests.post(
        f"{URL}/audio_query",
        params={"text": text, "speaker": speaker},
        timeout=30,
    )
    query_resp.raise_for_status()

    synth_resp = requests.post(
        f"{URL}/synthesis",
        params={"speaker": speaker},
        json=query_resp.json(),
        timeout=60,
    )
    synth_resp.raise_for_status()
    return synth_resp.content
