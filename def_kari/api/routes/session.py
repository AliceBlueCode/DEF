"""Session API routes."""

import datetime
import json
import os
import random
import re
import secrets
from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter, Body
from pydantic import BaseModel

from def_kari.characters import load_profiles, get_character
from def_kari.history.store import save_session_mode, list_session_mode_files
from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND
from def_kari.llm.client import generate_structured_reply  # vote/deliberate で直接使用
from def_kari.gm.player_agent import _player_agent
from def_kari.image_prompt.emotion_tags import apply_emotion_tags
from def_kari.settings import load_settings
from def_kari.t2i.backend import generate_image as _generate_t2i_image
from def_kari.gm.context_builder import (
    load_trpg_rulebook as _load_trpg_rulebook,
    load_trpg_scenario as _load_trpg_scenario,
    build_trpg_context as _build_trpg_context,
    build_for_player as _build_for_player,
    build_session_context as _build_session_context,
    build_turn_instruction as _build_turn_instruction,
)
from def_kari.gm.gm_agent import _gm_agent

router = APIRouter()

_BASE_DATA = Path(__file__).parent.parent.parent.parent / "data"
_SESSION_PROMPTS_PATH = _BASE_DATA / "session_prompts.json"
_session_prompts_cache: dict = {}

def _load_session_prompts() -> dict:
    global _session_prompts_cache
    if _session_prompts_cache:
        return _session_prompts_cache
    try:
        with open(_SESSION_PROMPTS_PATH, encoding="utf-8") as f:
            _session_prompts_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return _session_prompts_cache

def _sp(key: str, lang: str) -> str:
    """session_prompts.json から言語別テキストを取得。"""
    entry = _load_session_prompts().get(key, {})
    return entry.get(lang) or entry.get("ja") or ""


_LANG_LABELS = {
    "ja": "日本語", "en": "English", "zh": "中文",
    "ko": "한국어", "es": "Español", "fr": "Français", "de": "Deutsch",
}




_MAX_SESSIONS = int(os.environ.get("DEF_MAX_SESSIONS", "1000"))
_sessions: OrderedDict[str, dict] = OrderedDict()
_last_session_debug: dict = {}


def _handle_flag_updated(session_id: str, event: dict) -> None:
    """FLAG_UPDATED イベントを受けて player_knowledge を更新する。"""
    sess = _sessions.get(session_id)
    if not sess:
        return
    payload = event.get("payload", {})
    if payload.get("gm_only"):
        return
    key = payload.get("key", "")
    value = payload.get("value")
    if not key:
        return
    entry = f"フラグ「{key}」が更新された（値: {value}）"
    pk = sess.setdefault("player_knowledge", {})
    for char_id in sess.get("initiative", []):
        char_list = pk.setdefault(char_id, [])
        if entry not in char_list:
            char_list.append(entry)


from def_kari.gm.events import game_event_bus as _game_event_bus, FLAG_UPDATED as _FLAG_UPDATED
_game_event_bus.subscribe(_FLAG_UPDATED, _handle_flag_updated)


def _save_session_episodic(session_id: str, session: dict) -> None:
    """セッション終了時に各キャラクターの episodic memory を書き込む。"""
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


def _build_initial_npc_state(scenario_id: str) -> dict:
    """シナリオの静的NPC定義から npc_state を初期化する。

    npc_state = {
        npc_id: {
            "knowledge": [str, ...],       # セッション中に獲得した情報
            "relationship": {              # PC/NPC との関係値（動的更新）
                char_id: {"trust": int, "hostility": int}
            }
        }
    }
    静的なデフォルト値（goal / description など）は scenario JSON を直接参照し、
    セッション中の変更分のみ npc_state に保持する。
    """
    if not scenario_id:
        return {}
    scenario = _load_trpg_scenario(scenario_id)
    npc_state = {}
    for npc in scenario.get("npcs", []):
        nid = npc.get("id")
        if not nid:
            continue
        npc_state[nid] = {
            "knowledge": list(npc.get("knowledge", [])),
            "relationship": {
                k: dict(v) for k, v in npc.get("relationship", {}).items()
            },
        }
    return npc_state


_BASE = Path(__file__).parent.parent.parent.parent
_RULE_DIRS = [
    _BASE / "data" / "public" / "session_rules",
    _BASE / "data" / "private" / "session_rules",
]
_DIRECTIVE_DIRS = [
    _BASE / "data" / "public" / "action_directives",
    _BASE / "data" / "private" / "action_directives",
]
_SESSION_HISTORY_DIRS = [
    _BASE / "data" / "public" / "session_history",
    _BASE / "data" / "private" / "session_history",
]
_AUTOSAVE_DIR = _BASE / "data" / "private" / "session_autosave"
_SAFE_FILENAME_RE = re.compile(r'^[A-Za-z0-9_\-]+\.json$')


def _autosave(session_id: str) -> None:
    session = _sessions.get(session_id)
    if not session:
        return
    try:
        _AUTOSAVE_DIR.mkdir(parents=True, exist_ok=True)
        (_AUTOSAVE_DIR / f"{session_id}.json").write_text(
            json.dumps(session, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def _delete_autosave(session_id: str) -> None:
    try:
        (_AUTOSAVE_DIR / f"{session_id}.json").unlink(missing_ok=True)
    except Exception:
        pass


# ── 起動時に進行中セッションを復元 ──────────────────────────────
try:
    if _AUTOSAVE_DIR.is_dir():
        for _f in sorted(_AUTOSAVE_DIR.iterdir()):
            if _f.suffix == ".json":
                try:
                    _restored = json.loads(_f.read_text(encoding="utf-8"))
                    if isinstance(_restored, dict) and _restored.get("id"):
                        _sessions[_restored["id"]] = _restored
                except Exception:
                    pass
except Exception:
    pass


def _load_action_directives() -> dict:
    directives: dict = {}
    for d in _DIRECTIVE_DIRS:
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix == ".json" and f.name != ".gitkeep":
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        did = data.get("id", f.stem)
                        directives[did] = data
                    except (json.JSONDecodeError, OSError):
                        pass
    if "none" not in directives:
        directives["none"] = {"id": "none", "label": "指示なし（キャラクターに任せる）", "directives": {}}
    return directives


@router.get("/action-directives")
def get_action_directives():
    directives = _load_action_directives()
    return {
        "directives": [
            {"id": did, "label": d.get("label", did), "rating": d.get("rating", "general"), "recommended_for": d.get("recommended_for", [])}
            for did, d in directives.items()
        ]
    }


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


@router.get("/rules/{rule_id}")
def get_session_rule_detail(rule_id: str):
    if not re.match(r'^[A-Za-z0-9_\-]+$', rule_id):
        return {"error": "Invalid rule ID"}
    for d in _RULE_DIRS:
        path = d / f"{rule_id}.json"
        if path.exists():
            try:
                return {"content": path.read_text(encoding="utf-8"), "id": rule_id}
            except OSError as e:
                return {"error": str(e)}
    return {"error": f"Rule '{rule_id}' not found"}


class SaveRuleRequest(BaseModel):
    content: str


@router.put("/rules/{rule_id}")
def save_session_rule(rule_id: str, req: SaveRuleRequest):
    if not re.match(r'^[A-Za-z0-9_\-]+$', rule_id):
        return {"error": "Invalid rule ID"}
    try:
        data = json.loads(req.content)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}
    target: Path | None = None
    for d in _RULE_DIRS:
        path = d / f"{rule_id}.json"
        if path.exists():
            target = path
            break
    if target is None:
        _RULE_DIRS[0].mkdir(parents=True, exist_ok=True)
        target = _RULE_DIRS[0] / f"{rule_id}.json"
    tmp = str(target) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(target))
    return {"status": "ok", "id": rule_id}


