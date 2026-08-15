"""AIターン自動読み上げ・人間プレイヤーTTSの、無効設定時の生成スキップテスト。

以前はクライアント側の再生可否（tts_enabled/tts_human_enabled）に関わらず
サーバー側は常に音声を合成しており、誰も聴かない音声を毎ターンvram_lockを
使って合成し続ける無駄があった。挿絵の自動生成オプトイン化（session_auto_illustrate）
と同じ発想で、生成自体をスキップするよう修正した（2026-08-10）。
"""

from unittest import mock


def test_generate_turn_audio_skips_when_tts_disabled():
    from def_kari.api.routes.session import _generate_turn_audio

    with mock.patch(
        "def_kari.api.routes.session_turn_engine.load_settings",
        return_value={"tts_enabled": False, "tts_backend": "voicevox"},
    ), mock.patch(
        "def_kari.api.routes.session_turn_engine._synthesize_turn_audio_sync"
    ) as mock_synth:
        _generate_turn_audio("sid", {"text": "hello", "character_id": "char_a"})

    mock_synth.assert_not_called()


def test_generate_turn_audio_runs_when_tts_enabled():
    from def_kari.api.routes.session import _generate_turn_audio

    with mock.patch(
        "def_kari.api.routes.session_turn_engine.load_settings",
        return_value={"tts_enabled": True, "tts_backend": "voicevox"},
    ), mock.patch(
        "def_kari.api.routes.session_turn_engine._synthesize_turn_audio_sync", return_value=""
    ) as mock_synth:
        _generate_turn_audio("sid", {"text": "hello", "character_id": "char_a"})

    mock_synth.assert_called_once()


def test_start_background_tts_skips_by_default():
    """tts_human_enabledはデフォルトOFFのため、設定未指定なら空文字列を返しスレッドを起動しないこと。"""
    from def_kari.api.routes.session import _start_background_tts

    with mock.patch(
        "def_kari.api.routes.session_turn_engine.load_settings",
        return_value={"tts_backend": "voicevox"},
    ), mock.patch(
        "def_kari.api.routes.session_turn_engine.threading.Thread"
    ) as mock_thread:
        result = _start_background_tts("sid", "こんにちは", "char_a")

    assert result == ""
    mock_thread.assert_not_called()


def test_start_background_tts_runs_when_human_tts_enabled():
    from def_kari.api.routes.session import _start_background_tts

    with mock.patch(
        "def_kari.api.routes.session_turn_engine.load_settings",
        return_value={"tts_backend": "voicevox", "tts_human_enabled": True},
    ), mock.patch(
        "def_kari.api.routes.session_turn_engine.threading.Thread"
    ) as mock_thread:
        result = _start_background_tts("sid", "こんにちは", "char_a")

    assert result != ""
    mock_thread.assert_called_once()
