"""Phase 2-3 CLI検証: workers, safety, historyがStreamlit無しで動作することを確認する。

使用方法:
  cd e:\tools\DEF
  python -m def_kari.test_phase2_3
"""

import os
import json
import queue
import tempfile
import threading


def test_tts_worker():
    from def_kari.workers.tts_worker import handle_tts_task

    result_q = queue.Queue()
    task = {"kind": "tts", "msg_id": "test-tts-001", "emotion": "happy", "text": "テスト"}
    handle_tts_task(task, result_q)

    event = result_q.get(timeout=5)
    assert event["type"] == "TTS_COMPLETE"
    assert event["payload"]["msg_id"] == "test-tts-001"
    audio_path = event["payload"]["audio_path"]
    assert audio_path and os.path.exists(audio_path)
    os.remove(audio_path)
    print("PASS: tts_worker")


def test_t2i_worker():
    from def_kari.workers.t2i_worker import handle_image_task

    result_q = queue.Queue()
    vram_lock = threading.Lock()
    task = {
        "kind": "image",
        "msg_id": "test-t2i-001",
        "emotion": "sad",
        "image_prompt_en": "1girl, beach, sunset",
        "t2i_width": 256,
        "t2i_height": 256,
    }
    handle_image_task(task, result_q, vram_lock)

    events = []
    while not result_q.empty():
        events.append(result_q.get_nowait())

    assert any(e["type"] == "SYSTEM_NOTIFICATION" and "acquired" in e["payload"].get("message", "") for e in events)
    assert any(e["type"] == "IMAGE_COMPLETE" for e in events)
    assert any(e["type"] == "SYSTEM_NOTIFICATION" and "released" in e["payload"].get("message", "") for e in events)
    assert not vram_lock.locked()

    img_event = next(e for e in events if e["type"] == "IMAGE_COMPLETE")
    img_path = img_event["payload"]["image_path"]
    assert os.path.exists(img_path)
    os.remove(img_path)
    print("PASS: t2i_worker")


def test_worker_runner():
    from def_kari.workers.runner import start_worker

    task_q = queue.Queue()
    result_q = queue.Queue()
    vram_lock = threading.Lock()

    t = start_worker(task_q, result_q, vram_lock)
    assert t.is_alive()

    task_q.put({"kind": "tts", "msg_id": "runner-001", "emotion": "neutral", "text": "test"})
    event = result_q.get(timeout=10)
    assert event["type"] == "TTS_COMPLETE"
    if event["payload"].get("audio_path") and os.path.exists(event["payload"]["audio_path"]):
        os.remove(event["payload"]["audio_path"])
    print("PASS: worker_runner")


def test_safety_filters():
    from def_kari.safety.filters import (
        is_flagged,
        effective_level,
        should_mask_text,
        should_blur_image,
        should_hide_image,
        should_autoplay_audio,
        should_hide_audio,
    )

    assert is_flagged(["nsfw"]) is True
    assert is_flagged([]) is False
    assert is_flagged(None) is False

    assert effective_level("mask", True, False) == "mask"
    assert effective_level("mask", True, True) == "off"
    assert effective_level("warn", False, False) == "off"

    assert should_mask_text("mask") is True
    assert should_mask_text("warn") is False
    assert should_blur_image("warn") is True
    assert should_hide_image("mask") is True
    assert should_autoplay_audio("off") is True
    assert should_autoplay_audio("warn") is False
    assert should_hide_audio("mask") is True
    print("PASS: safety_filters")


def test_history_store():
    from def_kari.history import store

    original_dir = store.DATA_DIR
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            from pathlib import Path
            store.DATA_DIR = Path(tmpdir)

            test_char = "test_luna"
            assert store.load_full(test_char) == []

            history = [
                {"id": "h1", "text": "hello", "state": "Persist"},
                {"id": "h2", "text": "world", "state": "Persist"},
            ]
            store.save_session(history, test_char)

            loaded = store.load_full(test_char)
            assert len(loaded) == 2
            assert loaded[0]["id"] == "h1"

            assert store.load_full("other_char") == []

            history[0]["text"] = "updated"
            history.append({"id": "h3", "text": "new", "state": "TTS Running"})
            store.save_session(history, test_char)

            loaded2 = store.load_full(test_char)
            assert len(loaded2) == 3
            assert loaded2[0]["text"] == "updated"

            trimmed = store.trim_session(
                [
                    {"id": "h1", "state": "Persist"},
                    {"id": "h2", "state": "Persist"},
                    {"id": "h3", "state": "Persist"},
                    {"id": "h4", "state": "TTS Running"},
                ],
                max_visible=2,
            )
            ids = {m["id"] for m in trimmed}
            assert "h4" in ids
            assert "h3" in ids or "h2" in ids
            assert len(trimmed) <= 3

            store.clear_history(test_char)
            assert store.load_full(test_char) == []

            print("PASS: history_store")
    finally:
        store.DATA_DIR = original_dir


if __name__ == "__main__":
    test_safety_filters()
    test_tts_worker()
    test_t2i_worker()
    test_worker_runner()
    test_history_store()
    print("\nPhase 2-3 CLI tests: all passed.")
