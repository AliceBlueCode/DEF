"""GM Event Bus: ゲームロジック用イベント名前空間。

core/events.py はインフラ系（TTS/Image/Error）。
gm/events.py はゲームロジック系（判定・場面・NPC・フラグ）。
"""

import time
import uuid
from typing import Callable


# ── イベント種別定数 ──────────────────────────────────────────────
JUDGMENT_RESOLVED = "JUDGMENT_RESOLVED"   # ダイス+判定結果が出た
SCENE_NARRATED    = "SCENE_NARRATED"      # GMがナレーションを生成した
SCENE_CHANGED     = "SCENE_CHANGED"       # シーンインデックスが進んだ
NPC_DEAD          = "NPC_DEAD"            # NPCのHPが0になった
FLAG_UPDATED      = "FLAG_UPDATED"        # ストーリーフラグが変更された
DAMAGE_APPLIED    = "DAMAGE_APPLIED"      # HP/MP/SANダメージが適用された
STATUS_CHANGED    = "STATUS_CHANGED"      # 状態異常が付与/解除された
TOPIC_CHANGED     = "TOPIC_CHANGED"       # 投票によりお題が変更された
SESSION_ENDED     = "SESSION_ENDED"       # セッション終了が可決された


class GameEventBus:
    """セッション単位のゲームロジックイベントを仲介するシンプルなPub/Sub。

    - ハンドラは subscribe() で登録する（モジュールレベルでOK）
    - emit() は同期的に全ハンドラを呼び出す（例外は握り潰す）
    - イベントログはセッション単位でメモリに保持（Observer Agent用）
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[str, dict], None]]] = {}
        self._logs: dict[str, list[dict]] = {}

    def subscribe(self, event_type: str, handler: Callable[[str, dict], None]) -> None:
        """event_type のハンドラを登録する。handler(session_id, event_dict) で呼ばれる。"""
        self._handlers.setdefault(event_type, []).append(handler)

    def emit(self, session_id: str, event_type: str, payload: dict) -> None:
        """イベントを発行し、登録済みハンドラを同期実行する。"""
        event = {
            "id": str(uuid.uuid4()),
            "type": event_type,
            "session_id": session_id,
            "payload": payload,
            "timestamp": time.time(),
        }
        self._logs.setdefault(session_id, []).append(event)
        for handler in self._handlers.get(event_type, []):
            try:
                handler(session_id, event)
            except Exception:
                pass

    def get_log(self, session_id: str) -> list[dict]:
        """セッションのイベントログを返す（コピー）。"""
        return list(self._logs.get(session_id, []))

    def clear_log(self, session_id: str) -> None:
        """セッション終了時などにログを破棄する。"""
        self._logs.pop(session_id, None)


# モジュールレベルのシングルトン
game_event_bus = GameEventBus()
