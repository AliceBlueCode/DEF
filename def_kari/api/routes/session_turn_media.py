"""ターン結果の挿絵・TTS自動生成、および人間プレイヤー発言のTTSバックグラウンド合成。

`session_turn_engine.py`の一部だったが、いずれもターン進行ロジック（_run_ai_turns等）
への依存を持たない自己完結した生成ヘルパーのため独立モジュール化した
（TODO.md「session_turn_engine.pyのさらなる分割」参照）。呼び出し側
（_run_ai_turns・human_turn_action、いずれもsession_turn_engine.py）からは
一方向にimportされるだけで、このモジュール自身はturn_engine側の関数を一切呼ばない。
"""

import logging
import threading
import uuid as _uuid_mod
from pathlib import Path

from def_kari.gm.events import game_event_bus as _game_event_bus
from def_kari.settings import load_settings
from def_kari.t2i.backend import generate_image as _generate_t2i_image

_log = logging.getLogger("def.session")


def _synthesize_turn_audio_sync(text: str, character_id: str, tts_backend: str) -> str:
    """テキストをTTS合成してassets/に保存し、配信用URLを返す（同期・fail-silent）。

    呼び出し元は必ずバックグラウンドスレッド（_generate_turn_audio /
    _synthesize_and_notify_audio）経由で呼ぶこと。リクエストハンドラから直接
    同期呼び出しすると、TTSバックエンドが無応答の場合にHTTPレスポンスごと
    ブロックされる（2026-08-02、human_turn_actionでの実装ミスで発覚）。
    """
    if not tts_backend or not text:
        return ""
    try:
        from def_kari.api.routes.tts import synthesize_and_save
        from def_kari.api.routes.session_turn_engine import _VRAM_LOCK_TIMEOUT_SECONDS
        from def_kari.resources.vram_lock import get_vram_lock
        lock = get_vram_lock()
        if not lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
            _log.warning("vram_lock busy for over %.0fs, skipping TTS synthesis", _VRAM_LOCK_TIMEOUT_SECONDS)
            return ""
        try:
            return synthesize_and_save(text, character_id, tts_backend)
        finally:
            lock.release()
    except Exception:
        return ""


def _generate_turn_image(session_id: str, result: dict) -> None:
    """AIターン結果の image_prompt_en から挿絵をバックグラウンド生成し、TURN_IMAGE_READY をemitする（fail-silent）。

    従来は各クライアントが個別に POST /api/t2i/ を叩いていたが、それだと画像生成という
    重い操作を無認証で外部公開する必要が生じてしまう。サーバー側で1回だけ生成してWS配信する
    ことで、参加者側は読み取り専用の /api/t2i/image/{filename} だけで済むようにする。
    """
    try:
        image_prompt_en = result.get("image_prompt_en", "")
        if not image_prompt_en:
            return
        settings = load_settings()
        backend = settings.get("t2i_backend", "")
        if not backend:
            return
        model = settings.get(f"t2i_model_{backend}") or None
        from def_kari.api.routes.session_turn_engine import _VRAM_LOCK_TIMEOUT_SECONDS
        from def_kari.resources.vram_lock import get_vram_lock
        lock = get_vram_lock()
        if not lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
            _log.warning("vram_lock busy for over %.0fs, skipping turn image generation", _VRAM_LOCK_TIMEOUT_SECONDS)
            return
        try:
            image_path = _generate_t2i_image(prompt=image_prompt_en, backend=backend, model=model)
        finally:
            lock.release()
        filename = Path(image_path).name
        url = f"/api/t2i/image/{filename}"
        _game_event_bus.emit(session_id, "TURN_IMAGE_READY", {
            "character_id": result.get("character_id", ""),
            "round": result.get("round"),
            "turn": result.get("turn"),
            "url": url,
        })
    except Exception as e:
        _log.warning("turn image generation failed for session=%s: %s", session_id, e)


