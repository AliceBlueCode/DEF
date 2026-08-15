"""data/private/session_autosave/ のTTL掃除機構（_cleanup_stale_autosaves）のテスト。

_delete_autosave() はセッション正常終了時（/end 等）にしか呼ばれず、プロセスの
異常終了やホストが /end を呼ばずに放置した場合はファイルが際限なく溜まり続けて
いた（TODO.md「data/private/session_autosave/の掃除機構が無い」、実測1752個）。
"""

import time
from unittest.mock import patch


def test_cleanup_removes_stale_inactive_session_files(tmp_path):
    """TTLを超えて更新がなく、_sessionsにも存在しないファイルは削除されること。"""
    from def_kari.api.routes.session import _cleanup_stale_autosaves, _sessions, _autosave_last_cleanup

    stale = tmp_path / "stale_session.json"
    stale.write_text("{}", encoding="utf-8")
    old_time = time.time() - 8 * 24 * 3600  # 8日前（TTL=7日を超過）
    import os
    os.utime(stale, (old_time, old_time))

    assert "stale_session" not in _sessions
    with patch("def_kari.api.routes.session_persistence._AUTOSAVE_DIR", tmp_path):
        _autosave_last_cleanup["t"] = float("-inf")  # 呼び出し頻度制限をリセットして即実行させる
        _cleanup_stale_autosaves()

    assert not stale.exists()


def test_cleanup_keeps_fresh_files(tmp_path):
    """TTL内（更新が新しい）のファイルは削除されないこと。"""
    from def_kari.api.routes.session import _cleanup_stale_autosaves, _autosave_last_cleanup

    fresh = tmp_path / "fresh_session.json"
    fresh.write_text("{}", encoding="utf-8")

    with patch("def_kari.api.routes.session_persistence._AUTOSAVE_DIR", tmp_path):
        _autosave_last_cleanup["t"] = float("-inf")
        _cleanup_stale_autosaves()

    assert fresh.exists()


def test_cleanup_keeps_stale_files_for_active_sessions(tmp_path):
    """TTLを超えていても、_sessionsに存在する（＝現在アクティブな）セッションのファイルは残ること。"""
    from def_kari.api.routes.session import _cleanup_stale_autosaves, _sessions, _autosave_last_cleanup

    sid = "_autosave_cleanup_active_test"
    active = tmp_path / f"{sid}.json"
    active.write_text("{}", encoding="utf-8")
    old_time = time.time() - 8 * 24 * 3600
    import os
    os.utime(active, (old_time, old_time))

    _sessions[sid] = {"id": sid}
    try:
        with patch("def_kari.api.routes.session_persistence._AUTOSAVE_DIR", tmp_path):
            _autosave_last_cleanup["t"] = float("-inf")
            _cleanup_stale_autosaves()
        assert active.exists()
    finally:
        _sessions.pop(sid, None)


def test_cleanup_respects_rate_limit(tmp_path):
    """直前に実行済みなら、TTL超過ファイルがあっても間引かれないこと（呼び出し頻度制限）。"""
    from def_kari.api.routes.session import _cleanup_stale_autosaves, _autosave_last_cleanup

    stale = tmp_path / "stale_session2.json"
    stale.write_text("{}", encoding="utf-8")
    old_time = time.time() - 8 * 24 * 3600
    import os
    os.utime(stale, (old_time, old_time))

    with patch("def_kari.api.routes.session_persistence._AUTOSAVE_DIR", tmp_path):
        _autosave_last_cleanup["t"] = time.monotonic()  # ついさっき実行済みという体にする
        _cleanup_stale_autosaves()

    assert stale.exists()  # 間引かれない
