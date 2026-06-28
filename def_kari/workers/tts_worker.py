"""F-10/F-11: TTSワーカー(基本設計5.2節)"""

import math
import os
import struct
import time
import wave

from def_kari.core.events import make_event, EVENT_TTS_COMPLETE

ASSET_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "assets")
EMOTION_FREQ = {"neutral": 440, "happy": 660, "angry": 220, "sad": 330}


def _generate_beep_wav(path: str, emotion: str) -> None:
    freq = EMOTION_FREQ.get(emotion, 440)
    framerate = 22050
    duration = 0.6
    amp = 16000
    n = int(framerate * duration)

    with wave.open(path, "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(framerate)
        frames = bytearray()
        for i in range(n):
            val = int(amp * math.sin(2 * math.pi * freq * i / framerate))
            frames += struct.pack("<h", val)
        f.writeframes(bytes(frames))


def handle_tts_task(task: dict, result_q) -> None:
    """task = {"kind": "tts", "msg_id": str, "emotion": str, "text": str, ...}
    完了時にEVENT_TTS_COMPLETEをresult_qへpushする。"""
    msg_id = task["msg_id"]
    emotion = task.get("emotion", "neutral")
    text = task.get("text", "")

    os.makedirs(ASSET_DIR, exist_ok=True)
    filename = f"{msg_id}_{int(time.time() * 1000)}.wav"
    path = os.path.join(ASSET_DIR, filename)

    error = None
    try:
        tts_backend_name = task.get("tts_backend")
        speaker_id = task.get("tts_speaker_id")
        print(f"[TTS WORKER] msg_id={msg_id}, backend={tts_backend_name}, speaker={speaker_id}, text={text[:30]}")
        if tts_backend_name:
            from def_kari.workers._tts_synth import synthesize
            audio_bytes = synthesize(text, speaker_id, tts_backend_name)
            with open(path, "wb") as f:
                f.write(audio_bytes)
        else:
            _generate_beep_wav(path, emotion)
    except Exception as exc:
        error = str(exc)
        print(f"[TTS WORKER] error: {error}")
        _generate_beep_wav(path, emotion)

    payload = {"msg_id": msg_id, "audio_path": path}
    if error:
        payload["error"] = error
    result_q.put(make_event(EVENT_TTS_COMPLETE, payload))
