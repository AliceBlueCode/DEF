"""F-3: イベントドレイン・ポーリング間隔制御(基本設計3.4節)"""

from __future__ import annotations

import queue

from def_kari.core.events import (
    EVENT_IMAGE_COMPLETE,
    EVENT_SYSTEM_NOTIFICATION,
    EVENT_TTS_COMPLETE,
)


def drain_events(result_q: queue.Queue) -> list[dict]:
    """result_qからイベントをすべて取り出し、timestamp順でソートして返す。"""
    events: list[dict] = []
    while True:
        try:
            events.append(result_q.get_nowait())
        except queue.Empty:
            break
    events.sort(key=lambda e: e.get("timestamp", 0))
    return events


def apply_event(event: dict, session_history: list[dict]) -> None:
    """イベントをsession_history上の対応アイテムに反映する。"""
    payload = event.get("payload", {})
    msg_id = payload.get("msg_id")
    if not msg_id:
        return

    msg = next((m for m in session_history if m.get("id") == msg_id), None)

    event_type = event["type"]

    # セッションモードのTTS完了をsession_tts_audioに蓄積
    if not msg:
        return

    if event_type == EVENT_TTS_COMPLETE:
        msg["audio_path"] = payload.get("audio_path")
        msg["state"] = "TTS Completed"
    elif event_type == EVENT_IMAGE_COMPLETE:
        msg["image_path"] = payload.get("image_path")
        msg["image_queued"] = False
        msg["state"] = "Persist"
        if payload.get("error"):
            msg["image_error"] = payload["error"]
    elif event_type == EVENT_SYSTEM_NOTIFICATION:
        pass
