"""生成リクエストの監査ログ（9章 Layer 3、`DEF_kari_セキュリティ設計書_内部用.md` 9.3参照）。

IP・session_id・jti・タイムスタンプを紐づけて記録する。コスト面の異常検知だけでなく、
9.5で述べる名誉毀損リスクにおいて「これは第三者による無断アクセスの結果であり、自分の
行為ではない」とホストが事後に客観的に示すための唯一の実効的な防御線でもある。
"""

import json
import logging
import time
from collections import defaultdict, deque
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_BASE = Path(__file__).parent.parent.parent
_LOG_DIR = _BASE / "data" / "private" / "logs"

# 構造化JSON専用ロガー。会話断片等は含まないが念のためdata/private/配下に置く
# （main.pyのdef.logと同じ規約）。ルートロガーへは伝播させず、コンソール等に
# 生JSONが混ざらないようにする。
_audit_logger = logging.getLogger("def.audit")
_audit_logger.propagate = False

# ホストへの即時通知用。こちらは伝播させ、main.pyが設定するコンソール＋def.logの
# 両方に出す（設計書9.3「ログファイルへのWARNING出力等」に対応）。
_alert_logger = logging.getLogger("def.audit.alert")

# 名誉毀損リスク等の事後証跡としての性質上、通常のアプリログ（14日）より長く保持する
_BACKUP_COUNT_DAYS = 90


_handler_ready = False


def _ensure_handler() -> None:
    """一度だけファイルハンドラを付ける。

    `_audit_logger.handlers`の空/非空で判定しない: pytestは`propagate=False`の
    ロガー全てに自前のLogCaptureHandlerを差し込むため（`_pytest.logging.catching_logs`）、
    テスト実行下では常に非空になり判定が壊れる。専用フラグで管理する。
    """
    global _handler_ready
    if _handler_ready:
        return
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = TimedRotatingFileHandler(
        _LOG_DIR / "audit.log", when="midnight", backupCount=_BACKUP_COUNT_DAYS, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _audit_logger.addHandler(handler)
    _audit_logger.setLevel(logging.INFO)
    _handler_ready = True


def _write(entry: dict) -> None:
    _ensure_handler()
    try:
        _audit_logger.info(json.dumps(entry, ensure_ascii=False))
    except Exception:
        pass


def record_generation_event(event: str, session_id: str, ip: str, jti: str) -> None:
    """生成トリガー系エンドポイント（vote/deliberate・vote/commit・generate-image・
    human_turn）が全チェックを通過し、実際にLLM/T2I呼び出しへ進む直前に呼ぶ。"""
    _write({
        "ts": time.time(),
        "type": "generation",
        "event": event,
        "session_id": session_id,
        "ip": ip,
        "jti": jti,
    })


_VIOLATION_WINDOW_SEC = 300  # 5分
_VIOLATION_THRESHOLD = 10  # 5分間に10回レート制限で弾かれたらサーキットブレーカー作動
_violations: dict[str, deque] = defaultdict(deque)


def record_rate_limit_violation(event: str, session_id: str, ip: str, jti: str) -> bool:
    """レート制限（jti単位・IP単位・1日上限のいずれか）で弾かれたリクエストを記録する。

    短時間に閾値を超えて弾かれ続けた場合はサーキットブレーカーを作動させるべき
    シグナルとしてTrueを返す（呼び出し元がセッションに`circuit_broken`フラグを立てる）。
    「正規参加者がたまたま数回レート制限に触れた」程度では作動しない、意図的な連打の
    継続だけを拾う閾値。
    """
    now = time.time()
    _write({
        "ts": now,
        "type": "rate_limit_violation",
        "event": event,
        "session_id": session_id,
        "ip": ip,
        "jti": jti,
    })
    q = _violations[session_id]
    q.append(now)
    while q and now - q[0] > _VIOLATION_WINDOW_SEC:
        q.popleft()
    if len(q) >= _VIOLATION_THRESHOLD:
        reason = f"{len(q)} rate-limit violations within {_VIOLATION_WINDOW_SEC}s (latest: {event} from ip={ip})"
        _write({"ts": now, "type": "circuit_breaker_tripped", "session_id": session_id, "reason": reason})
        _alert_logger.warning("[audit] session %s: circuit breaker tripped - %s", session_id, reason)
        q.clear()
        return True
    return False


def reset_violations(session_id: str) -> None:
    """ホストが手動でサーキットブレーカーを解除した際、違反カウントも一緒にクリアする。"""
    _violations.pop(session_id, None)
