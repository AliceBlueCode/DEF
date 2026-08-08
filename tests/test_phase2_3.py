"""MVP初期(Phase 2-3)CLI検証: safety, historyがStreamlit無しで動作することを確認する。
2026-08-08、def_kari/直下からtests/へ移動。workers系(test_tts_worker/test_t2i_worker/
test_worker_runner)は死んでいたworkers.runner/t2i_worker/tts_workerのテストだった
ため削除(モジュール自体も削除)。

使用方法:
  cd e:\tools\DEF
  python -m pytest tests/test_phase2_3.py
"""

import tempfile


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
    test_history_store()
    print("\nPhase 2-3 CLI tests: all passed.")
