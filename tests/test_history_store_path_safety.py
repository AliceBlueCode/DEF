"""def_kari/history/store.py の character_id/session_id にID形式検証が無く、
そのままファイル名に使われていた問題（trpg loaderの8.26と同型のパストラバーサル
経路）のテスト。本モジュールはmain.py経由のローカル専用API（chat.py/session.py）
からのみ到達し、session_idは通常サーバー生成のためリモート攻撃には直結しないが、
「サーバー生成だから安全」に依存しない多層防御として_SAFE_ID_REを追加した。
"""

import tempfile
from pathlib import Path

import pytest

from def_kari.history import store


@pytest.fixture
def isolated_store(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_data_dir = Path(tmpdir)
        monkeypatch.setattr(store, "DATA_DIR", tmp_data_dir)
        monkeypatch.setattr(store, "PRIVATE_DIR", tmp_data_dir / "private")
        yield tmp_data_dir


_BAD_IDS = ["../secret", "..%2Fsecret", "a/b", "a\\b", "a.b", ""]


def test_load_full_rejects_bad_character_id(isolated_store):
    for bad_id in _BAD_IDS:
        assert store.load_full(bad_id) == []


def test_save_session_rejects_bad_character_id_without_writing(isolated_store):
    for bad_id in _BAD_IDS:
        store.save_session([{"id": "h1", "text": "hi", "state": "Persist"}], bad_id)
    # public/private のどちらにも session_history ファイルが作られていないこと
    for sub in ("public", "private"):
        d = isolated_store / sub / "session_history"
        assert not d.exists() or list(d.glob("*.json")) == []


def test_clear_history_rejects_bad_character_id(isolated_store):
    for bad_id in _BAD_IDS:
        store.clear_history(bad_id)  # 例外を投げないこと自体がテスト


def test_history_store_still_works_for_valid_id(isolated_store):
    """回帰確認: 正規のcharacter_idでは従来どおり動作すること。"""
    store.save_session([{"id": "h1", "text": "hello", "state": "Persist"}], "test_luna")
    loaded = store.load_full("test_luna")
    assert len(loaded) == 1
    assert loaded[0]["text"] == "hello"
    store.clear_history("test_luna")
    assert store.load_full("test_luna") == []


def test_save_session_mode_rejects_bad_session_id_without_writing(isolated_store):
    for bad_id in _BAD_IDS:
        store.save_session_mode(bad_id, [], [{"id": "h1"}], {})
    for sub in ("public", "private"):
        d = isolated_store / sub / "session_history"
        assert not d.exists() or list(d.glob("session_mode_*.json")) == []


def test_load_session_mode_rejects_bad_session_id(isolated_store):
    for bad_id in _BAD_IDS:
        assert store.load_session_mode(bad_id, []) is None


def test_session_mode_still_works_for_valid_id(isolated_store):
    """回帰確認: 正規のsession_idでは従来どおり動作すること。"""
    store.save_session_mode("valid_session_123", ["char_a"], [{"id": "h1"}], {"topic": "t"})
    loaded = store.load_session_mode("valid_session_123", ["char_a"])
    assert loaded is not None
    assert loaded["session_id"] == "valid_session_123"
