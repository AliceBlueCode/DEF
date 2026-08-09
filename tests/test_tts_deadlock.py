"""_generate_turn_audio が保持する vram_lock の自己デッドロック回帰テスト。

synthesize_and_save() が独自に vram_lock を再取得していたため、呼び出し元の
_synthesize_turn_audio_sync が既に取得済みのロックを同一スレッドが再度 acquire()
しようとして永久にブロックしていた（threading.Lock は非再入のため）。
実機でセッションの自動進行が完全に停止する形で発覚した（2026-08-09）。
"""

import threading
from unittest import mock


def test_synthesize_turn_audio_sync_does_not_deadlock():
    """_synthesize_turn_audio_sync がタイムアウトせず完了し、vram_lock を解放すること。"""
    from def_kari.api.routes.session import _synthesize_turn_audio_sync
    from def_kari.resources.vram_lock import get_vram_lock

    with mock.patch(
        "def_kari.api.routes.tts.synthesize", return_value=b"fake-wav-bytes"
    ):
        result_holder: dict = {}

        def _run():
            result_holder["url"] = _synthesize_turn_audio_sync(
                "こんにちは", "nonexistent_char_for_test", "voicevox"
            )

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=5)

        assert not t.is_alive(), "デッドロックしている（5秒待っても完了しない）"
        assert result_holder.get("url", "").startswith("/api/tts/audio/")

    lock = get_vram_lock()
    acquired = lock.acquire(timeout=1)
    assert acquired, "呼び出し後も vram_lock が解放されていない"
    lock.release()