class SessionStartRequest(BaseModel):
    character_ids: list[str]
    topic: str = ""
    backend: str = DEFAULT_LLM_BACKEND
    rule_set: str = "default"
    actions_per_turn: int = 0
    action_directive_set: str = ""
    char_backends: dict[str, str] = {}
    trpg_mode: bool = False
    trpg_rulebook: str = ""
    trpg_scenario: str = ""
    char_game_sheets: dict[str, str] = {}


class SessionNextRequest(BaseModel):
    session_id: str
    backend: str = DEFAULT_LLM_BACKEND
    model: str = ""


class SessionHumanMessage(BaseModel):
    session_id: str
    message: str


class KeeperMessageRequest(BaseModel):
    text: str


@router.post("/start")
def start_session(req: SessionStartRequest):
    from def_kari.settings import load_settings as _load_s
    _s = _load_s()
    apt = req.actions_per_turn or _s.get("session_actions_per_turn", 2)
    directive_set_id = req.action_directive_set or _s.get("session_action_directive_set", "default")

    session_id = secrets.token_urlsafe(16)
    initiative = random.sample(req.character_ids, len(req.character_ids))
    profiles = load_profiles()
    name_map = {}
    for cid in req.character_ids:
        char = get_character(cid, profiles)
        name_map[cid] = char.get("name", cid) if char else cid

    if len(_sessions) >= _MAX_SESSIONS:
        _sessions.popitem(last=False)
    _rule_data = _load_session_rules().get(req.rule_set, {})
    rules = _rule_data.get("rules", [])
    scene = _rule_data.get("scene", "")
    char_backends = {
        cid: bid
        for cid, bid in req.char_backends.items()
        if cid in req.character_ids and bid in LLM_BACKENDS
    }
    _sessions[session_id] = {
        "id": session_id,
        "initiative": initiative,
        "name_map": name_map,
        "topic": req.topic,
        "backend": req.backend,
        "char_backends": char_backends,
        "rule_set": req.rule_set,
        "rules": rules,
        "scene": scene,
        "round": 1,
        "turn": 0,
        "action_count": 0,
        "actions_per_turn": apt,
        "action_directive_set": directive_set_id,
        "history": [],
        "counters": {},
        "designated_next": None,
        "trpg_mode": req.trpg_mode,
        "trpg_rulebook": req.trpg_rulebook,
        "trpg_scenario": req.trpg_scenario,
        "char_game_sheets": req.char_game_sheets,
        "current_scene_index": 0,
        "player_knowledge": {cid: [] for cid in req.character_ids},
        "npc_state": _build_initial_npc_state(req.trpg_scenario),
    }

    order = [name_map.get(c, c) for c in initiative]
    _autosave(session_id)
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

    # 指名があれば優先
    designated = session.pop("designated_next", None)
    if designated and designated in initiative:
        return_turn = session.pop("designated_return_turn", None)
        if return_turn is not None:
            session["_designated_return_turn"] = return_turn
        turn = initiative.index(designated)
        session["turn"] = turn
        session["action_count"] = 0

    current_char_id = initiative[turn]
    name_map = session["name_map"]

    # 発言力がマイナスなら自動スキップ
    counters = session.setdefault("counters", {})
    if counters.get(current_char_id, 0) < 0:
        counters[current_char_id] += 1
        session["turn"] = turn + 1
        session["action_count"] = 0
        _autosave(req.session_id)
        return {
            "skipped": True,
            "character_id": current_char_id,
            "character_name": name_map.get(current_char_id, current_char_id),
            "round": session["round"],
            "counters": dict(counters),
        }

    profiles = load_profiles()
    char = get_character(current_char_id, profiles)

    # 人間プレイヤーのターンは LLM を呼ばず入力待ちを返す
    if char.get("player_type") == "human":
        return {
            "waiting_for_human": True,
            "character_id": current_char_id,
            "character_name": name_map.get(current_char_id, current_char_id),
            "round": session["round"],
            "counters": dict(counters),
        }

    char_backends = session.get("char_backends", {})
    backend_id = char_backends.get(current_char_id) or req.backend or session.get("backend", DEFAULT_LLM_BACKEND)
    if backend_id not in LLM_BACKENDS:
        backend_id = DEFAULT_LLM_BACKEND
    model = req.model
    if not model:
        model = LLM_BACKENDS.get(backend_id, {}).get("default_model", "")

    history = []
    for h in session["history"][-20:]:
        raw_content = h["content"]
        h_role = h.get("role", "user")
        h_char_id = h.get("character_id")
        if h_role == "assistant" and h_char_id:
            # "Name: text" → strip prefix
            text = raw_content.split(": ", 1)[-1] if ": " in raw_content else raw_content
            if h_char_id == current_char_id:
                history.append({"role": "assistant", "content": text})
            else:
                other_name = name_map.get(h_char_id, h_char_id)
                history.append({"role": "user", "content": f"[{other_name}] {text}"})
        else:
            history.append({"role": h_role, "content": raw_content})

    _settings = load_settings()
    _user_lang = _settings.get("user_language", "ja") or "ja"
    _allowed_sexual = _settings.get("allowed_rating_sexual", ["general"])
    _allowed_violence = _settings.get("allowed_rating_violence", ["general"])

    rules = session.get("rules", [])
    speaker_name = name_map.get(current_char_id, current_char_id)
    topic = session.get("topic", "")
    action_count = session.get("action_count", 0)
    other_names = [name_map.get(c, c) for c in initiative if name_map.get(c, c) != speaker_name]

    directive_set_id = session.get("action_directive_set", "default")
    _directives = _load_action_directives().get(directive_set_id, {}).get("directives", {})

    _trpg_ctx = ""
    if session.get("trpg_mode"):
        _rulebook = _load_trpg_rulebook(session.get("trpg_rulebook", ""))
        _scenario = _load_trpg_scenario(session.get("trpg_scenario", ""))
        _trpg_ctx = _build_for_player(
            current_char_id, char, _rulebook, _scenario or None, session, _user_lang
        )

    session_ctx = _build_session_context(
        topic, rules, initiative, name_map, speaker_name, _user_lang,
        trpg_context=_trpg_ctx,
    )
    user_text = _build_turn_instruction(
        action_count, speaker_name, other_names, topic,
        session["history"], current_char_id, session, _directives, _user_lang,
    )

    prev_emotion = next(
        (h.get("emotion", "neutral") for h in reversed(session["history"])
         if h.get("character_id") == current_char_id),
        "neutral",
    )
    if isinstance(prev_emotion, list):
        prev_emotion = ", ".join(prev_emotion)

    global _last_session_debug
    from def_kari.resources.vram_lock import get_vram_lock
    _vram_lock = get_vram_lock()
    _vram_lock.acquire()
    try:
        result = _player_agent.narrate(
            character=char,
            user_text=user_text,
            history=history,
            model=model,
            backend=backend_id,
            session_context=session_ctx,
            allowed_sexual=_allowed_sexual,
            allowed_violence=_allowed_violence,
            current_emotion=prev_emotion,
            char_id=current_char_id,
        )
    except Exception as e:
        _last_session_debug = {"error": str(e), "success": False, "attempts": [], "character_id": current_char_id, "backend": backend_id, "topic": topic, "round": session["round"], "user_text": user_text}
        return {"error": str(e), "character_id": current_char_id, "character_name": name_map.get(current_char_id, current_char_id), "text": f"(error: {e})", "emotion": "neutral", "round": session["round"], "turn": turn + 1, "counters": dict(session.get("counters", {}))}
    finally:
        _vram_lock.release()

    text = ""
    emotion = "neutral"
    tags: list[str] = []
    image_prompt_en = ""
    if result.get("success") and result.get("result"):
        parsed = result["result"]
        text = parsed.get("dialogue", "")
        emotion = parsed.get("emotion", "neutral")
        raw_tags = parsed.get("tags", [])
        tags = raw_tags if isinstance(raw_tags, list) else []
        image_prompt_en = parsed.get("image_prompt_en", "")
        image_prompt_en = apply_emotion_tags(image_prompt_en, emotion)
        _last_session_debug = {
            "success": True,
            "character_id": current_char_id,
            "character_name": name_map.get(current_char_id, current_char_id),
            "backend": backend_id,
            "topic": topic,
            "round": session["round"],
            "text": text,
            "emotion": emotion,
            "tags": tags,
            "image_prompt_en": image_prompt_en,
            "raw": result.get("attempts", [{}])[-1].get("raw", "") if result.get("attempts") else "",
            "attempts": result.get("attempts", []),
            "user_text": user_text,
        }
    else:
        attempts = result.get("attempts", [])
        errors = "; ".join(e for a in attempts for e in a.get("errors", []))
        text = f"(generation failed: {errors})" if errors else "(generation failed)"
        _last_session_debug = {
            "success": False,
            "character_id": current_char_id,
            "character_name": name_map.get(current_char_id, current_char_id),
            "backend": backend_id,
            "topic": topic,
            "round": session["round"],
            "raw": attempts[-1]["raw"] if attempts else "",
            "attempts": attempts,
            "user_text": user_text,
        }

    session["history"].append({
        "role": "assistant",
        "content": f"{name_map.get(current_char_id, current_char_id)}: {text}",
        "character_id": current_char_id,
        "emotion": emotion,
        "tags": tags,
    })

    # A6 リピートペナルティ
    from def_kari.settings import load_settings as _load_settings
    _s = _load_settings()
    _repeat_threshold = int(_s.get("session_repeat_penalty_count", 3))
    _lang = _s.get("user_language", "ja")
    if _repeat_threshold > 0:
        _char_contents = [
            h["content"] for h in session["history"]
            if h.get("character_id") == current_char_id and h.get("role") == "assistant"
        ][-_repeat_threshold:]
        penalty_message = ""
    if len(_char_contents) >= _repeat_threshold and len(set(_char_contents)) == 1:
            counters[current_char_id] = counters.get(current_char_id, 0) - 1
            _char_label = name_map.get(current_char_id, current_char_id)
            penalty_message = (
                f"⚠ {_char_label} repeated the same message {_repeat_threshold} times [speech power -1]"
                if _lang == "en" else
                f"⚠ {_char_label} が同一発言を{_repeat_threshold}回繰り返した [発言力-1]"
            )

    actions_per_turn = session.get("actions_per_turn", 2)
    action_count = session.get("action_count", 0) + 1
    if action_count >= actions_per_turn:
        return_turn = session.pop("_designated_return_turn", None)
        if return_turn is not None:
            next_t = return_turn % len(initiative) if initiative else 0
        else:
            next_t = turn + 1
        session["turn"] = next_t
        session["action_count"] = 0
    else:
        session["action_count"] = action_count

    _autosave(req.session_id)
    return {
        "character_id": current_char_id,
        "character_name": name_map.get(current_char_id, current_char_id),
        "text": text,
        "emotion": emotion,
        "tags": tags,
        "image_prompt_en": image_prompt_en,
        "round": session["round"],
        "turn": turn + 1,
        "counters": dict(counters),
        "penalty_message": penalty_message,
    }


