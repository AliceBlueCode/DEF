"""Session永続化: シリアライズ・autosave・visitor永続化・episodic memory保存・
保存済みセッションのload/save/list/delete。`session.py`分割の一部。
"""

import datetime
import json
import logging
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from fastapi import Body, Depends
from pydantic import BaseModel, field_validator

from def_kari.characters import load_profiles, get_character
from def_kari.history.store import save_session_mode, list_session_mode_files
from def_kari.llm.backend import DEFAULT_LLM_BACKEND
from def_kari.llm import backend_guard as _backend_guard
from def_kari.gm.context_builder import load_trpg_scenario as _load_trpg_scenario
from def_kari.trpg import resources as _trpg_resources
from def_kari.settings import load_settings
from def_kari.prompts import sp as _sp
from def_kari.t2i.backend import generate_image as _generate_t2i_image
from def_kari.gm.events import game_event_bus as _game_event_bus

from def_kari.api.routes.session_state import (
    router,
    local_router,
    _sessions,
    _last_session_debug,
    _MAX_SESSIONS,
    _session_for_json,
)
from def_kari.api.routes.session_auth import issue_player_jwt, _evict_oldest_session, require_keeper
from def_kari.api.routes.session_rules import _load_session_rules

_log = logging.getLogger("def.session")

_VRAM_LOCK_TIMEOUT_SECONDS = float(os.environ.get("DEF_VRAM_LOCK_TIMEOUT", "60"))

_BASE = Path(__file__).parent.parent.parent.parent
# 書き込むデータは def_kari.runtime_paths の置き場所（テストでは一時ディレクトリ）
from def_kari.runtime_paths import writable_data_dir as _writable_data_dir
_DATA_W = _writable_data_dir()
_SESSION_HISTORY_DIRS = [
    _DATA_W / "public" / "session_history",
    _DATA_W / "private" / "session_history",
]
_AUTOSAVE_DIR = _DATA_W / "private" / "session_autosave"
_VISITORS_DIR = _DATA_W / "visitors"
_VISITORS_MAX_FILES = 5000  # 新規ディレクトリ作成時のみ判定。既存の上書き更新は無制限
_SAFE_FILENAME_RE = re.compile(r'^[A-Za-z0-9_\-]+\.json$')


def _table_keeps_content_inside(session: dict) -> bool:
    """外部への送信を許さない卓か（ルールブック・シナリオ・プラグインの manifest。B-021）。"""
    if not (session.get("trpg_rulebook") or session.get("trpg_scenario")):
        return False
    perms = _trpg_resources.table_permissions(session.get("trpg_rulebook", ""), session.get("trpg_scenario", ""),
                                              session.get("trpg_rule_system") or None)
    return not perms["external_services_allowed"]


def _save_session_episodic(session_id: str, session: dict) -> None:
    """セッション終了時に各キャラクターの episodic memory を書き込む。"""
    # 外部への送信を許さない卓の中身は、キャラの記憶に書かない。記憶は後の別の卓で読まれ、外部の LLM に
    # 送られうるため（B-021・B-025。実装レビュー2の🟡2、2026-11-14 決定）
    if _table_keeps_content_inside(session):
        _log.info("[memory] session %s: not saved (this table does not allow sending outside)", str(session_id)[:8])
        return
    try:
        from def_kari.gm.memory import save_episodic
    except ImportError:
        return

    history = session.get("history", [])
    name_map = session.get("name_map", {})
    topic = session.get("topic", "")
    round_count = session.get("round", 1)
    all_char_ids = session.get("initiative", [])
    ts = datetime.datetime.now().isoformat()

    for char_id in all_char_ids:
        # このキャラの assistant 発言から key_moments を抽出（最後の3件）
        char_lines = [
            h["content"].split(": ", 1)[-1]
            for h in history
            if h.get("role") == "assistant" and h.get("character_id") == char_id
        ]
        key_moments = char_lines[-3:] if char_lines else []

        # 最後の感情状態
        emotion_at_end = next(
            (h.get("emotion", "neutral") for h in reversed(history)
             if h.get("character_id") == char_id and h.get("emotion")),
            "neutral",
        )

        entry = {
            "session_id": session_id,
            "date": ts,
            "topic": topic,
            "round_count": round_count,
            "participants": [name_map.get(c, c) for c in all_char_ids if c != char_id],
            "key_moments": key_moments,
            "emotion_at_end": emotion_at_end,
        }
        save_episodic(char_id, entry)


