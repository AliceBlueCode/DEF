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


# 本体の手元のバックエンドの向け先（def_kari/backends.py と同じ環境変数と既定値）
_LOCAL_URL_ENV = {
    "textgen_webui": ("TEXTGEN_WEBUI_URL", "http://127.0.0.1:5000/v1"),
    "ollama": ("OLLAMA_URL", "http://localhost:11434"),
    "voicevox": ("VOICEVOX_URL", "http://127.0.0.1:50021"),
    "irodori": ("IRODORI_TTS_URL", "http://127.0.0.1:8088"),
    "kokoro": ("KOKORO_TTS_URL", "http://127.0.0.1:8766"),
    "a1111": ("A1111_URL", "http://localhost:7860"),
    "comfyui": ("COMFYUI_URL", "http://127.0.0.1:8188"),
}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}


def _points_to_this_machine(backend_id: str) -> bool:
    import os
    from urllib.parse import urlparse
    env, default = _LOCAL_URL_ENV.get(backend_id, ("", ""))
    url = os.environ.get(env, default) if env else ""
    host = (urlparse(url).hostname or "").lower()
    return host in _LOOPBACK_HOSTS or host.startswith("127.")


def _is_ollama_cloud_model(model: str) -> bool:
    """Ollama のクラウドのモデル（手元の Ollama を経由して、外のサーバーで動く）。名前が -cloud で終わる。"""
    m = (model or "").lower()
    return m.endswith("-cloud") or m.endswith(":cloud")


def is_local(kind: str, backend_id: str, model: str = "") -> bool:
    """このバックエンドが、この機械の中だけで動くか（B-021）。

    - 互換バックエンドの定義に同じ名前があれば、その「手元」の印を先に見る（実装レビュー2の🔴2。
      以前は名前が本体と同じなら、印が無くても手元とみなしていた）。
    - 本体の手元のバックエンドは、向け先の URL がこの機械（ループバック）のときだけ手元とする（🟡1）。
      LAN の別の機械も外部として扱う。
    - Ollama のクラウドのモデルは、向け先が手元でも外部として扱う。
    """
    try:
        from def_kari.compatible_backends_store import has_backend, is_local_backend
        if has_backend(backend_id):
            return is_local_backend(backend_id)
    except Exception:
        return False
    if backend_id not in LOCAL_BACKENDS.get(kind, frozenset()):
        return False
    if not _points_to_this_machine(backend_id):
        return False
    if backend_id == "ollama":
        if not model:
            try:
                from def_kari.llm.backend import LLM_BACKENDS
                model = LLM_BACKENDS.get("ollama", {}).get("default_model", "")
            except Exception:
                model = ""
        if _is_ollama_cloud_model(model):
            return False
    return True


def refusal(session: dict | None, kind: str, backend_id: str, model: str = "") -> str | None:
    """送ってはいけないなら、その理由。送ってよいなら None。"""
    if not isinstance(session, dict) or not backend_id:
        return None
    rulebook_id = session.get("trpg_rulebook", "") or ""
    scenario_id = session.get("trpg_scenario", "") or ""
    if not rulebook_id and not scenario_id:
        return None
    if is_local(kind, backend_id, model):
        return None
    from def_kari.trpg import resources
    # 卓を作ったときに固定したルールシステムも渡す。ルールブックが読めなくても、閉じる側に倒れる（🔴1）
    perms = resources.table_permissions(rulebook_id, scenario_id, session.get("trpg_rule_system") or None)
    if perms["external_services_allowed"]:
        return None
    if perms.get("missing"):
        return (f"{kind} backend {backend_id!r} is an external service, and this table's rules cannot be "
                f"checked ({'; '.join(perms['missing'])}), so nothing is sent outside")
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


def check(session: dict | None, kind: str, backend_id: str, model: str = "") -> None:
    """送ってはいけないなら、ホストに知らせて `ExternalServiceRefused` を出す。"""
    reason = refusal(session, kind, backend_id, model)
    if reason:
        _notify(session, kind, backend_id, reason)
        raise ExternalServiceRefused(reason)


def allowed(session: dict | None, kind: str, backend_id: str, model: str = "") -> bool:
    """送ってよいか。いけないなら、ホストに知らせて False（読み上げ・挿絵のように、黙って飛ばす所用）。"""
    reason = refusal(session, kind, backend_id, model)
    if reason:
        _notify(session, kind, backend_id, reason)
        return False
    return True
