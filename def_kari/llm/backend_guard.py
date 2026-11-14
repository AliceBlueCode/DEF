"""外部のサービスへの送信の確かめ（マルチルールブック基盤 B-021・B-025、基本設計書 11.4・11.6）。

ルールブックの manifest が外部への送信を許さない卓では、外部の LLM・読み上げ（TTS）・画像生成（T2I）に
送らない。送る直前に `check()`（断るときは例外）か `allowed()`（断るときは False）を呼ぶ。確かめる
処理はここ1か所にまとめ、呼ぶ所はセッションと GM のコードの中で LLM・TTS・T2I を直接呼ぶ関数すべて
（`tests/test_backend_guard_coverage.py` が呼び忘れを機械的に探す）。

- 手元のバックエンド: LLM は textgen_webui・ollama、TTS は voicevox・irodori・kokoro、T2I は a1111・comfyui。
  互換バックエンドは、設定の画面で「手元で動いている」の印（`local: true`）を付けたものだけ。印の無い
  ものは外部として扱う（B-021）。
- 断ったら、何をなぜ断ったかをホスト（とGM）に知らせる。別のバックエンドに黙って切り替えない（B-021）。
- manifest はホストの手元のファイルなので、これはうっかり送る事故を防ぐ仕組みで、強制ではない。
- TRPG の卓でない（ルールブックもシナリオも無い）セッションは、確かめない。
"""

import logging
import threading

_log = logging.getLogger("def.trpg")

LOCAL_BACKENDS: dict[str, frozenset[str]] = {
    "llm": frozenset({"textgen_webui", "ollama"}),
    "tts": frozenset({"voicevox", "irodori", "kokoro"}),
    "t2i": frozenset({"a1111", "comfyui"}),
}


class ExternalServiceRefused(RuntimeError):
    """manifest が外部への送信を許さない卓で、外部のバックエンドを使おうとした。"""


def is_local(kind: str, backend_id: str) -> bool:
    if backend_id in LOCAL_BACKENDS.get(kind, frozenset()):
        return True
    try:
        from def_kari.compatible_backends_store import is_local_backend
        return is_local_backend(backend_id)
    except Exception:
        return False


def refusal(session: dict | None, kind: str, backend_id: str) -> str | None:
    """送ってはいけないなら、その理由。送ってよいなら None。"""
    if not isinstance(session, dict) or not backend_id:
        return None
    rulebook_id = session.get("trpg_rulebook", "") or ""
    scenario_id = session.get("trpg_scenario", "") or ""
    if not rulebook_id and not scenario_id:
        return None
    if is_local(kind, backend_id):
        return None
    from def_kari.trpg import resources
    if resources.table_permissions(rulebook_id, scenario_id)["external_services_allowed"]:
        return None
    return (f"{kind} backend {backend_id!r} is an external service, and this table's rulebook does not "
            f"allow sending to external services")


_notified: dict[str, set] = {}
_notified_lock = threading.Lock()


def _notify(session: dict, kind: str, backend_id: str, reason: str) -> None:
    """ホストとGMに知らせる（同じ卓・同じバックエンドは1回だけ）。"""
    session_id = session.get("id", "")
    _log.warning("[trpg] refused %s backend %s for session %s: %s", kind, backend_id, str(session_id)[:8], reason)
    with _notified_lock:
        seen = _notified.setdefault(session_id, set())
        if (kind, backend_id) in seen:
            return
        seen.add((kind, backend_id))
    try:
        from def_kari.gm.events import game_event_bus
        game_event_bus.emit(session_id, "EXTERNAL_SERVICE_REFUSED", {
            "kind": kind, "backend": backend_id, "reason": reason, "gm_only": True,
        })
    except Exception as e:
        _log.warning("[trpg] could not notify the host: %s", e)


def check(session: dict | None, kind: str, backend_id: str) -> None:
    """送ってはいけないなら、ホストに知らせて `ExternalServiceRefused` を出す。"""
    reason = refusal(session, kind, backend_id)
    if reason:
        _notify(session, kind, backend_id, reason)
        raise ExternalServiceRefused(reason)


def allowed(session: dict | None, kind: str, backend_id: str) -> bool:
    """送ってよいか。いけないなら、ホストに知らせて False（読み上げ・挿絵のように、黙って飛ばす所用）。"""
    reason = refusal(session, kind, backend_id)
    if reason:
        _notify(session, kind, backend_id, reason)
        return False
    return True