def _autosave_visitors(session: dict) -> None:
    """guest_chars（持ち込みキャラ）を data/visitors/{char_id}/profile.json に書き出す。

    join直後と _autosave() の両方から呼ばれる（べき等・上書き）。ディレクトリ形式にしているのは
    def_kari/gm/memory.py の _char_base_dir() がそのまま visitors/{char_id}/ を認識できるようにするため
    （episodic memory 対応、guest_id は毎回使い捨てなので次回セッションへの引き継ぎはされない）。
    """
    guest_chars = session.get("guest_chars", {})
    if not guest_chars:
        return
    try:
        _VISITORS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    existing_count = None  # 新規ディレクトリ作成が発生したときだけ遅延評価する
    skill_values = session.get("skill_values", {})
    runtime_stats = session.get("runtime_stats", {})
    counters = session.get("counters", {})
    for char_id, char_data in guest_chars.items():
        char_dir = _VISITORS_DIR / char_id
        if not char_dir.exists():
            if existing_count is None:
                existing_count = sum(1 for _ in _VISITORS_DIR.iterdir() if _.is_dir())
            if existing_count >= _VISITORS_MAX_FILES:
                _log.warning("visitors/ cap (%d) reached, skipping new visitor dir for %s", _VISITORS_MAX_FILES, char_id)
                continue
            existing_count += 1
        snapshot = dict(char_data)
        if char_id in skill_values:
            snapshot["_session_skill_values"] = skill_values[char_id]
        if char_id in runtime_stats:
            snapshot["_session_runtime_stats"] = runtime_stats[char_id]
        if char_id in counters:
            snapshot["_session_counter"] = counters[char_id]
        try:
            char_dir.mkdir(parents=True, exist_ok=True)
            (char_dir / "profile.json").write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass


def _extract_appearance_tags(character_json: dict) -> str:
    """flat形式・versioned形式（base_profile入れ子）の両方から appearance_tags（無ければ features）を取り出す。"""
    if not isinstance(character_json, dict):
        return ""
    for v in character_json.values():
        if isinstance(v, dict) and isinstance(v.get("base_profile"), dict):
            bp = v["base_profile"]
            vr = bp.get("visual_references") or {}
            return bp.get("appearance_tags") or vr.get("appearance_tags") or vr.get("features") or ""
    vr = character_json.get("visual_references") or {}
    return character_json.get("appearance_tags") or vr.get("appearance_tags") or vr.get("features") or ""


def _generate_visitor_images(session_id: str, char_id: str, character_json: dict) -> None:
    """持ち込みキャラのアイコン・立ち絵をバックグラウンドで生成する（fail-silent）。

    join_session からデーモンスレッドで起動され、参加処理の完了はこれを待たない。
    生成完了時に VISITOR_ICON_READY をemitし、フロントにアイコン再取得を促す
    （画像配信は _NO_CACHE_HEADERS 済みなので、フロント側は同URLを再フェッチするだけでよい）。
    """
    try:
        appearance_tags = _extract_appearance_tags(character_json)
        if not appearance_tags:
            return
        settings = load_settings()
        backend = settings.get("t2i_backend", "")
        if not backend:
            return
        # 外部への送信を許さない卓では、外部の画像生成に送らない（B-025）
        if not _backend_guard.allowed(_sessions.get(session_id), "t2i", backend):
            return
        model = settings.get(f"t2i_model_{backend}") or None
        char_dir = _VISITORS_DIR / char_id
        char_dir.mkdir(parents=True, exist_ok=True)

        from def_kari.resources.vram_lock import get_vram_lock
        lock = get_vram_lock()

        icon_prompt = f"portrait, face close-up, {appearance_tags}, white background, simple background"
        if not lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
            _log.warning("vram_lock busy for over %.0fs, skipping visitor icon generation", _VRAM_LOCK_TIMEOUT_SECONDS)
            return
        try:
            icon_path = _generate_t2i_image(prompt=icon_prompt, backend=backend, model=model, width=512, height=512)
        finally:
            lock.release()
        shutil.copy2(icon_path, char_dir / "icon.png")

        standing_prompt = f"full body, standing, {appearance_tags}, white background, simple background"
        if not lock.acquire(timeout=_VRAM_LOCK_TIMEOUT_SECONDS):
            _log.warning("vram_lock busy for over %.0fs, skipping visitor standing generation", _VRAM_LOCK_TIMEOUT_SECONDS)
            return
        try:
            standing_path = _generate_t2i_image(prompt=standing_prompt, backend=backend, model=model, width=832, height=1216)
        finally:
            lock.release()
        shutil.copy2(standing_path, char_dir / "standing.png")

        _game_event_bus.emit(session_id, "VISITOR_ICON_READY", {"character_id": char_id})
    except Exception as e:
        _log.warning("visitor image generation failed for %s: %s", char_id, e)


