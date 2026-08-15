"""pytest共通フィクスチャ。

character_json 持ち込みの /join を呼ぶ既存テストが、LLM審査（audit_character_json）追加によって
実際にLLM呼び出しを行わないよう、デフォルトで審査通過にスタブする。
個別に reject/timeout パスを検証するテストはこのフィクスチャを `with patch(...)` で上書きする。
"""

import os

# session.py が import される前に設定する必要がある（_VRAM_LOCK_TIMEOUT_SECONDS は
# モジュールロード時に os.environ から一度だけ読まれる）。
# _execute_ai_turn 等をモックし忘れたテストが実LLM呼び出しでvram_lockを握ったまま
# 60秒（本番値）ブロックし続けるのを待たず、2秒で諦めさせてすぐ気付けるようにする。
# fail-silentの挙動自体（本番コードのロジック）は変えず、待ち時間だけを短縮する
# 目的なので、ここでモックの中身を弄って挙動を誤魔化すことはしない（2026-08-02）。
os.environ.setdefault("DEF_VRAM_LOCK_TIMEOUT", "2")

import pytest
from unittest.mock import patch

from def_kari.safety.character_audit import AuditResult


@pytest.fixture(autouse=True)
def _stub_character_audit():
    with patch(
        "def_kari.api.routes.session_lobby.audit_character_json",
        return_value=AuditResult(passed=True, reason="stubbed"),
    ) as m:
        yield m


@pytest.fixture(autouse=True)
def _reset_session_create_rate():
    """/startのIPベースレート制限（8.5対策、1分あたり20回）状態をテストごとにクリアする。

    TestClientのリクエストは全て"testclient"という同一ホスト名から来るため、
    このグローバル辞書をクリアしないとテストスイート全体で単一のバケットを
    共有してしまい、/startを呼ぶ既存テストが後半になるほど429で落ちる
    （実際に発生した事故、2026-08-05）。
    """
    from def_kari.api.routes.session import _session_create_rate
    _session_create_rate.clear()
    yield
    _session_create_rate.clear()


@pytest.fixture(autouse=True)
def _block_real_llm_calls():
    """テスト環境ではLLMバックエンドへの実ネットワーク呼び出しを一切許可しない。

    _execute_ai_turn / _gm_agent.narrate / generate_structured_reply 等をモックし
    忘れたテストが、無応答のバックエンドに接続を試みて vram_lock を握ったまま長時間
    ブロックし、後続テストとデッドロックする事故が実際に起きた（2026-08-02）。

    正常系の結果を装う空スタブは「テストを通すためのモック」になってしまい、モック
    し忘れを見逃す（実際に一度この失敗をした）。代わりに「呼ばれたら即座に例外を
    投げる」ダミーに差し替えることで、モックし忘れがあれば vram_lock を長時間握る
    ことなく即座に解放させつつ（session.py側は except Exception で受けて finally で
    release する設計）、そのテスト自体を分かりやすく失敗させる。

    LLM_BACKENDS オブジェクト自体（def_kari.llm.backend）の中身を書き換えるため、
    これをimportして使う全モジュール（session.py 等）に効く。tests/test_character_audit.py
    は def_kari.safety.character_audit.LLM_BACKENDS という別モジュールの参照先を
    丸ごと差し替える独立したパターンなので衝突しない。
    """
    from def_kari.llm.backend import LLM_BACKENDS

    def _blocked_chat(*args, **kwargs):
        raise RuntimeError(
            "LLM backend called during a test without mocking. "
            "Mock _execute_ai_turn, _player_agent.narrate, _gm_agent.narrate, "
            "generate_structured_reply, or the specific chat_fn as appropriate."
        )

    originals = {bid: entry.get("chat") for bid, entry in LLM_BACKENDS.items()}
    for entry in LLM_BACKENDS.values():
        entry["chat"] = _blocked_chat
    try:
        yield
    finally:
        for bid, entry in LLM_BACKENDS.items():
            entry["chat"] = originals[bid]
