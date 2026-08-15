"""_maybe_generate_turn_media の挿絵自動生成オプトインテスト。

以前はAIターン完了ごとに挿絵(_generate_turn_image)を無条件でバックグラウンド
生成していたが、テンポ重視で作画ボタン（発言力を消費・認証済み）のみに
限定したいという要望から、session_auto_illustrate設定（デフォルトOFF）で
オプトインに変更した。TTS自動生成は対象外で常時変更なし（2026-08-10）。
"""

from unittest import mock


def test_auto_illustrate_off_by_default_skips_image_thread():
    from def_kari.api.routes.session import _maybe_generate_turn_media

    with mock.patch(
        "def_kari.api.routes.session_turn_engine.load_settings", return_value={}
    ), mock.patch(
        "def_kari.api.routes.session_turn_engine.threading.Thread"
    ) as mock_thread:
        _maybe_generate_turn_media("sid", {"text": "hello"})

    targets = [call.kwargs.get("target") for call in mock_thread.call_args_list]
    from def_kari.api.routes.session import _generate_turn_image, _generate_turn_audio
    assert _generate_turn_image not in targets
    assert _generate_turn_audio in targets


def test_auto_illustrate_on_starts_image_thread():
    from def_kari.api.routes.session import _maybe_generate_turn_media

    with mock.patch(
        "def_kari.api.routes.session_turn_engine.load_settings",
        return_value={"session_auto_illustrate": True},
    ), mock.patch(
        "def_kari.api.routes.session_turn_engine.threading.Thread"
    ) as mock_thread:
        _maybe_generate_turn_media("sid", {"text": "hello"})

    targets = [call.kwargs.get("target") for call in mock_thread.call_args_list]
    from def_kari.api.routes.session import _generate_turn_image, _generate_turn_audio
    assert _generate_turn_image in targets
    assert _generate_turn_audio in targets