def _autosave(session_id: str) -> None:
    session = _sessions.get(session_id)
    if not session:
        return
    try:
        _AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
        (_AUTOSAVE_DIR / f"{session_id}.json").write_text(
            json.dumps(_session_for_json(session), ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass
    _autosave_visitors(session)
    _cleanup_stale_autosaves()


def _delete_autosave(session_id: str) -> None:
    try:
        (_AUTOSAVE_DIR / f"{session_id}.json").unlink(missing_ok=True)
    except Exception:
        pass


# autosaveファイルのTTL（この期間以上更新がなければ放置されたセッションとみなす）。
# _delete_autosave() はセッション正常終了時（/end 等）にしか呼ばれないため、プロセスの
# 異常終了やホストが /end を呼ばずに放置した場合、ファイルが際限なく溜まり続けていた
# （実測1752個）。
_AUTOSAVE_TTL_SEC = 7 * 24 * 3600.0  # 7日
_AUTOSAVE_CLEANUP_INTERVAL_SEC = 3600.0  # 稼働中の定期掃除の間隔（1時間）
# 0.0ではなく-infにする: time.monotonic()の基準点は不定（システム起動時刻等）で
# 「経過0秒」を意味しないため、0.0だと起動直後（システム稼働時間がこの間隔未満）の
# 環境（CIランナー等）で「まだ一度も実行していない」はずの初回呼び出しが誤って
# 間引かれてしまう。-infなら`now - (-inf)`が必ず間隔を超え、初回は確実に実行される。
_autosave_last_cleanup: dict[str, float] = {"t": float("-inf")}


def _cleanup_stale_autosaves() -> None:
    """_sessions に存在しない（＝終了済み・復元されなかった）セッションのうち、
    最終更新からTTLを超えたautosaveファイルを間引く。呼び出し頻度の高い
    _autosave() に軽量にフックし、一定間隔でのみ実際の掃除を行う
    （S-3の _cleanup_invite_rate_state と同じパターン）。
    """
    now = time.monotonic()
    if now - _autosave_last_cleanup["t"] < _AUTOSAVE_CLEANUP_INTERVAL_SEC:
        return
    _autosave_last_cleanup["t"] = now
    try:
        if not _AUTOSAVE_DIR.is_dir():
            return
        wall_now = time.time()
        for _f in _AUTOSAVE_DIR.iterdir():
            if _f.suffix != ".json" or _f.stem in _sessions:
                continue
            try:
                if wall_now - _f.stat().st_mtime > _AUTOSAVE_TTL_SEC:
                    _f.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


def _refund_proposer_counter(session: dict, pending_vote: dict | None) -> None:
    """流れた投票（取り消し・再起動）の発議者に、発議で消費した発言力を戻す。

    消費後に別の理由（キーパーの調整等）で増減していても失わないよう、0に戻した値を
    上書きするのではなく、消費した量を足し戻す。
    """
    if not pending_vote:
        return
    proposer_id = pending_vote.get("proposer_id")
    spent = pending_vote.get("proposer_counter_spent", 0)
    if proposer_id and proposer_id != "_keeper" and spent:
        counters = session.setdefault("counters", {})
        counters[proposer_id] = counters.get(proposer_id, 0) + spent


def _refund_unaccepted_ai_vote_proposal(session: dict) -> None:
    """受け付けられなかったAIの発議（_ai_vote_proposal が残ったまま）の発言力を戻し、記録を消す。

    AIの発議は行動選択の時点で発言力を消費して記録し、vote_deliberate が受け付けると記録を
    投票へ引き継ぐ。受け付けられなかった（キーパーのタブが無い・レート制限・失敗等）場合は
    記録が残り続け、発言力も戻らず、古い理由が後からそのAIの発言として使われ得た
    （2026-11-08レビュー指摘）。受け付けられなかった発議も「流れた」ものとして戻す。
    """
    proposal = session.pop("_ai_vote_proposal", None)
    if proposal:
        _refund_proposer_counter(session, {
            "proposer_id": proposal.get("proposer_id"), "proposer_counter_spent": proposal.get("spent", 0),
        })


def _note_pending_vote_dropped_on_restore(restored: dict, expel: dict | None) -> None:
    """復元時に捨てた投票・追放の決定待ちを、履歴に残す。

    黙って捨てると、可決済みの追放の対象が何事も無かったように発言でき、参加者には何が
    起きたか分からない（2026-11-08レビュー指摘）。文言は session_prompts.json で変えられる
    （vote_cancel と同じ仕組み）。想定外の形のファイル（historyがnull等）でも、通知の
    失敗でセッションごと復元できなくならないよう、ここだけで例外を握る。
    """
    try:
        lang = load_settings().get("user_language", "ja") or "ja"
        if expel:
            target = (restored.get("name_map") or {}).get(expel.get("target_id"), expel.get("target_id", ""))
            note = (_sp("expel_cancelled_by_restart_notice", lang) or (
                "🗳 The passed expulsion was cancelled because the server restarted ({name} stays in the session)"
                if lang == "en" else "🗳 サーバーの再起動のため、可決された退場の処理を取り消しました（{name} はセッションに残ります）"
            )).format(name=target)
        else:
            note = _sp("vote_cancelled_by_restart_notice", lang) or (
                "🗳 The pending vote was cancelled because the server restarted"
                if lang == "en" else "🗳 サーバーの再起動のため、保留中の投票を取り消しました"
            )
        if not isinstance(restored.get("history"), list):
            restored["history"] = []
        restored["history"].append({"role": "user", "content": note, "character_id": "_keeper"})
    except Exception:
        _log.warning("failed to note dropped pending vote for session %s", restored.get("id"), exc_info=True)


def _restore_one_autosave_file(f: Path, wall_now: float) -> None:
    """1件のautosaveファイルを復元する。TTLを超えて放置されたファイルは復元せず削除する。"""
    if f.suffix != ".json":
        return
    try:
        if wall_now - f.stat().st_mtime > _AUTOSAVE_TTL_SEC:
            f.unlink(missing_ok=True)
            return
        restored = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(restored, dict) and restored.get("id"):
            # ルールブックのルールシステムが使えない（プラグインが読み込まれていない）セッションは
            # 戻さない。def_original として遊ばせない。ファイルは消さずに残すので、プラグインを
            # 入れ直せば次の起動で戻る（B-002、基本設計書 11.6）。
            _unavailable = _trpg_resources.rulebook_unavailable_reason(restored.get("trpg_rulebook", ""))
            if _unavailable:
                _log.warning("[autosave] session %s not restored: %s", str(restored["id"])[:8], _unavailable)
                return
            # 投票中・追放の決定待ちのまま保存されていたら捨てる。確定や選択のUIはキーパーの
            # タブの状態にしか無く、再起動後には出せない。残すとターンの進行が止まったまま
            # 二度と進まなくなる（2026-11-08。投票の発言は履歴に残っている）。
            pending_vote = restored.pop("_pending_vote", None)
            expel = restored.pop("_pending_expel_followup", None)
            had_ai_proposal = "_ai_vote_proposal" in restored
            _refund_unaccepted_ai_vote_proposal(restored)
            _sessions[restored["id"]] = restored
            if had_ai_proposal and not (pending_vote or expel):
                _autosave(restored["id"])
            if pending_vote or expel:
                _refund_proposer_counter(restored, pending_vote)
                _note_pending_vote_dropped_on_restore(restored, expel)
                # 捨てた状態をすぐ保存し直す。しないと、何も操作しないまま再起動が続くたびに
                # 同じ待ち状態を捨て直し、通知が重複して入る（2026-11-08レビュー指摘）
                _autosave(restored["id"])
    except Exception:
        pass


# ── 起動時に進行中セッションを復元 ──────────────────────────────
try:
    if _AUTOSAVE_DIR.is_dir():
        _wall_now = time.time()
        for _f in sorted(_AUTOSAVE_DIR.iterdir()):
            _restore_one_autosave_file(_f, _wall_now)
except Exception:
    pass


# ── 保存済みセッション（ローカル専用） ────────────────────────────────

@local_router.get("/debug")
def get_session_debug():
    return _last_session_debug


@local_router.get("/saved")
def list_saved_sessions():
    files = list_session_mode_files()
    _rule_sets = _load_session_rules()
    result = []
    for f in files:
        meta = f.get("metadata", {})
        _rule_set_id = meta.get("rule_set", "")
        result.append({
            "filename": Path(f["path"]).name,
            "session_id": f["session_id"],
            "topic": meta.get("topic", ""),
            "saved_at": meta.get("saved_at", ""),
            "round": meta.get("round", 1),
            "character_names": list(meta.get("name_map", {}).values()),
            "trpg_scenario_title": meta.get("trpg_scenario_title", ""),
            "private": f.get("private", False),
            "rule_set": _rule_set_id,
            "rule_set_label": _rule_sets.get(_rule_set_id, {}).get("label", _rule_set_id),
            "online_mode": meta.get("online_mode", False),
        })
    result.sort(key=lambda x: x["saved_at"], reverse=True)
    return {"sessions": result}


class SessionLoadRequest(BaseModel):
    filename: str


@local_router.delete("/saved/{filename}")
def delete_saved_session(filename: str):
    if not _SAFE_FILENAME_RE.match(filename):
        return {"error": "Invalid filename"}
    for d in _SESSION_HISTORY_DIRS:
        path = d / filename
        if path.exists():
            try:
                path.unlink()
                return {"status": "ok"}
            except OSError as e:
                return {"error": str(e)}
    return {"error": "File not found"}


@local_router.post("/load")
def load_session(req: SessionLoadRequest):
    if not _SAFE_FILENAME_RE.match(req.filename):
        return {"error": "Invalid filename"}
    data = None
    for d in _SESSION_HISTORY_DIRS:
        path = d / req.filename
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                break
            except (json.JSONDecodeError, OSError):
                pass
    if data is None:
        return {"error": "File not found"}
    meta = data.get("metadata", {})
    # ルールブックのルールシステムが使えないセッションは読み込まず、何が足りないかを返す（B-002）
    _unavailable = _trpg_resources.rulebook_unavailable_reason(meta.get("trpg_rulebook", ""))
    if _unavailable:
        return {"error": _unavailable}
    _pinned_rs, _pinned_ver = meta.get("trpg_rule_system", ""), meta.get("trpg_plugin_version", "")
    if meta.get("trpg_rulebook") and not _pinned_rs:
        from def_kari.trpg import registry as _trpg_registry
        _pinned_rs, _pinned_ver = _trpg_registry.pin_for(_trpg_resources.load_rulebook(meta["trpg_rulebook"]))
    if _pinned_rs:
        from def_kari.trpg import registry as _trpg_registry
        _sys, _why = _trpg_registry.resolve_pinned(_pinned_rs, _pinned_ver)
        if _why:
            return {"error": _why}
    new_id = secrets.token_urlsafe(16)
    session = {
        "id": new_id,
        "initiative": meta.get("initiative", data.get("participants", [])),
        "name_map": meta.get("name_map", {}),
        "topic": meta.get("topic", ""),
        "backend": meta.get("backend", DEFAULT_LLM_BACKEND),
        "rule_set": meta.get("rule_set", "default"),
        "rules": meta.get("rules", []),
        "round": meta.get("round", 1),
        "turn": meta.get("turn", 0),
        "actions_per_turn": meta.get("actions_per_turn", 2),
        "action_count": 0,
        "history": data.get("history", []),
        "trpg_mode": meta.get("trpg_mode", False),
        "trpg_rulebook": meta.get("trpg_rulebook", ""),
        # 保存したときに固定していたルールシステムと版。古い保存には無いので、そのときはルールブックから決める（B-002）
        "trpg_rule_system": _pinned_rs,
        "trpg_plugin_version": _pinned_ver,
        "trpg_scenario": meta.get("trpg_scenario", ""),
        "char_game_sheets": meta.get("char_game_sheets", {}),
        "current_scene_index": meta.get("current_scene_index", 0),
        "runtime_stats": meta.get("runtime_stats", {}),
        "skill_pool": meta.get("skill_pool", {}),
        "skill_values": meta.get("skill_values", {}),
        "keeper_char_id": meta.get("keeper_char_id", ""),
        "keeper_char_name": meta.get("keeper_char_name", ""),
        "human_keeper": meta.get("human_keeper", False),
        # ── Phase 2: マルチプレイフィールド（ロード時は空で初期化）──
        "players": {},
        "host_token": "",
        "ws_connections": {},
        "ai_task": None,
        "idle_shutdown_task": None,
        "invite_codes": {},
        "ws_rate": {},
        "human_char_ids": meta.get("human_char_ids", []),
    }
    # ロードで復元されたセッションにも /start と同様にホストトークンを発行する。
    # 以前は host_token="" のままトークンを一切発行しておらず、GET /{session_id} の
    # 認証必須化（require_participant）でロード直後の履歴取得が401になるほか、
    # そもそも require_keeper/require_player 保護のセッション操作系（keeper発言・
    # ダイス等）にロード済みセッションから到達する手段が無かった。
    host_token = issue_player_jwt(new_id, "host")
    session["host_token"] = host_token
    session["players"][host_token] = ""  # ホストはキャラなし（/startと同じ扱い）
    if len(_sessions) >= _MAX_SESSIONS:
        _evict_oldest_session()
    _sessions[new_id] = session
    return {
        "session_id": new_id,
        "host_token": host_token,
        "initiative": session["initiative"],
        "round": session["round"],
        "topic": session["topic"],
        "name_map": session["name_map"],
        "history": session["history"],
        "actions_per_turn": session["actions_per_turn"],
        "trpg_mode": session["trpg_mode"],
        "trpg_rulebook": session.get("trpg_rulebook", ""),
        "char_game_sheets": session["char_game_sheets"],
        "runtime_stats": session["runtime_stats"],
        "current_scene_index": session.get("current_scene_index", 0),
        "human_keeper": session.get("human_keeper", False),
    }


class SaveSessionMediaItem(BaseModel):
    index: int
    image_url: str = ""
    audio_url: str = ""

    @field_validator("image_url", "audio_url")
    @classmethod
    def _validate_media_url(cls, v: str) -> str:
        """8.20対策: image_url/audio_urlは自サーバーの配信エンドポイントのみ許可する。

        以前はURL形式・オリジンの検証が一切無く、フロント（ChatTab.tsx/SessionTab.tsx）が
        <img src>/<audio src>にそのまま使うため、外部URLを仕込まれると読み込み時点で
        閲覧者のIPアドレス・User-Agentが漏れる。GM/ホスト権限（require_keeper）を持つ
        参加者（あるいはそのトークンを奪われた場合）が他の全参加者に仕込める経路だった。
        """
        if v and not v.startswith(("/api/t2i/image/", "/api/tts/audio/")):
            raise ValueError("image_url/audio_url must point to this server's own media endpoints")
        return v

class SaveSessionRequest(BaseModel):
    media: list[SaveSessionMediaItem] = []


@router.post("/{session_id}/save")
def save_session(session_id: str, req: SaveSessionRequest = Body(default=SaveSessionRequest()), _auth: dict = Depends(require_keeper)):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    history = session.get("history", [])
    for item in req.media:
        if 0 <= item.index < len(history):
            if item.image_url:
                history[item.index]["image_url"] = item.image_url
            if item.audio_url:
                history[item.index]["audio_url"] = item.audio_url

    metadata = {
        "topic": session.get("topic", ""),
        "backend": session.get("backend", ""),
        "rule_set": session.get("rule_set", ""),
        "online_mode": session.get("online_mode", False),
        "rules": session.get("rules", []),
        "round": session.get("round", 1),
        "turn": session.get("turn", 0),
        "initiative": session.get("initiative", []),
        "name_map": session.get("name_map", {}),
        "actions_per_turn": session.get("actions_per_turn", 2),
        "saved_at": datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
        "trpg_mode": session.get("trpg_mode", False),
        "trpg_rulebook": session.get("trpg_rulebook", ""),
        "trpg_rule_system": session.get("trpg_rule_system", ""),
        "trpg_plugin_version": session.get("trpg_plugin_version", ""),
        "trpg_scenario": session.get("trpg_scenario", ""),
        "trpg_scenario_title": _load_trpg_scenario(session.get("trpg_scenario", "")).get("title", "") if session.get("trpg_scenario") else "",
        "char_game_sheets": session.get("char_game_sheets", {}),
        "current_scene_index": session.get("current_scene_index", 0),
        "runtime_stats": session.get("runtime_stats", {}),
        "skill_pool": session.get("skill_pool", {}),
        "skill_values": session.get("skill_values", {}),
        "keeper_char_id": session.get("keeper_char_id", ""),
        "keeper_char_name": session.get("keeper_char_name", ""),
        "human_keeper": session.get("human_keeper", False),
    }
    save_session_mode(
        session_id=session_id,
        participants=session.get("initiative", []),
        history=history,
        metadata=metadata,
    )
    _delete_autosave(session_id)
    return {"status": "ok"}