@router.post("/{session_id}/retake")
def retake_turn(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    action_count = session.get("action_count", 0)
    actions_per_turn = session.get("actions_per_turn", 2)
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

    _autosave(session_id)
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
    _autosave(req.session_id)
    return {"status": "ok"}


@router.post("/{session_id}/keeper")
def inject_keeper_message(session_id: str, req: KeeperMessageRequest):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    content = f"[GM] {req.text}"
    session["history"].append({
        "role": "user",
        "content": content,
        "character_id": "_keeper",
    })
    _autosave(session_id)
    return {"status": "ok"}


class AIKeeperRequest(BaseModel):
    backend: str = DEFAULT_LLM_BACKEND
    inject_history: bool = True


@router.post("/{session_id}/ai_keeper")
def ai_keeper_narrate(session_id: str, req: AIKeeperRequest):
    """AIキーパー（無個性モード）: シナリオ・ルールブック・履歴からGM発言を生成する。"""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    if not session.get("trpg_mode"):
        return {"error": "Not in TRPG mode"}

    result = _gm_agent.narrate(
        session=session,
        backend_id=req.backend or DEFAULT_LLM_BACKEND,
        inject_history=req.inject_history,
        session_id=session_id,
    )
    if result.get("error"):
        return {"error": result["error"]}
    if req.inject_history and result["text"]:
        _autosave(session_id)

    return {
        "text": result["text"],
        "character_id": "_keeper",
        "character_name": "🎩 Keeper",
        "judgments": result["judgments"],
    }


@router.post("/{session_id}/skip")
def skip_turn(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    initiative = session["initiative"]
    turn = session["turn"]
    if turn >= len(initiative):
        session["round"] += 1
        session["turn"] = 0
        turn = 0
    char_id = initiative[turn]
    counters = session.setdefault("counters", {})
    counters[char_id] = counters.get(char_id, 0) + 1
    session["turn"] = turn + 1
    session["action_count"] = 0
    if session["turn"] >= len(initiative):
        session["round"] += 1
        session["turn"] = 0
    _autosave(session_id)
    return {
        "character_id": char_id,
        "character_name": session["name_map"].get(char_id, char_id),
        "round": session["round"],
        "counters": dict(counters),
    }


class DesignateRequest(BaseModel):
    target_id: str


@router.post("/{session_id}/designate")
def designate_next(session_id: str, req: DesignateRequest):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    if req.target_id not in session["initiative"]:
        return {"error": "Character not in initiative"}
    initiative = session["initiative"]
    current_turn = session.get("turn", 0)
    # 指名発言後に戻るべきターン位置を保存（指名キャラの次）
    session["designated_next"] = req.target_id
    session["designated_return_turn"] = (current_turn + 1) % len(initiative) if initiative else 0
    _autosave(session_id)
    return {"status": "ok"}


class CounterAdjustRequest(BaseModel):
    delta: int


@router.post("/{session_id}/counter/{char_id}")
def adjust_counter(session_id: str, char_id: str, req: CounterAdjustRequest):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    counters = session.setdefault("counters", {})
    counters[char_id] = counters.get(char_id, 0) + req.delta
    _autosave(session_id)
    return {"counters": dict(counters)}


class VoteRequest(BaseModel):
    vote_type: str
    detail: str = ""
    target_id: str = ""
    proposer_id: str = ""  # 人間プレイヤーが発議した場合、カウンターを0にする
    proposer_text: str = ""  # 人間プレイヤーの弁明テキスト


class VoteCommitRequest(BaseModel):
    keeper_vote: bool


class HumanTurnRequest(BaseModel):
    action: str  # "send" | "extend" | "skip" | "interrupt"
    text: str = ""
    character_id: str = ""  # interrupt 時に発言者IDを指定


@router.post("/{session_id}/human_turn")
def human_turn_action(session_id: str, req: HumanTurnRequest):
    """人間プレイヤーのターンアクション（send / extend / skip）。"""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    initiative = session["initiative"]
    turn = session["turn"]
    if turn >= len(initiative):
        return {"error": "invalid turn"}

    current_char_id = initiative[turn]
    name_map = session["name_map"]
    counters = session.setdefault("counters", {})
    char_name = name_map.get(current_char_id, current_char_id)

    if req.action == "interrupt":
        if not req.text.strip():
            return {"error": "text required"}
        # 割り込み発言者は current_char_id ではなく req.character_id（人間キャラ）
        interrupter_id = req.character_id if req.character_id else current_char_id
        interrupter_name = name_map.get(interrupter_id, interrupter_id)
        counters[interrupter_id] = counters.get(interrupter_id, 0) - 2
        session["history"].append({
            "role": "assistant",
            "content": f"{interrupter_name}: {req.text}",
            "character_id": interrupter_id,
            "emotion": "neutral",
            "tags": [],
        })
        _autosave(session_id)
        return {
            "action": "interrupt",
            "character_id": interrupter_id,
            "character_name": interrupter_name,
            "text": req.text,
            "round": session["round"],
            "counters": dict(counters),
        }

    if req.action == "generate_image":
        char_id = req.character_id if req.character_id else current_char_id
        counters[char_id] = counters.get(char_id, 0) - 1
        _autosave(session_id)
        return {
            "action": "generate_image",
            "counters": dict(counters),
            "round": session["round"],
        }

    if req.action == "skip":
        counters[current_char_id] = counters.get(current_char_id, 0) + 1
        session["turn"] = turn + 1
        session["action_count"] = 0
        _autosave(session_id)
        return {
            "action": "skip",
            "character_id": current_char_id,
            "character_name": char_name,
            "round": session["round"],
            "counters": dict(counters),
        }

    if not req.text.strip():
        return {"error": "text required"}

    session["history"].append({
        "role": "assistant",
        "content": f"{char_name}: {req.text}",
        "character_id": current_char_id,
        "emotion": "neutral",
        "tags": [],
    })

    if req.action == "extend":
        counters[current_char_id] = counters.get(current_char_id, 0) - 1
        _autosave(session_id)
        return {
            "action": "extend",
            "character_id": current_char_id,
            "character_name": char_name,
            "text": req.text,
            "round": session["round"],
            "counters": dict(counters),
        }
    else:  # "send"
        # 人間プレイヤーは「積む→発言完」が1ターン完了とみなす（actions_per_turn に関わらず即時進行）
        session["turn"] = turn + 1
        session["action_count"] = 0
        _autosave(session_id)
        return {
            "action": "send",
            "turn_advanced": True,
            "character_id": current_char_id,
            "character_name": char_name,
            "text": req.text,
            "round": session["round"],
            "counters": dict(counters),
        }


@router.post("/{session_id}/vote/deliberate")
def vote_deliberate(session_id: str, req: VoteRequest):
    """弁明ラウンド: 全 AI キャラが意見を述べてセッションに保存し、結果を返す。"""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    initiative = session["initiative"]
    name_map = session["name_map"]
    char_backends = session.get("char_backends", {})
    default_backend = session.get("backend", DEFAULT_LLM_BACKEND)
    profiles = load_profiles()

    from def_kari.settings import load_settings as _load_settings_v
    _vlang = _load_settings_v().get("user_language", "ja")
    vote_labels = {
        "topic_change": "Change Topic" if _vlang == "en" else "お題変更",
        "expel": "Expel Participant" if _vlang == "en" else "参加者退場",
        "end_session": "End Session" if _vlang == "en" else "セッション終了",
    }
    vote_label = vote_labels.get(req.vote_type, req.vote_type)
    detail_text = f" — {req.detail}" if req.detail else ""

    # ターン位置を保存 (commit 時に復元する)
    session["_pending_vote"] = {
        "vote_type": req.vote_type,
        "detail": req.detail,
        "target_id": req.target_id,
        "proposer_id": req.proposer_id,
        "vote_label": vote_label,
        "detail_text": detail_text,
        "saved_turn": session["turn"],
        "saved_round": session["round"],
        "saved_action_count": session.get("action_count", 0),
        "deliberation_texts": {},
    }

    counters = session.setdefault("counters", {})
    if req.proposer_id:
        counters[req.proposer_id] = 0

    deliberations: list[dict] = []

    vote_announce = (
        f"[Vote Proposal] {vote_label}{detail_text}\nAll participants are asked for their opinion."
        if _vlang == "en" else
        f"[投票提案] {vote_label}{detail_text}\n参加者全員に意見を求めます。"
    )
    session["history"].append({
        "role": "user",
        "content": vote_announce,
        "character_id": "_keeper",
    })
    deliberations.append({
        "character_id": "_keeper",
        "character_name": "GM",
        "text": vote_announce,
        "emotion": "neutral",
    })

    if req.proposer_id and req.proposer_text.strip():
        proposer_name = name_map.get(req.proposer_id, req.proposer_id)
        session["history"].append({
            "role": "assistant",
            "content": f"{proposer_name}: {req.proposer_text}",
            "character_id": req.proposer_id,
            "emotion": "neutral",
            "tags": [],
        })
        deliberations.append({
            "character_id": req.proposer_id,
            "character_name": proposer_name,
            "text": req.proposer_text,
            "emotion": "neutral",
        })
        session["_pending_vote"]["deliberation_texts"][req.proposer_id] = req.proposer_text

    _v_settings = load_settings()
    _v_lang = _v_settings.get("user_language", "ja") or "ja"
    _v_allowed_sexual = _v_settings.get("allowed_rating_sexual", ["general"])
    _v_allowed_violence = _v_settings.get("allowed_rating_violence", ["general"])

    for char_id in initiative:
        char = get_character(char_id, profiles)
        char_name = name_map.get(char_id, char_id)

        # 人間プレイヤーは LLM 生成をスキップ
        if char and char.get("player_type") == "human":
            continue

        bid = char_backends.get(char_id) or default_backend
        if bid not in LLM_BACKENDS:
            bid = DEFAULT_LLM_BACKEND
        model = LLM_BACKENDS.get(bid, {}).get("default_model", "")

        deliberation_prompt = _sp("deliberation_prompt", _v_lang).format(
            vote_label=vote_label, detail_text=detail_text
        )

        _v_prev_emotion = next(
            (h.get("emotion", "neutral") for h in reversed(session["history"])
             if h.get("character_id") == char_id),
            "neutral",
        )
        if isinstance(_v_prev_emotion, list):
            _v_prev_emotion = ", ".join(_v_prev_emotion)
        _v_session_ctx = _build_session_context(
            session.get("topic", ""), session.get("rules", []),
            initiative, name_map, char_name, _v_lang,
        )
        _v_history = []
        for h in session["history"][-20:]:
            _raw = h["content"]
            _h_role = h.get("role", "user")
            _h_cid = h.get("character_id")
            if _h_role == "assistant" and _h_cid:
                _text = _raw.split(": ", 1)[-1] if ": " in _raw else _raw
                if _h_cid == char_id:
                    _v_history.append({"role": "assistant", "content": _text})
                else:
                    _oname = name_map.get(_h_cid, _h_cid)
                    _v_history.append({"role": "user", "content": f"[{_oname}] {_text}"})
            else:
                _v_history.append({"role": _h_role, "content": _raw})
        try:
            result = generate_structured_reply(
                user_text=deliberation_prompt,
                history=_v_history,
                model=model,
                character=char,
                backend=bid,
                allowed_sexual=_v_allowed_sexual,
                allowed_violence=_v_allowed_violence,
                current_emotion=_v_prev_emotion,
                session_context=_v_session_ctx,
            )
            dialogue = ""
            emotion = "neutral"
            if result.get("success") and result.get("result"):
                parsed = result["result"]
                dialogue = parsed.get("dialogue", "")
                emotion = parsed.get("emotion", "neutral")
            if not dialogue:
                dialogue = _sp("no_deliberation", _v_lang) or "(弁明なし)"
        except Exception:
            dialogue = _sp("no_deliberation", _v_lang) or "(弁明なし)"
            emotion = "neutral"

        session["history"].append({
            "role": "assistant",
            "content": f"{char_name}: {dialogue}",
            "character_id": char_id,
            "emotion": emotion,
            "tags": [],
        })
        deliberations.append({
            "character_id": char_id,
            "character_name": char_name,
            "text": dialogue,
            "emotion": emotion,
        })
        session["_pending_vote"]["deliberation_texts"][char_id] = dialogue

    _autosave(session_id)
    return {"deliberations": deliberations, "counters": dict(counters)}


@router.post("/{session_id}/vote/commit")
def vote_commit(session_id: str, req: VoteCommitRequest):
    """キーパー票を受け取り、AI票と合算して集計・効果適用する。"""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    pending = session.get("_pending_vote")
    if not pending:
        return {"error": "No pending vote"}

    initiative = session["initiative"]
    name_map = session["name_map"]
    char_backends = session.get("char_backends", {})
    default_backend = session.get("backend", DEFAULT_LLM_BACKEND)
    profiles = load_profiles()

    vote_type = pending["vote_type"]
    vote_label = pending["vote_label"]
    detail_text = pending["detail_text"]
    detail = pending["detail"]
    target_id = pending["target_id"]
    deliberation_texts = pending["deliberation_texts"]

    from def_kari.resources.vram_lock import get_vram_lock
    from def_kari.settings import load_settings as _load_settings
    _vram_lock = get_vram_lock()
    _force_approve = bool(_load_settings().get("vote_force_approve", False))

    proposer_id = pending.get("proposer_id", "")
    _v_lang = _load_settings().get("user_language", "ja") or "ja"

    results: dict[str, bool] = {}
    for char_id in initiative:
        char = get_character(char_id, profiles)

        # 人間プレイヤーは LLM 判定せず keeper_vote（ボタンクリック）を直接使う
        if char and char.get("player_type") == "human":
            results[char_id] = req.keeper_vote
            continue

        bid = char_backends.get(char_id) or default_backend
        if bid not in LLM_BACKENDS:
            bid = DEFAULT_LLM_BACKEND
        model = LLM_BACKENDS.get(bid, {}).get("default_model", "")
        dialogue = deliberation_texts.get(char_id, "")

        if _force_approve:
            results[char_id] = True
            continue

        judge_prompt = _sp("judge_prompt", _v_lang).format(
            dialogue=dialogue, vote_label=vote_label, detail_text=detail_text,
            yes_word=_sp("yes_word", _v_lang), no_word=_sp("no_word", _v_lang),
        )
        try:
            chat_fn = LLM_BACKENDS[bid]["chat"]
            messages = [
                {"role": "system", "content": char.get("persona_description", "")},
                {"role": "user", "content": judge_prompt},
            ]
            _vram_lock.acquire()
            try:
                reply = chat_fn(messages, model, json_mode=False, options={"num_predict": 32})
            finally:
                _vram_lock.release()
            results[char_id] = _sp("yes_word", _v_lang) in reply or "yes" in reply.lower()
        except Exception:
            results[char_id] = True

    if proposer_id:
        # 人間キャラがいる場合: LLM がキーパーとして追加投票
        bid = default_backend if default_backend in LLM_BACKENDS else DEFAULT_LLM_BACKEND
        model = LLM_BACKENDS.get(bid, {}).get("default_model", "")
        if _force_approve:
            results["_keeper"] = True
        else:
            all_texts = "\n".join(
                f"{name_map.get(cid, cid)}: {text}"
                for cid, text in deliberation_texts.items()
                if text
            )
            keeper_judge_prompt = _sp("keeper_judge_prompt", _v_lang).format(
                vote_label=vote_label, detail_text=detail_text, all_texts=all_texts,
                yes_word=_sp("yes_word", _v_lang), no_word=_sp("no_word", _v_lang),
            )
            try:
                chat_fn = LLM_BACKENDS[bid]["chat"]
                keeper_msgs = [
                    {"role": "system", "content": _sp("keeper_system", _v_lang) or "あなたはセッションのキーパー（GM・司会者）です。"},
                    {"role": "user", "content": keeper_judge_prompt},
                ]
                _vram_lock.acquire()
                try:
                    reply = chat_fn(keeper_msgs, model, json_mode=False, options={"num_predict": 32})
                finally:
                    _vram_lock.release()
                results["_keeper"] = _sp("yes_word", _v_lang) in reply or "yes" in reply.lower()
            except Exception:
                results["_keeper"] = True
    else:
        # 人間キャラなし: キーパー票はボタンクリックで決まる
        results["_keeper"] = req.keeper_vote

    yes_count = sum(1 for v in results.values() if v)
    no_count = len(results) - yes_count
    passed = yes_count > no_count

    if passed:
        if vote_type == "topic_change" and detail:
            session["topic"] = detail
        elif vote_type == "expel" and target_id:
            session["initiative"] = [c for c in initiative if c != target_id]

    # イベントバス通知（vote結果をゲームロジックレイヤーへ伝播）
    if passed:
        from def_kari.gm.events import game_event_bus, TOPIC_CHANGED, SESSION_ENDED
        if vote_type == "topic_change" and detail:
            game_event_bus.emit(session_id, TOPIC_CHANGED, {"new_topic": detail})
        elif vote_type == "end_session":
            game_event_bus.emit(session_id, SESSION_ENDED, {})

    # ターン位置を復元
    session["turn"] = pending["saved_turn"]
    session["round"] = pending["saved_round"]
    session["action_count"] = pending["saved_action_count"]

    # expel 可決時: 退場者が saved_turn より前にいた場合は turn を -1 してからクランプ
    if passed and vote_type == "expel" and target_id:
        new_init = session["initiative"]
        expelled_idx = initiative.index(target_id) if target_id in initiative else -1
        if expelled_idx >= 0 and expelled_idx < session["turn"]:
            session["turn"] -= 1
        if len(new_init) > 0 and session["turn"] >= len(new_init):
            session["turn"] = len(new_init) - 1
        elif len(new_init) == 0:
            session["turn"] = 0

    vote_for_label = _sp("vote_for", _v_lang) or "賛成"
    vote_against_label = _sp("vote_against", _v_lang) or "反対"
    keeper_label = _sp("keeper_label", _v_lang) or "キーパー"
    human_vote_label = vote_for_label if req.keeper_vote else vote_against_label
    keeper_llm_label = vote_for_label if results.get("_keeper") else vote_against_label
    if proposer_id:
        vote_detail_str = (
            f"{name_map.get(proposer_id, proposer_id)}: {human_vote_label}, "
            f"{keeper_label}: {keeper_llm_label}"
        )
    else:
        vote_detail_str = f"{keeper_label}: {human_vote_label}"
    outcome = _sp("vote_passed" if passed else "vote_rejected", _v_lang) or ("✅ 可決" if passed else "❌ 否決")
    result_text = (_sp("vote_result", _v_lang) or "🗳 {vote_label}{detail_text} — {yes_count}/{no_count}（{vote_detail_str}） → {outcome}").format(
        vote_label=vote_label, detail_text=detail_text,
        yes_count=yes_count, no_count=no_count,
        vote_detail_str=vote_detail_str, outcome=outcome,
    )
    session["history"].append({
        "role": "user",
        "content": result_text,
        "character_id": "_keeper",
    })

    session.pop("_pending_vote", None)

    ended = passed and vote_type == "end_session"
    if ended:
        _save_session_episodic(session_id, session)
        _delete_autosave(session_id)
        from def_kari.gm.events import game_event_bus
        game_event_bus.clear_log(session_id)
    else:
        _autosave(session_id)
    return {
        "results": {name_map.get(k, k) if k != "_keeper" else keeper_label: v for k, v in results.items()},
        "yes_count": yes_count,
        "no_count": no_count,
        "passed": passed,
        "result_text": result_text,
        "vote_type": vote_type,
        "ended": ended,
        "initiative": session["initiative"],
        "topic": session.get("topic", ""),
    }


@router.get("/{session_id}/events")
def get_session_events(session_id: str):
    """セッションのゲームロジックイベントログを返す（Observer Agent用）。"""
    from def_kari.gm.events import game_event_bus
    return {"session_id": session_id, "events": game_event_bus.get_log(session_id)}


class NpcKnowledgeRequest(BaseModel):
    entry: str


class NpcRelationshipRequest(BaseModel):
    char_id: str
    trust: int | None = None
    hostility: int | None = None


@router.post("/{session_id}/npc/{npc_id}/knowledge")
def add_npc_knowledge(session_id: str, npc_id: str, req: NpcKnowledgeRequest):
    """NPC が新たな情報を獲得したとき knowledge に追加する。

    GM または自動ゲームロジックから呼び出す。
    """
    session = _sessions.get(session_id)
    if not session:
        return {"error": "session not found"}
    npc_state = session.setdefault("npc_state", {})
    npc = npc_state.setdefault(npc_id, {"knowledge": [], "relationship": {}})
    if req.entry and req.entry not in npc["knowledge"]:
        npc["knowledge"].append(req.entry)
        from def_kari.gm.events import game_event_bus, FLAG_UPDATED
        game_event_bus.emit(session_id, FLAG_UPDATED, {
            "key": f"npc_{npc_id}_knowledge",
            "value": req.entry,
            "gm_only": True,
        })
    return {"npc_id": npc_id, "knowledge": npc["knowledge"]}


@router.post("/{session_id}/npc/{npc_id}/relationship")
def update_npc_relationship(session_id: str, npc_id: str, req: NpcRelationshipRequest):
    """NPC の特定キャラクターへの関係値を更新する。

    trust / hostility は None を渡すと変更しない（部分更新）。
    """
    session = _sessions.get(session_id)
    if not session:
        return {"error": "session not found"}
    npc_state = session.setdefault("npc_state", {})
    npc = npc_state.setdefault(npc_id, {"knowledge": [], "relationship": {}})
    rel = npc["relationship"].setdefault(req.char_id, {"trust": 50, "hostility": 0})
    if req.trust is not None:
        rel["trust"] = max(0, min(100, req.trust))
    if req.hostility is not None:
        rel["hostility"] = max(0, min(100, req.hostility))
    return {"npc_id": npc_id, "char_id": req.char_id, "relationship": rel}


@router.get("/{session_id}/npc/{npc_id}/state")
def get_npc_state(session_id: str, npc_id: str):
    """NPC の現在の動的状態を返す（GM確認用）。"""
    session = _sessions.get(session_id)
    if not session:
        return {"error": "session not found"}
    npc_state = session.get("npc_state", {})
    return {"npc_id": npc_id, "state": npc_state.get(npc_id, {"knowledge": [], "relationship": {}})}


@router.get("/debug")
def get_session_debug():
    return _last_session_debug


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


@router.delete("/saved/{filename}")
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
        "actions_per_turn": meta.get("actions_per_turn", 2),
        "action_count": 0,
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
        "actions_per_turn": session["actions_per_turn"],
    }


class SaveSessionMediaItem(BaseModel):
    index: int
    image_url: str = ""
    audio_url: str = ""

class SaveSessionRequest(BaseModel):
    media: list[SaveSessionMediaItem] = []

@router.post("/{session_id}/save")
def save_session(session_id: str, req: SaveSessionRequest = Body(default=SaveSessionRequest())):
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
        "rules": session.get("rules", []),
        "round": session.get("round", 1),
        "turn": session.get("turn", 0),
        "initiative": session.get("initiative", []),
        "name_map": session.get("name_map", {}),
        "actions_per_turn": session.get("actions_per_turn", 2),
        "saved_at": datetime.datetime.now().strftime("%Y%m%d_%H%M%S"),
    }
    save_session_mode(
        session_id=session_id,
        participants=session.get("initiative", []),
        history=history,
        metadata=metadata,
    )
    _delete_autosave(session_id)
    return {"status": "ok"}


