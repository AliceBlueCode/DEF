"""def_kari/safety/audit_log.py の単体テスト（9章 Layer 3: 監査ログ・サーキットブレーカー）。"""

import json
import time
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolate_audit_log(tmp_path):
    """テスト間で _violations（グローバルdeque）とファイルハンドラの向き先が汚染されないようにする。

    _ensure_handler() は「一度ハンドラが付いたら以降は何もしない」実装のため、実ログ
    （data/private/logs/audit.log）を汚さないよう、テストのたびにハンドラを外して
    tmp_path 配下を向く新しいハンドラを作らせる。
    """
    from def_kari.safety import audit_log
    audit_log._violations.clear()
    audit_log._audit_logger.handlers.clear()
    audit_log._handler_ready = False
    with patch.object(audit_log, "_LOG_DIR", tmp_path / "logs"):
        yield
    audit_log._violations.clear()
    audit_log._audit_logger.handlers.clear()
    audit_log._handler_ready = False


def test_record_generation_event_writes_json_line(tmp_path):
    from def_kari.safety import audit_log
    audit_log.record_generation_event("generate_session_image", "sid-1", "203.0.113.5", "jti-1")
    log_file = audit_log._LOG_DIR / "audit.log"
    assert log_file.exists()
    line = log_file.read_text(encoding="utf-8").strip().splitlines()[-1]
    entry = json.loads(line)
    assert entry["type"] == "generation"
    assert entry["event"] == "generate_session_image"
    assert entry["session_id"] == "sid-1"
    assert entry["ip"] == "203.0.113.5"
    assert entry["jti"] == "jti-1"
    assert "ts" in entry


def test_record_rate_limit_violation_below_threshold_returns_false():
    from def_kari.safety import audit_log
    for _ in range(9):
        assert audit_log.record_rate_limit_violation("vote_deliberate", "sid-2", "203.0.113.5", "jti-2") is False


def test_record_rate_limit_violation_trips_at_threshold():
    """5分間に10回で閾値到達、10回目でTrue（サーキットブレーカー作動シグナル）を返すこと。"""
    from def_kari.safety import audit_log
    results = [
        audit_log.record_rate_limit_violation("vote_deliberate", "sid-3", "203.0.113.5", "jti-3")
        for _ in range(10)
    ]
    assert results[:9] == [False] * 9
    assert results[9] is True


def test_record_rate_limit_violation_old_entries_pruned_from_window():
    """ウィンドウ外(5分より前)の違反はカウントされないこと。"""
    from def_kari.safety import audit_log
    old_time = time.time() - 999
    audit_log._violations["sid-4"].extend([old_time] * 9)
    # 9件は古いので、新しい1件が積まれても合計10件と数えず False のまま
    assert audit_log.record_rate_limit_violation("vote_commit", "sid-4", "203.0.113.5", "jti-4") is False


def test_record_rate_limit_violation_independent_per_session():
    from def_kari.safety import audit_log
    for _ in range(9):
        audit_log.record_rate_limit_violation("vote_deliberate", "sid-5a", "203.0.113.5", "jti-5")
    # 別セッションのカウントには影響しない
    assert audit_log.record_rate_limit_violation("vote_deliberate", "sid-5b", "203.0.113.6", "jti-6") is False


def test_reset_violations_clears_counter():
    from def_kari.safety import audit_log
    for _ in range(9):
        audit_log.record_rate_limit_violation("vote_deliberate", "sid-6", "203.0.113.5", "jti-7")
    audit_log.reset_violations("sid-6")
    # リセット後は9回分が消えているので、続けて9回叩いてもまだ閾値未到達
    for _ in range(9):
        assert audit_log.record_rate_limit_violation("vote_deliberate", "sid-6", "203.0.113.5", "jti-7") is False
