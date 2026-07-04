"""F-13-1: vram_lockシングルトン(基本設計5.3節)"""

from __future__ import annotations
import threading

_lock: threading.Lock | None = None


def get_vram_lock() -> threading.Lock:
    global _lock
    if _lock is None:
        _lock = threading.Lock()
    return _lock