class SessionGenerateImageRequest(BaseModel):
    backend: str = DEFAULT_LLM_BACKEND
    t2i_backend: str = ""
    t2i_model: str = ""
    t2i_prompt_mode: str = ""


@router.post("/{session_id}/generate-image")
def generate_session_image(session_id: str, req: SessionGenerateImageRequest):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}

    history = session.get("history", [])
    initiative = session.get("initiative", [])
    actions_per_turn = session.get("actions_per_turn", 2)
    name_map = session.get("name_map", {})
    topic = session.get("topic", "")
    scene = session.get("scene", "")

    # 直近ラウンドの発言を取得
    round_size = max(len(initiative) * actions_per_turn, 1)
    last_round = [h for h in history[-round_size * 2:] if h.get("role") == "assistant"][-round_size:]

    from def_kari.settings import load_settings as _load_settings
    _settings = _load_settings()
    t2i_prompt_mode = req.t2i_prompt_mode or _settings.get("t2i_prompt_mode", "current")

    def _dedup_tags(prompt: str, max_tags: int = 256) -> str:
        raw = [t.strip() for t in prompt.split(',') if t.strip()]
        seen: set[str] = set()
        unique: list[str] = []
        for t in raw:
            k = t.lower()
            if k not in seen:
                seen.add(k)
                unique.append(t)
        return ', '.join(unique[:max_tags])

    def _append_appearance_tags(prompt: str, last_char_id: str | None) -> str:
        if not last_char_id:
            return prompt
        _profiles = load_profiles()
        _char = get_character(last_char_id, _profiles)
        _app_tags = _char.get("appearance_tags", "").strip()
        if _app_tags:
            return prompt + ", " + _app_tags if prompt else _app_tags
        return prompt

    _last_char_id = last_round[-1].get("character_id") if last_round else None

    if t2i_prompt_mode == "passthrough":
        # LLM不使用: history の image_prompt_en を直接流用
        try:
            _ip_parts = [h.get("image_prompt_en", "") for h in last_round if h.get("image_prompt_en")]
            image_prompt = ", ".join(_ip_parts)
            if not image_prompt and scene:
                image_prompt = scene
            image_prompt = _append_appearance_tags(image_prompt, _last_char_id)
            image_prompt = _dedup_tags(image_prompt)
        except Exception as e:
            return {"error": f"image prompt (passthrough) failed: {e}"}

    else:
        # current / dedicated: LLM経由でタグ生成
        dialogue_block = "\n".join(
            f"{name_map.get(h.get('character_id', ''), h.get('character_id', ''))}: "
            f"{h.get('content', '').split(': ', 1)[-1]}"
            for h in last_round
        ) if last_round else ""

        scene_line = f"Base scene tags: {scene}" if scene else ""
        topic_line = f"Session topic: {topic}" if topic else ""
        dialogue_line = f"Recent dialogue (for character count and mood):\n{dialogue_block}" if dialogue_block else ""

        if t2i_prompt_mode == "dedicated":
            # dedicated: 出力制約を強化（thinkingモデル対策）
            user_text = "\n".join(filter(None, [scene_line, topic_line, dialogue_line])) + (
                "\n\nIMMEDIATELY output 10-20 Danbooru image tags, comma-separated. "
                "Visual tags only (characters, setting, mood, lighting). "
                "NO words like 'courageous', 'bold', 'daring' — only what can be SEEN. "
                "NO explanation. NO reasoning. First token must be a tag."
            )
            system_prompt = (
                "Image tag generator. Output comma-separated Danbooru tags ONLY. "
                "Start your response with the first tag immediately. "
                "No prose, no reasoning, no abstract concepts. "
                "Only visual descriptors: people, objects, setting, lighting, color, composition."
            )
            num_predict = 128
        else:
            # current: 既存のプロンプト
            user_text = "\n".join(filter(None, [scene_line, topic_line, dialogue_line])) + (
                "\n\nOutput ONLY Danbooru-style image tags in English, comma-separated. "
                "Start from the base scene tags above and add character count, emotions, and mood from the dialogue. "
                "No explanation. No reasoning. Tags only."
            )
            system_prompt = (
                "You are an image prompt generator for Stable Diffusion. "
                "Output ONLY Danbooru-style image tags, comma-separated. "
                "Do NOT think out loud. Do NOT explain. Output tags immediately."
            )
            num_predict = 512

        backend_id = req.backend or session.get("backend", DEFAULT_LLM_BACKEND)
        if backend_id not in LLM_BACKENDS:
            backend_id = DEFAULT_LLM_BACKEND

        try:
            chat_fn = LLM_BACKENDS[backend_id]["chat"]
            model = LLM_BACKENDS.get(backend_id, {}).get("default_model", "")
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ]
            from def_kari.resources.vram_lock import get_vram_lock
            _vram_lock_llm = get_vram_lock()
            _vram_lock_llm.acquire()
            try:
                image_prompt = chat_fn(messages, model, json_mode=False, options={"num_predict": num_predict})
            finally:
                _vram_lock_llm.release()
            image_prompt = re.sub(r'#(\w)', r'\1', image_prompt).strip().strip('"').strip("'")
            image_prompt = _append_appearance_tags(image_prompt, _last_char_id)
            image_prompt = _dedup_tags(image_prompt)
        except Exception as e:
            return {"error": f"image prompt generation failed: {e}"}

    if not image_prompt:
        return {"error": "empty image prompt"}

    try:
        from def_kari.settings import load_settings
        from def_kari.api.routes.t2i import set_t2i_debug
        settings = load_settings()
        t2i_backend = req.t2i_backend or settings.get("t2i_backend", "")
        if not t2i_backend:
            return {"error": "T2Iバックエンドが未設定です"}
        t2i_model = req.t2i_model or settings.get(f"t2i_model_{t2i_backend}") or None
        workflow = settings.get("comfyui_workflow", "default") if t2i_backend == "comfyui" else ""
        width = int(settings.get("session_t2i_width") or settings.get("t2i_width", 512))
        height = int(settings.get("session_t2i_height") or settings.get("t2i_height", 768))
        from def_kari.models.t2i_profiles import get_quality_settings
        quality_tags, default_neg = get_quality_settings(t2i_model)
        prompt_final = f"{image_prompt}, {quality_tags}" if quality_tags else image_prompt
        t2i_debug = {
            "backend": t2i_backend,
            "model": t2i_model or "",
            "workflow": workflow,
            "t2i_prompt_mode": t2i_prompt_mode,
            "prompt_input": image_prompt,
            "quality_tags": quality_tags,
            "prompt_final": prompt_final,
            "negative_prompt": default_neg,
            "width": width,
            "height": height,
        }
        set_t2i_debug(t2i_debug)
        from def_kari.resources.vram_lock import get_vram_lock
        _vram_lock = get_vram_lock()
        _vram_lock.acquire()
        try:
            image_path = _generate_t2i_image(
                prompt=prompt_final,
                width=width,
                height=height,
                model=t2i_model,
                backend=t2i_backend,
                negative_prompt=default_neg,
                workflow_name=workflow,
            )
        finally:
            _vram_lock.release()
        filename = image_path.split("/")[-1].split("\\")[-1]
        t2i_debug["url"] = f"/api/t2i/image/{filename}"
        set_t2i_debug(t2i_debug)
        return {"url": f"/api/t2i/image/{filename}", "prompt": prompt_final}
    except Exception as e:
        return {"error": str(e)}


@router.get("/{session_id}")
def get_session(session_id: str):
    session = _sessions.get(session_id)
    if not session:
        return {"error": "Session not found"}
    return {"session": session}
