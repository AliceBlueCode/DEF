"""Session API routes."""

import datetime
import json
import os
import random
import re
import secrets
from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from def_kari.characters import load_profiles, get_character
from def_kari.history.store import save_session_mode, list_session_mode_files
from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.llm.client import generate_structured_reply

router = APIRouter()

_MAX_SESSIONS = int(os.environ.get("DEF_MAX_SESSIONS", "1000"))
_sessions: OrderedDict[str, dict] = OrderedDict()

_BASE = Path(__file__).parent.parent.parent.parent
_RULE_DIRS = [
    _BASE / "data" / "public" / "session_rules",
    _BASE / "data" / "private" / "session_rules",
]
_SESSION_HISTORY_DIRS = [
    _BASE / "data" / "public" / "session_history",
    _BASE / "data" / "private" / "session_history",
]
_SAFE_FILENAME_RE = re.compile(r'^[A-Za-z0-9_\-]+\.json$')


def _load_session_rules() -> dict:
    rules = {}
    for d in _RULE_DIRS:
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix == ".json":
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        rid = data.get("id", f.stem)
                        rules[rid] = data
                    except (json.JSONDecodeError, OSError):
                        pass
    if not rules:
        rules["none"] = {"id": "none", "label": "ルールなし", "rules": []}
    return rules


@router.get("/rules")
def get_session_rules():
    rules = _load_session_rules()
    return {
        "rules": [
            {"id": rid, "label": r.get("label", rid)}
            for rid, r in rules.items()
        ]
    }


class SessionStartRequest(BaseModel):
    character_ids: list[str]
    topic: str = ""
    backend: str = DEFAULT_LLM_BACKEND
    rule_set: str = "default"
    actions_per_turn: int = 1


class SessionNextRequest(BaseModel):
    session_id: str
    backend: str = DEFAULT_LLM_BACKEND
    model: str = ""


class SessionHumanMessage(BaseModel):
    session_id: str
    message: str


@router.post("/start")
def start_session(req: SessionStartRequest):
    session_id = secrets.token_urlsafe(16)
    initiative = random.sample(req.character_ids, len(req.character_ids))
    profiles = load_profiles()
    name_map = {}
    for cid in req.character_ids:
        char = get_character(cid, profiles)
        name_map[cid] = char.get("name", cid) if char else cid

    if len(_sessions) >= _MAX_SESSIONS:
        _sessions.popitem(last=False)
    rules = _load_session_rules().get(req.rule_set, {}).get("rules", [])
    _sessions[session_id] = {
        "id": session_id,
        "initiative": initiative,
        "name_map": name_map,
        "topic": req.topic,
        "backend": req.backend,
        "rule_set": req.rule_set,
        "rules": rules,
        "round": 1,
        "turn": 0,
        "action_count": 0,
        "actions_per_turn": req.actions_per_turn,
        "history": [],
    }

    order = [name_map.get(c, c) for c in initiative]
    return {"session_id": session_id, "initiative": initiative, "order": order}


@router.post("/next")
def next_turn(req: SessionNextRequest):
    session = _sessions.get(req.session_id)
    if not session:
        return {"error": "Session not found"}

    initiative = session["initiative"]
    turn = session["turn"]
    if turn >= len(initiative):
        session["round"] += 1
        session["turn"] = 0
        turn = 0

    current_char_id = initiative[turn]
    profiles = load_profiles()
    char = get_character(current_char_id, profiles)
    name_map = session["name_map"]

    backend_id = req.backend or session["backend"]
    if backend_id not in LLM_BACKENDS:
        backend_id = DEFAULT_LLM_BACKEND
    model = req.model
    if not model:
        model = LLM_BACKENDS.get(backend_id, {}).get("default_model", "")

    history = []
    for h in session["history"][-20:]:
        history.append({"role": h["role"], "content": h["content"]})

    rules = session.get("rules", [])
    rule_block = ("【セッションルール】\n" + "\n".join(f"・{r}" for r in rules) + "\n") if rules else ""
    other_names = [name_map.get(c, c) for c in initiative if c != current_char_id]
    speaker_name = name_map.get(current_char_id, current_char_id)
    topic = session.get("topic", "")

    lang_rule = "【重要】必ず日本語で発言してください。英語で考えた内容も、出力は日本語にしてください。dialogue フィールドに思考プロセスや推論を書かないでください。\n"
    if not session["history"]:
        user_text = lang_rule + rule_block
        user_text += "\nこれは複数の参加者による討論セッションです。"
        if topic:
            user_text += f"\n今日のお題: 「{topic}」"
        user_text += f"\n参加者: {', '.join(name_map.get(c, c) for c in initiative)}"
        user_text += f"\nあなたは{speaker_name}です。対話相手は{', '.join(other_names)}です。"
        user_text += "\nまず簡潔に自己紹介し、このお題に対するあなたの考えや立場を述べてください。"
    else:
        user_text = lang_rule + rule_block
        user_text += f"\nあなたは{speaker_name}です。対話相手は{', '.join(other_names)}です。"
        if topic:
            user_text += f"\nお題: 「{topic}」"
        user_text += "\n上記の発言記録を踏まえ、他の参加者の発言を具体的に引用しながら、あなた自身の立場から意見を述べてください。"

    try:
        result = generate_structured_reply(
            user_text=user_text,
            history=history,
            model=model,
            character=char,
            backend=backend_id,
        )
    except Exception as e:
        return {"error": str(e), "character_id": current_char_id, "character_name": name_map.get(current_char_id, current_char_id), "text": f"(error: {e})", "emotion": "neutral", "round": session["round"], "turn": turn + 1}

    text = ""
    emotion = "neutral"
    tags: list[str] = []
    if result.get("success") and result.get("result"):
        parsed = result["result"]
        text = parsed.get("dialogue", "")
        emotion = parsed.get("emotion", "neutral")
        raw_tags = parsed.get("tags", [])
        tags = raw_tags if isinstance(raw_tags, list) else []
    else:
        attempts = result.get("attempts", [])
        errors = "; ".join(e for a in attempts for e in a.get("errors", []))
        text = f"(generation failed: {errors})" if errors else "(generation failed)"

    session["history"].append({
        "role": "assistant",
        "content": f"{name_map.get(current_char_id, current_char_id)}: {text}",
        "character_id": current_char_id,
        "emotion": emotion,
        "tags": tags,
    })
    actions_per_turn = session.get("actions_per_turn", 1)
    action_count = session.get("action_count", 0) + 1
    if action_count >= actions_per_turn:
        session["turn"] = turn + 1
        session["action_count"] = 0
    else:
        session["action_count"] = action_count

    return {
        "character_id": current_char_id,
        "character_name": name_map.get(current_char_id, current_char_id),
        "text": text,
        "emotion": emotion,
        "tags": tags,
        "round": session["round"],
        "turn": turn + 1,
    }


