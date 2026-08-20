"""VOICEVOXメモリウォッチドッグ(check_voicevox_watchdog_once)のテスト。

upstream(VOICEVOX/voicevox_engine#1506・#513・#1691)がONNX Runtimeの
メモリアリーナ未解放問題を解決できていないため、DEF側でメモリ閾値超過(主)・
経過時間超過(保険)のハイブリッド判定でエンジンを定期再起動する設計
(TODO.md「VOICEVOXエンジンのメモリリーク疑い」参照)。
"""

import time
from unittest.mock import patch

from def_kari import backends


def _write_pid_file(tmp_path, monkeypatch, launched_at):
    monkeypatch.setattr(backends, "_DATA_DIR", str(tmp_path))
    pid_path = backends._pid_path("voicevox")
    with open(pid_path, "w") as f:
        f.write(f"{12345}:{launched_at}")
    return pid_path


def test_not_running_skips_check(tmp_path, monkeypatch):
    _write_pid_file(tmp_path, monkeypatch, time.time())
    with patch.object(backends, "is_voicevox_running", return_value=False), \
         patch.object(backends, "stop_voicevox") as mock_stop, \
         patch.object(backends, "start_voicevox") as mock_start:
        result = backends.check_voicevox_watchdog_once()
    assert result is None
    mock_stop.assert_not_called()
    mock_start.assert_not_called()


def test_missing_pid_file_skips_check(tmp_path, monkeypatch):
    monkeypatch.setattr(backends, "_DATA_DIR", str(tmp_path))
    with patch.object(backends, "is_voicevox_running", return_value=True), \
         patch.object(backends, "stop_voicevox") as mock_stop:
        result = backends.check_voicevox_watchdog_once()
    assert result is None
    mock_stop.assert_not_called()


def test_under_both_thresholds_no_restart(tmp_path, monkeypatch):
    _write_pid_file(tmp_path, monkeypatch, time.time())
    with patch.object(backends, "is_voicevox_running", return_value=True), \
         patch.object(backends, "_voicevox_process_memory_mb", return_value=500.0), \
         patch.object(backends, "stop_voicevox") as mock_stop, \
         patch.object(backends, "start_voicevox") as mock_start:
        result = backends.check_voicevox_watchdog_once()
    assert result is None
    mock_stop.assert_not_called()
    mock_start.assert_not_called()


def test_over_memory_threshold_restarts(tmp_path, monkeypatch):
    _write_pid_file(tmp_path, monkeypatch, time.time())
    with patch.object(backends, "is_voicevox_running", return_value=True), \
         patch.object(backends, "_voicevox_process_memory_mb", return_value=8000.0), \
         patch.object(backends, "stop_voicevox", return_value=None) as mock_stop, \
         patch.object(backends, "start_voicevox", return_value=None) as mock_start:
        result = backends.check_voicevox_watchdog_once()
    assert result == "memory"
    mock_stop.assert_called_once()
    mock_start.assert_called_once()


def test_over_uptime_threshold_restarts_even_with_low_memory(tmp_path, monkeypatch):
    old_launch = time.time() - backends._WATCHDOG_MAX_UPTIME_SEC - 1.0
    _write_pid_file(tmp_path, monkeypatch, old_launch)
    with patch.object(backends, "is_voicevox_running", return_value=True), \
         patch.object(backends, "_voicevox_process_memory_mb", return_value=200.0), \
         patch.object(backends, "stop_voicevox", return_value=None) as mock_stop, \
         patch.object(backends, "start_voicevox", return_value=None) as mock_start:
        result = backends.check_voicevox_watchdog_once()
    assert result == "uptime"
    mock_stop.assert_called_once()
    mock_start.assert_called_once()


def test_restart_skipped_while_generation_in_progress(tmp_path, monkeypatch):
    """vram_lock使用中(LLM/T2I/TTS生成中)は再起動に割り込まないこと。"""
    _write_pid_file(tmp_path, monkeypatch, time.time())
    from def_kari.resources.vram_lock import get_vram_lock
    lock = get_vram_lock()
    lock.acquire()
    try:
        with patch.object(backends, "is_voicevox_running", return_value=True), \
             patch.object(backends, "_voicevox_process_memory_mb", return_value=8000.0), \
             patch.object(backends, "stop_voicevox") as mock_stop, \
             patch.object(backends, "start_voicevox") as mock_start:
            result = backends.check_voicevox_watchdog_once()
        assert result is None
        mock_stop.assert_not_called()
        mock_start.assert_not_called()
    finally:
        lock.release()


def test_stop_failure_does_not_attempt_start(tmp_path, monkeypatch):
    _write_pid_file(tmp_path, monkeypatch, time.time())
    with patch.object(backends, "is_voicevox_running", return_value=True), \
         patch.object(backends, "_voicevox_process_memory_mb", return_value=8000.0), \
         patch.object(backends, "stop_voicevox", return_value="taskkill failed") as mock_stop, \
         patch.object(backends, "start_voicevox") as mock_start:
        result = backends.check_voicevox_watchdog_once()
    assert result is None
    mock_stop.assert_called_once()
    mock_start.assert_not_called()


def test_memory_probe_failure_falls_back_to_uptime_only(tmp_path, monkeypatch):
    """psutil未導入・対象PID消滅等でメモリが取得できない場合はfail-open
    (Noneとして扱い、uptime判定のみ有効)。"""
    _write_pid_file(tmp_path, monkeypatch, time.time())
    with patch.object(backends, "is_voicevox_running", return_value=True), \
         patch.object(backends, "_voicevox_process_memory_mb", return_value=None), \
         patch.object(backends, "stop_voicevox") as mock_stop, \
         patch.object(backends, "start_voicevox") as mock_start:
        result = backends.check_voicevox_watchdog_once()
    assert result is None
    mock_stop.assert_not_called()
    mock_start.assert_not_called()
