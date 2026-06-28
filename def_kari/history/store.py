"""F-16/F-17: ゾーニング・バイナリ分離保存(基本設計5.6節)

チャットモードではキャラクターごとに履歴ファイルを分離する。
ファイル名: data/session_history_{character_id}.json
"""

import json
import os
from pathlib import Path

from def_kari.config import MAX_VISIBLE_TURNS

DATA_DIR = Path(__file__).parent.parent.parent / "data"
PRIVATE_DIR = DATA_DIR / "private"

_EXCLUDE_KEYS = {"llm_attempts", "_undo_stack", "_redo_stack"}


def _is_private_character(character_id: str) -> bool:
    private_chars = PRIVATE_DIR / "characters"
    if private_chars.exists():
        return (private_chars / character_id / "profile.json").exists()
    return False


def _history_path(character_id: str) -> Path:
    if _is_private_character(character_id):
        _dir = PRIVATE_DIR / "session_history"
    else:
        _dir = DATA_DIR / "public" / "session_history"
    _dir.mkdir(parents=True, exist_ok=True)
    return _dir / f"{character_id}.json"


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "public" / "session_history").mkdir(parents=True, exist_ok=True)
    (PRIVATE_DIR / "session_history").mkdir(parents=True, exist_ok=True)


def load_full(character_id: str = "character_luna_001") -> list[dict]:
    _ensure_dirs()
    path = _history_path(character_id)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return []


def _write(full: list[dict], character_id: str = "character_luna_001") -> None:
    _ensure_dirs()
    path = _history_path(character_id)
    tmp_path = str(path) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(full, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, str(path))


def save_session(session_history: list[dict], character_id: str = "character_luna_001") -> None:
    """session_historyをID単位でフルマージして永続化する(F-17)。"""
    full = load_full(character_id)
    index_by_id = {m["id"]: i for i, m in enumerate(full)}

    for msg in session_history:
        m = {k: v for k, v in msg.items() if k not in _EXCLUDE_KEYS}
        if m["id"] in index_by_id:
            existing = full[index_by_id[m["id"]]]
            for k, v in m.items():
                if v is not None or k not in existing:
                    existing[k] = v
        else:
            full.append(m)
            index_by_id[m["id"]] = len(full) - 1
    _write(full, character_id)


def trim_session(session_history: list[dict], max_visible: int = MAX_VISIBLE_TURNS) -> list[dict]:
    """完了済み(state == "Persist")ターンのうち直近max_visible件のみを保持する(F-17)。"""
    pending = [m for m in session_history if m.get("state") != "Persist"]
    done = [m for m in session_history if m.get("state") == "Persist"]
    if len(done) > max_visible:
        done = done[-max_visible:]
    keep_ids = {m["id"] for m in done} | {m["id"] for m in pending}
    return [m for m in session_history if m["id"] in keep_ids]


def lazy_load_more(session_history: list[dict], batch: int, character_id: str = "character_luna_001") -> list[dict]:
    """全履歴からsession未保持分をbatch件読み込み、先頭に追加して返す(F-17)。"""
    full = load_full(character_id)
    existing_ids = {m["id"] for m in session_history}
    missing = [m for m in full if m["id"] not in existing_ids]
    if not missing:
        return session_history
    to_load = missing[-batch:]
    return to_load + session_history


def clear_history(character_id: str) -> None:
    """指定キャラクターの履歴をクリアする。"""
    path = _history_path(character_id)
    if path.exists():
        _write([], character_id)


# --- セッションモード履歴の永続化 ---

def _is_private_rule_set(rule_set: str) -> bool:
    return (PRIVATE_DIR / "session_rules" / f"{rule_set}.json").exists()


def _session_mode_path(session_id: str, participants: list[str], rule_set: str = "") -> Path:
    _is_private = False
    for pid in participants:
        if _is_private_character(pid):
            _is_private = True
            break
    if not _is_private and rule_set and _is_private_rule_set(rule_set):
        _is_private = True
    _dir = PRIVATE_DIR / "session_history" if _is_private else DATA_DIR / "public" / "session_history"
    _dir.mkdir(parents=True, exist_ok=True)
    return _dir / f"session_mode_{session_id}.json"


def save_session_mode(session_id: str, participants: list[str], history: list[dict], metadata: dict | None = None) -> None:
    _ensure_dirs()
    _rule_set = (metadata or {}).get("rule_set", "")
    path = _session_mode_path(session_id, participants, _rule_set)
    data = {
        "session_id": session_id,
        "participants": participants,
        "metadata": metadata or {},
        "history": history,
    }
    tmp_path = str(path) + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, str(path))


def load_session_mode(session_id: str, participants: list[str] | None = None) -> dict | None:
    participants = participants or []
    path = _session_mode_path(session_id, participants)
    if not path.exists():
        for _dir in (DATA_DIR / "public" / "session_history", PRIVATE_DIR / "session_history"):
            _candidate = _dir / f"session_mode_{session_id}.json"
            if _candidate.exists():
                path = _candidate
                break
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def list_session_mode_files() -> list[dict]:
    results = []
    for _dir in (DATA_DIR / "public" / "session_history", PRIVATE_DIR / "session_history"):
        if _dir.exists():
            for _f in sorted(_dir.glob("session_mode_*.json")):
                try:
                    with open(_f, encoding="utf-8") as f:
                        data = json.load(f)
                    results.append({
                        "session_id": data.get("session_id", _f.stem),
                        "participants": data.get("participants", []),
                        "metadata": data.get("metadata", {}),
                        "path": str(_f),
                        "private": "private" in str(_f),
                    })
                except (json.JSONDecodeError, OSError):
                    pass
    return results
