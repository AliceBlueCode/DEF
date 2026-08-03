"""JWT秘密鍵の手動再生成（マルチプレイ設計書§7で「決定」だったが未実装だった機能）のテスト。

再生成後は settings.json の jwt_secret が新しい値に更新され、既存の全JWTは
新しい鍵で検証できなくなり無効になる。APIエンドポイントは加えて全アクティブ
セッションのWS接続をcode=1008で強制切断する。
"""

import json
from unittest.mock import AsyncMock, patch

import pytest


def test_regenerate_jwt_secret_overwrites_existing_value(tmp_path):
    """既存のjwt_secretがあっても、呼び出すたびに新しい値で上書きされること。"""
    from def_kari import settings as settings_module

    settings_path = tmp_path / "mvp_settings.json"
    settings_path.write_text(json.dumps({"jwt_secret": "old-secret"}), encoding="utf-8")

    with patch.object(settings_module, "SETTINGS_PATH", settings_path), \
         patch.object(settings_module, "DATA_DIR", tmp_path):
        new_secret = settings_module.regenerate_jwt_secret()

        assert new_secret != "old-secret"
        assert len(new_secret) == 64  # secrets.token_hex(32) は64文字の16進文字列

        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        assert saved["jwt_secret"] == new_secret

        # 続けて呼ぶとさらに別の値になること（固定値へのフォールバックでないこと）
        newer_secret = settings_module.regenerate_jwt_secret()
        assert newer_secret != new_secret


def test_regenerate_jwt_secret_preserves_other_settings(tmp_path):
    """jwt_secret以外の既存設定値が再生成時に消えないこと。"""
    from def_kari import settings as settings_module

    settings_path = tmp_path / "mvp_settings.json"
    settings_path.write_text(
        json.dumps({"jwt_secret": "old-secret", "user_language": "en"}), encoding="utf-8"
    )

    with patch.object(settings_module, "SETTINGS_PATH", settings_path), \
         patch.object(settings_module, "DATA_DIR", tmp_path):
        settings_module.regenerate_jwt_secret()
        saved = json.loads(settings_path.read_text(encoding="utf-8"))
        assert saved["user_language"] == "en"


@pytest.mark.asyncio
async def test_regenerate_endpoint_invalidates_existing_tokens_and_closes_ws(tmp_path):
    """再生成エンドポイントを叩くと、既存トークンが無効になり、全WS接続がcode=1008でcloseされること。"""
    from def_kari import settings as settings_module
    from def_kari.api.routes.session import (
        _sessions, issue_player_jwt, verify_jwt,
    )
    from def_kari.api.routes.settings import regenerate_jwt_secret_endpoint
    from jose import JWTError

    settings_path = tmp_path / "mvp_settings.json"
    settings_path.write_text(json.dumps({}), encoding="utf-8")

    sid = "_jwt_regen_test"
    fake_ws = AsyncMock()
    try:
        with patch.object(settings_module, "SETTINGS_PATH", settings_path), \
             patch.object(settings_module, "DATA_DIR", tmp_path):
            # issue_player_jwt/verify_jwt も get_jwt_secret() 経由でこの settings_path を
            # 読むため、トークンの発行・検証・再生成すべてを同じパッチ下で行う
            old_token = issue_player_jwt(sid, "player", "char_a")
            verify_jwt(old_token)  # 再生成前は有効なことの前提確認

            _sessions[sid] = {"ws_connections": {old_token: fake_ws}}

            result = await regenerate_jwt_secret_endpoint()

            assert result["disconnected_connections"] == 1
            fake_ws.close.assert_awaited_once_with(code=1008)
            assert _sessions[sid]["ws_connections"] == {}

            with pytest.raises(JWTError):
                verify_jwt(old_token)  # 古いトークンはもう検証できない
    finally:
        _sessions.pop(sid, None)