def _generate_turn_audio(session_id: str, result: dict) -> None:
    """AIターン結果のテキストをバックグラウンドでTTS合成し、TURN_AUDIO_READY をemitする（fail-silent）。

    従来は各クライアントが個別に POST /api/tts/ → POST /api/tts/save を叩いていたが、
    それだと音声合成という重い操作を無認証で外部公開する必要が生じてしまう。
    サーバー側で1回だけ合成してWS配信する方式に統一した。

    tts_enabled設定がOFFの場合は生成自体をスキップする（以前は常に生成し
    クライアント側の再生可否のみで制御していたため、誰も聴かない音声を
    毎ターンvram_lockを使って合成し続ける無駄があった、2026-08-10発覚）。
    """
    try:
        settings = load_settings()
        if not settings.get("tts_enabled", True):
            return
        tts_backend = settings.get("tts_backend", "")
        url = _synthesize_turn_audio_sync(result.get("text", ""), result.get("character_id", ""), tts_backend)
        if not url:
            return
        _game_event_bus.emit(session_id, "TURN_AUDIO_READY", {
            "character_id": result.get("character_id", ""),
            "round": result.get("round"),
            "turn": result.get("turn"),
            "url": url,
        })
    except Exception as e:
        _log.warning("turn audio generation failed for session=%s: %s", session_id, e)


def _maybe_generate_turn_media(session_id: str, result: dict) -> None:
    """AIターン完了後の挿絵・TTSをそれぞれ独立したデーモンスレッドでバックグラウンド生成する。

    _run_ai_turns から AI_TURN_COMPLETED emit直後に呼ばれる。参加処理と同様、
    生成の成否に関わらずターン進行はブロックしない（fail-silent）。

    挿絵の自動生成はsession_auto_illustrate設定（デフォルトOFF）でオプトイン。
    OFF時は作画ボタン（generate_session_image、発言力消費・認証済み）のみで
    生成する。TTSは対象外（別軸のまま常時自動生成）。
    """
    if load_settings().get("session_auto_illustrate", False):
        threading.Thread(target=_generate_turn_image, args=(session_id, result), daemon=True).start()
    threading.Thread(target=_generate_turn_audio, args=(session_id, result), daemon=True).start()


def _synthesize_and_notify_audio(session_id: str, text: str, character_id: str, request_id: str) -> None:
    """バックグラウンドでTTS合成し、完了したら AUDIO_READY イベントをemitする（fail-silent）。

    human_turn_action（人間プレイヤー自己発言）・vote_deliberate（弁明ラウンド）が使う汎用版。
    AIターン自動読み上げ専用の _generate_turn_audio とは別に、character_id + request_id で
    紐付ける（呼び出し元ごとにレスポンス形状が異なり round/turn を持たないため）。
    """
    try:
        tts_backend = load_settings().get("tts_backend", "")
        url = _synthesize_turn_audio_sync(text, character_id, tts_backend)
        if not url:
            return
        _game_event_bus.emit(session_id, "AUDIO_READY", {
            "character_id": character_id,
            "request_id": request_id,
            "url": url,
        })
    except Exception as e:
        _log.warning("audio synth failed for session=%s: %s", session_id, e)


def _start_background_tts(session_id: str, text: str, character_id: str) -> str:
    """TTS合成をバックグラウンドスレッドで起動し、呼び出し元に返すrequest_idを発行する。

    人間プレイヤー自身の発言（human_turn_action・vote_deliberate・vote_proposal）に使う。
    text が空、tts_human_enabled設定がOFF（デフォルトOFF）、またはTTSバックエンド
    未設定の場合は空文字列を返しスレッドは起動しない
    （呼び出し元はaudio_request_idが空なら音声なしとして扱う）。
    """
    settings = load_settings()
    if not text or not settings.get("tts_human_enabled", False) or not settings.get("tts_backend", ""):
        return ""
    request_id = _uuid_mod.uuid4().hex[:12]
    threading.Thread(
        target=_synthesize_and_notify_audio,
        args=(session_id, text, character_id, request_id),
        daemon=True,
    ).start()
    return request_id