@router.post("/{session_id}/retake")
def retake_turn(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    action_count = session.get("action_count", 0)
    actions_per_turn = session.get("actions_per_turn", 1)
    turn = session.get("turn", 0)
    history = session.get("history", [])

    if action_count > 0:
        # 現キャラが途中まで発言済み → その分を巻き戻す
        remove = action_count
        session["action_count"] = 0
    else:
        # 直前のキャラのターンが完了してしまっている → 1つ前のキャラに戻る
        if turn == 0 and session.get("round", 1) <= 1:
            return {"error": "Cannot retake: at the beginning"}
        if turn == 0:
            session["round"] -= 1
            session["turn"] = len(session["initiative"])
            turn = session["turn"]
        session["turn"] = turn - 1
        remove = actions_per_turn
        session["action_count"] = 0

    # assistantのメッセージだけを対象に末尾からremove件削除
    removed = 0
    new_history = list(history)
    while removed < remove and new_history:
        if new_history[-1].get("role") == "assistant":
            new_history.pop()
            removed += 1
        else:
            break
    session["history"] = new_history

    return {"removed": removed}


@router.post("/human")
def human_message(req: SessionHumanMessage):
    session = _sessions.get(req.session_id)
    if not session:
        return {"error": "Session not found"}
    session["history"].append({
        "role": "user",
        "content": req.message,
        "character_id": "human",
        "emotion": "",
    })
    return {"status": "ok"}


@router.get("/saved")
def list_saved_sessions():
    files = list_session_mode_files()
    result = []
    for f in reversed(files):
        meta = f.get("metadata", {})
        result.append({
            "filename": Path(f["path"]).name,
            "session_id": f["session_id"],
            "topic": meta.get("topic", ""),
            "saved_at": meta.get("saved_at", ""),
            "round": meta.get("round", 1),
            "character_names": list(meta.get("name_map", {}).values()),
            "private": f.get("private", False),
        })
    return {"sessions": result}


class SessionLoadRequest(BaseModel):
    filename: str


@router.post("/load")
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
        "history": data.get("history", []),
    }
    if len(_sessions) >= _MAX_SESSIONS:
        _sessions.popitem(last=False)
    _sessions[new_id] = session
    return {
        "session_id": new_id,
        "initiative": session["initiative"],
        "round": session["round"],
        "topic": session["topic"],
        "name_map": session["name_map"],
        "history": session["history"],
    }


@router.post("/{session_id}/save")
def save_session(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    metadata = {
        "topic": session.get("topic", ""),
        "backend": session.get("backend", ""),
        "rule_set": session.get("rule_set", ""),
        "rules": session.get("rules", []),
        "round": session.get("round", 1),
        "turn": session.get("turn", 0),
        "initiative": session.get("initiative", []),
        "name_map": session.get("name_map", {}),
        "saved_at": datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
    }
    save_session_mode(
        session_id=session_id,
        participants=session.get("initiative", []),
        history=session.get("history", []),
        metadata=metadata,
    )
    return {"status": "ok"}


@router.get("/{session_id}")
def get_session(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    return {"session": session}
