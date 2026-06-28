"""F-1/F-2: 共通Eventスキーマ・標準イベント種別(基本設計3.1/3.2節)"""

import time
import uuid

EVENT_TTS_COMPLETE = "TTS_COMPLETE"
EVENT_IMAGE_COMPLETE = "IMAGE_COMPLETE"
EVENT_ERROR = "ERROR"
EVENT_AGENT_MESSAGE = "AGENT_MESSAGE"
EVENT_SYSTEM_NOTIFICATION = "SYSTEM_NOTIFICATION"


def make_event(event_type: str, payload: dict) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "type": event_type,
        "payload": payload,
        "timestamp": time.time(),
    }
