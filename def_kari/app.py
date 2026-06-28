"""DEF(kari) MVP — Streamlitエントリーポイント

Phase 4完了版: TGW自動ロード、実TTS/T2I連携、翻訳プロバイダC2方式を含む。
"""

import os
import uuid
from pathlib import Path

_env_path = Path(__file__).parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                if _k.strip() and _k.strip() not in os.environ:
                    os.environ[_k.strip()] = _v.strip()

import streamlit as st

import time

from def_kari.config import (
    ACTIVE_POLL_MS, IDLE_POLL_MS, MAX_VISIBLE_TURNS, IMAGE_INTERVAL_SEC,
    T2I_MODE_END, T2I_MODE_START, T2I_MODE_MANUAL, T2I_MODE_INTERVAL,
    T2I_MODES, T2I_MODE_LABELS, DEFAULT_T2I_MODE,
    T2I_PROMPT_FORMATS, T2I_PROMPT_FORMAT_LABELS, DEFAULT_T2I_PROMPT_FORMAT,
    T2I_BACKENDS, T2I_BACKEND_LABELS, DEFAULT_T2I_BACKEND,
    DEFAULT_STATUS_POLL_SEC,
)
from def_kari.core.queues import get_queues
from def_kari.core.dispatcher import drain_events, apply_event
from def_kari.resources.vram_lock import get_vram_lock
from def_kari.llm.client import generate_structured_reply
from def_kari.llm.backend import DEFAULT_LLM_BACKEND, LLM_BACKENDS, LLM_BACKEND_LABELS
from def_kari.llm.tgw_manager import is_running as tgw_is_running, is_model_loaded as tgw_model_loaded, load_model_async, list_available_models, get_loaded_model_name
from def_kari.models.registry import get_quirks
from def_kari.history.store import load_full, save_session, trim_session, clear_history, save_session_mode, load_session_mode, list_session_mode_files
from def_kari.settings import load_settings, save_settings, PERSISTED_KEYS
from def_kari.characters import load_profiles, get_character, get_raw_profile, list_character_choices, save_profile, apply_name_reading, get_tts_speaker_id, DEFAULT_CHARACTER_ID
import def_kari.secrets_store as secrets_store
from def_kari.workers.runner import start_worker
from def_kari.ui.sidebar import render_sidebar
from def_kari.ui.chat_panel import render_chat_panel

st.set_page_config(page_title="DEF(kari) MVP", layout="wide")

_ACTION_DIRECTIVES_DIRS = [
    os.path.join(os.path.dirname(__file__), "..", "data", "public", "action_directives"),
    os.path.join(os.path.dirname(__file__), "..", "data", "private", "action_directives"),
]
_SESSION_RULES_DIRS = [
    os.path.join(os.path.dirname(__file__), "..", "data", "public", "session_rules"),
    os.path.join(os.path.dirname(__file__), "..", "data", "private", "session_rules"),
]

def _load_session_rules() -> dict:
    import json as _jl
    rules = {}
    for _dir in _SESSION_RULES_DIRS:
        if os.path.isdir(_dir):
            for _fname in sorted(os.listdir(_dir)):
                if _fname.endswith(".json"):
                    try:
                        with open(os.path.join(_dir, _fname), encoding="utf-8") as f:
                            _data = _jl.load(f)
                            _id = _data.get("id", _fname.replace(".json", ""))
                            rules[_id] = _data
                    except (_json.JSONDecodeError, OSError):
                        pass
    if not rules:
        rules["none"] = {"label": "ルールなし", "rules": []}
    return rules

def _generate_session_illustration():
    """セッションの直近発言からイラストを同期生成し、履歴に追加する。"""
    _hist = st.session_state.get("session_history", [])
    _last_dialogue = next(
        (h for h in reversed(_hist) if h.get("speaker") != "_keeper" and h.get("text")),
        None,
    )
    if not _last_dialogue:
        return
    _prompt = _last_dialogue.get("image_prompt_en", "")
    if not _prompt:
        _text = _last_dialogue.get("text", "")
        _speaker_id = _last_dialogue.get("speaker", "")
        _speaker_char = get_character(_speaker_id, _profiles) if _speaker_id else {}
        _appearance = _speaker_char.get("appearance_tags", "")
        _prompt = _appearance if _appearance else "portrait"
    if st.session_state.get("emotion_tag_enabled", True):
        _last_emotion = _last_dialogue.get("emotion", "neutral")
        if _last_emotion:
            from def_kari.image_prompt.emotion_tags import apply_emotion_tags
            _prompt = apply_emotion_tags(_prompt, _last_emotion)
    try:
        from def_kari.workers._t2i_generate import generate_image
        _img_path = generate_image(
            prompt=_prompt,
            width=st.session_state.get("session_t2i_width", 512),
            height=st.session_state.get("session_t2i_height", 512),
            model_name=st.session_state.get("t2i_model", ""),
            backend=st.session_state.get("t2i_backend", "a1111"),
        )
        _round = st.session_state.get("session_round", 1)
        _turn = st.session_state.get("session_turn", 0)
        _new_hist = list(st.session_state.get("session_history", []))
        _new_hist.append({
            "speaker": "_keeper",
            "text": "🎨 挿図",
            "image_path": _img_path,
            "round": _round,
            "turn": _turn,
            "action": -1,
        })
        st.session_state.session_history = _new_hist
        print(f"[SESSION T2I] generated: {_img_path}")
    except Exception as _t2i_err:
        st.error(_t('error_image_failed') + str(_t2i_err))
        print(f"[SESSION T2I] error: {_t2i_err}")


def _end_session():
    _sid = st.session_state.get("session_id", "unknown")
    _participants = st.session_state.get("session_initiative", [])
    _hist = st.session_state.get("session_history", [])
    if _hist:
        _meta = {
            "topic": st.session_state.get("session_topic", ""),
            "rule_set": st.session_state.get("session_rule_set", "default"),
            "round": st.session_state.get("session_round", 1),
            "counters": st.session_state.get("session_counters", {}),
        }
        save_session_mode(_sid, _participants, _hist, _meta)
        print(f"[SESSION] saved: {_sid}, {len(_hist)} entries")
    st.session_state.session_active = False


def _get_ext_model(backend_id: str) -> str:
    return (
        st.session_state.get(f"llm_ext_model_{backend_id}")
        or LLM_BACKENDS.get(backend_id, {}).get("default_model", "")
        or st.session_state.get("llm_ext_model", "")
    )

def _get_wav_duration(path: str) -> float:
    try:
        import wave
        with wave.open(path, "r") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0

def _clickable_image(path: str, width: int = 400):
    _fname = os.path.basename(path)
    _url = f"/app/static/{_fname}"
    st.markdown(
        f'<a href="{_url}" target="_blank">'
        f'<img src="{_url}" width="{width}" style="cursor:pointer; border-radius:4px;">'
        f'</a>',
        unsafe_allow_html=True,
    )

def _load_action_directives() -> dict:
    import json as _jl
    directives = {}
    for _dir in _ACTION_DIRECTIVES_DIRS:
        if os.path.isdir(_dir):
            for _fname in sorted(os.listdir(_dir)):
                if _fname.endswith(".json"):
                    try:
                        with open(os.path.join(_dir, _fname), encoding="utf-8") as f:
                            _data = _jl.load(f)
                            _id = _data.get("id", _fname.replace(".json", ""))
                            directives[_id] = _data
                    except (_json.JSONDecodeError, OSError):
                        pass
    if not directives:
        directives["none"] = {"label": "指示なし", "directives": {}}
    return directives

task_q, result_q = get_queues()
vram_lock = get_vram_lock()

# --- ワーカースレッド起動 ---
if "_worker_started" not in st.session_state:
    start_worker(task_q, result_q, vram_lock)
    st.session_state._worker_started = True

if "_vram_lock" not in st.session_state:
    st.session_state._vram_lock = vram_lock

# --- session_state初期化 ---
_DEFAULTS = {
    "safety_level": "warn",
    "tts_enabled": True,
    "tts_human_enabled": False,
    "tts_backend": "voicevox",
    "interval_ms": IDLE_POLL_MS,
    "llm_backend": DEFAULT_LLM_BACKEND,
    "tgw_autoload_model": "",
    "tgw_autoload_attempted": False,
    "c2_method": "none",
    "deepl_api_key": "",
    "active_character": DEFAULT_CHARACTER_ID,
    "t2i_trigger_mode": DEFAULT_T2I_MODE,
    "last_interval_image_time": 0.0,
    "undo_max_history": 5,
    "character_greeting": True,
    "t2i_prompt_format": DEFAULT_T2I_PROMPT_FORMAT,
    "t2i_backend": DEFAULT_T2I_BACKEND,
    "t2i_model": None,
    "t2i_width": 512,
    "t2i_height": 768,
    "session_t2i_width": 512,
    "session_t2i_height": 512,
    "civitai_api_token": "",
    "llm_ext_model": "",
    "llm_ext_model_openai": "",
    "llm_ext_model_gemini": "",
    "llm_ext_model_anthropic": "",
    "status_poll_sec": DEFAULT_STATUS_POLL_SEC,
    "session_actions_per_turn": 3,
    "session_action_directive_set": "default",
    "session_repeat_penalty_count": 3,
    "session_rule_set": "default",
    "user_language": "ja",
    "comfyui_workflow": "default",
    "episode_candidate_count": 3,
    "episode_t2i_width": 1216,
    "episode_t2i_height": 832,
    "emotion_tag_enabled": True,
    "rating_sexual_strength": "general_only",
    "rating_violence_strength": "general_only",
    "allowed_rating_sexual": ["general"],
    "allowed_rating_violence": ["general"],
}
_saved = load_settings()
for key, default in _DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = _saved.get(key, default)

if "history" not in st.session_state:
    _init_char = st.session_state.get("active_character", DEFAULT_CHARACTER_ID)
    full = load_full(_init_char)
    st.session_state.history = full[-MAX_VISIBLE_TURNS:] if full else []
    for m in st.session_state.history:
        m.setdefault("llm_attempts", [])

# --- i18n ---
from def_kari.i18n import t
_ui_lang = st.session_state.get("user_language", "ja")
_t = lambda key, **kw: t(key, lang=_ui_lang, **kw)

# --- バックエンド自動起動 ---
_cur_backend_key = f"{st.session_state.llm_backend}_{st.session_state.get('tts_backend', 'voicevox')}_{st.session_state.get('t2i_backend', 'a1111')}"
print(f"[AUTOSTART] cur={_cur_backend_key}, prev={st.session_state.get('_backends_started_key')}")
if st.session_state.get("_backends_started_key") != _cur_backend_key:
    from def_kari.backends import auto_start_backends
    _start_results = auto_start_backends(
        llm_backend=st.session_state.llm_backend,
        tts_backend=st.session_state.tts_backend,
        t2i_backend=st.session_state.get("t2i_backend", "a1111"),
    )
    for _name, _err in _start_results.items():
        if _err:
            st.toast(f"⚠ {_name} 自動起動失敗: {_err}")
    st.session_state._backends_started_key = _cur_backend_key

# --- TGW自動ロード ---
if st.session_state.llm_backend == "textgen_webui":
    if tgw_is_running() and not tgw_model_loaded():
        autoload = st.session_state.tgw_autoload_model
        if autoload and not st.session_state.tgw_autoload_attempted:
            st.session_state.tgw_autoload_attempted = True
            load_model_async(autoload)
            st.toast(f"モデル **{autoload}** のロードを開始しました。")

# --- APIキー管理ダイアログ ---
import json as _json
from pathlib import Path as _Path

_API_SERVICES_PATH = _Path(__file__).parent.parent / "data" / "api_services.json"


def _load_api_services() -> list[dict]:
    if _API_SERVICES_PATH.exists():
        try:
            return _json.loads(_API_SERVICES_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


@st.dialog(_t("settings_apikey"))
def _render_api_key_dialog():
    _services = _load_api_services()
    st.caption(
        _t("apikey_desc") if False else "外部API連携で使用するAPIキーをサービスごとに暗号化して保存します。"
        "環境変数が設定されている場合はそちらが優先されます。"
    )

    if st.button(_t("apikey_save_all") if False else "💾 すべて保存", type="primary"):
        _saved_any = False
        for svc in _services:
            _key = st.session_state.get(f"api_key_input_{svc['id']}", "")
            if _key:
                secrets_store.set_api_key(svc["id"], _key)
                _saved_any = True
        if _saved_any:
            st.success(_t("apikey_saved") if False else "APIキーを保存しました。")
        else:
            st.warning(_t("apikey_none") if False else "保存するAPIキーがありません。")

    st.divider()

    for svc in _services:
        _id = svc["id"]
        _label = svc["label"]
        _env = svc.get("env_var", "")
        _help = svc.get("help", "")
        _env_val = os.environ.get(_env, "") if _env else ""
        has_key = secrets_store.has_api_key(_id)

        st.markdown(f"**{_label}**")
        pass

        _col_input, _col_del = st.columns([4, 1])
        with _col_input:
            st.text_input(
                f"{_label} APIキー",
                type="password",
                placeholder="設定済み(変更する場合のみ入力)" if (has_key or _env_val) else "未設定",
                key=f"api_key_input_{_id}",
                label_visibility="collapsed",
            )
        with _col_del:
            if has_key and st.button("🗑", key=f"api_key_delete_{_id}", help=f"{_label}のキーを削除"):
                secrets_store.delete_api_key(_id)
                st.success(f"{_label}のAPIキーを削除しました。")


# --- キャラクター ---
_profiles = load_profiles()
_active_character = get_character(st.session_state.active_character, _profiles)

# --- サイドバー ---
render_sidebar()

# --- メイン ---
st.markdown(
    """<style>
    .stTabs [data-baseweb="tab-list"] { gap: 0.2rem; margin-bottom: 0; }
    .stTabs [data-baseweb="tab"] { padding: 0.15rem 0.6rem; font-size: 0.85rem; }
    .stTabs [data-baseweb="tab-panel"] { padding-top: 0.5rem; }
    .stMainBlockContainer { padding-top: 1.5rem; }
    h2 { margin: 0 0 0.3rem 0; font-size: 1.3rem; }
    </style>""",
    unsafe_allow_html=True,
)
st.markdown(f"## {_t('app_title')}")

tab_character, tab_chat, tab_session, tab_episode, tab_thought, tab_settings, tab_thinking = st.tabs([
    _t("tab_character"), _t("tab_chat"), _t("tab_session"), _t("tab_episode"), _t("tab_thought"), _t("tab_settings"), _t("tab_debug"),
])

with tab_chat:
    if st.session_state.get("_pending_greeting"):
        _greet = st.session_state.pop("_pending_greeting")
        _greet_text = f"Hello, {_greet['new_name']}. How are you?" if _ui_lang == "en" else f"こんにちは、{_greet['new_name']}。調子はどう？"
        _greet_display = f"(Switched from {_greet['previous_name']} to {_greet['new_name']})" if _ui_lang == "en" else f"(キャラクターが{_greet['previous_name']}から{_greet['new_name']}に切り替わりました)"
        _greet_char = get_character(st.session_state.active_character, _profiles)
        if st.session_state.llm_backend == "textgen_webui":
            _model_name = get_loaded_model_name() or ""
        else:
            _model_name = _get_ext_model(st.session_state.llm_backend)
        _greet_quirks = get_quirks(_model_name)
        _greet_result = generate_structured_reply(
            _greet_text,
            history=st.session_state.history,
            character=_greet_char,
            backend=st.session_state.llm_backend,
            quirks=_greet_quirks,
        )
        import uuid as _uuid
        _greet_id = str(_uuid.uuid4())
        if _greet_result["success"] and _greet_result["result"]:
            _gr = _greet_result["result"]
            _greet_msg = {
                "id": _greet_id,
                "sender": st.session_state.active_character,
                "user_text": _greet_display,
                "text": _gr["dialogue"],
                "emotion": _gr["emotion"],
                "image_prompt_en": _gr["image_prompt_en"],
                "tags": _gr["tags"],
                "llm_success": True,
                "llm_attempts": _greet_result["attempts"],
                "audio_path": None,
                "image_path": None,
                "state": "Text Rendered",
                "image_queued": False,
                "audio_enabled": st.session_state.tts_enabled,
            }
        else:
            _greet_msg = {
                "id": _greet_id,
                "sender": st.session_state.active_character,
                "user_text": _greet_display,
                "text": f"({_greet['new_name']} appeared)" if _ui_lang == "en" else f"（{_greet['new_name']}が現れた）",
                "emotion": "neutral",
                "image_prompt_en": "",
                "tags": [],
                "llm_success": False,
                "llm_attempts": _greet_result["attempts"],
                "audio_path": None,
                "image_path": None,
                "state": "Persist",
                "image_queued": False,
                "audio_enabled": False,
            }
        st.session_state.history.append(_greet_msg)
        if _greet_msg["audio_enabled"]:
            task_q.put({
                "kind": "tts",
                "msg_id": _greet_id,
                "emotion": _greet_msg["emotion"],
                "text": apply_name_reading(_greet_msg["text"], _greet_char),
                "tts_backend": st.session_state.tts_backend,
                "tts_speaker_id": get_tts_speaker_id(_greet_char, st.session_state.tts_backend),
            })
            _greet_msg["state"] = "TTS Running"
            st.session_state.interval_ms = ACTIVE_POLL_MS

        _greet_trigger = st.session_state.t2i_trigger_mode
        _greet_msg["t2i_trigger"] = _greet_trigger
        if _greet_trigger in (T2I_MODE_END, T2I_MODE_START):
            task_q.put({
                "kind": "image",
                "msg_id": _greet_id,
                "emotion": _greet_msg["emotion"],
                "image_prompt_en": _greet_msg.get("image_prompt_en", ""),
                "t2i_backend": st.session_state.t2i_backend,
                "t2i_model": st.session_state.t2i_model,
                "t2i_width": st.session_state.t2i_width,
                "t2i_height": st.session_state.t2i_height,
            })
            _greet_msg["image_queued"] = True
            st.session_state.interval_ms = ACTIVE_POLL_MS

        save_session(st.session_state.history, st.session_state.active_character)
        st.rerun()

    render_chat_panel(task_q)

    user_text = st.chat_input(_t("chat_input_placeholder"))
    if user_text:
        st.session_state._pending_user_text = user_text
        st.rerun()

    _pending = st.session_state.pop("_pending_user_text", None)
    print(f"[CHAT] _pending={_pending is not None}")
    if _pending:
        user_text = _pending
        with st.chat_message("user"):
            st.write(user_text)
        if st.session_state.llm_backend == "textgen_webui":
            _model_name = get_loaded_model_name() or ""
        else:
            _model_name = _get_ext_model(st.session_state.llm_backend)
        _quirks = get_quirks(_model_name)
        with st.spinner(_t("chat_thinking")):
            result = generate_structured_reply(
                user_text,
                history=st.session_state.history,
                model=_model_name,
                character=_active_character,
                backend=st.session_state.llm_backend,
                quirks=_quirks,
            )

        msg_id = str(uuid.uuid4())
        if result["success"] and result["result"]:
            r = result["result"]
            tags = r["tags"]
            if not tags:
                from def_kari.safety.filters import detect_tags_from_text
                tags = detect_tags_from_text(user_text + " " + r["dialogue"])
            if st.session_state.get("force_rating_override"):
                _force_tag = st.session_state.get("force_rating_tag", "nsfw")
                if _force_tag not in tags:
                    tags = [_force_tag]
                st.session_state.force_rating_override = False

            image_prompt_en = r["image_prompt_en"]
            c2 = st.session_state.get("c2_method", "none")
            if c2 != "none":
                import sys
                from pathlib import Path
                _t_dir = str(Path(__file__).parent / "translation")
                _i_dir = str(Path(__file__).parent / "image_prompt")
                if _t_dir not in sys.path:
                    sys.path.insert(0, _t_dir)
                if _i_dir not in sys.path:
                    sys.path.insert(0, _i_dir)
                try:
                    from translation_factory import create_provider
                    from tag_extractor import extract_flat_tags

                    provider_opts = {}
                    if c2 == "deepl":
                        dk = st.session_state.get("deepl_api_key", "")
                        if dk:
                            provider_opts["api_key"] = dk
                    elif c2 == "llm":
                        from def_kari.llm.adapters.tgw import TEXTGEN_WEBUI_URL
                        provider_opts["base_url"] = TEXTGEN_WEBUI_URL
                    provider = create_provider(c2, **provider_opts)
                    text_to_translate = "\n".join(
                        t for t in (user_text.strip(), r["dialogue"].strip()) if t
                    )
                    if text_to_translate:
                        translated = provider.translate(text_to_translate, "ja", "en")
                        if translated:
                            _fmt = st.session_state.get("t2i_prompt_format", "danbooru")
                            if _fmt == "natural":
                                existing = [t.strip() for t in image_prompt_en.split(",") if t.strip()]
                                if translated.strip() not in existing:
                                    image_prompt_en = ", ".join(filter(None, [image_prompt_en, translated.strip()]))
                            else:
                                existing = [t.strip() for t in image_prompt_en.split(",") if t.strip()]
                                new_tags = [t for t in extract_flat_tags(translated) if t not in existing]
                                if new_tags:
                                    image_prompt_en = ", ".join(filter(None, [image_prompt_en, *new_tags]))
                except Exception:
                    pass

            # D方式: emotionに応じた補助タグ追記
            if st.session_state.get("emotion_tag_enabled", True):
                from def_kari.image_prompt.emotion_tags import apply_emotion_tags
                image_prompt_en = apply_emotion_tags(image_prompt_en, r["emotion"])

            msg = {
                "id": msg_id,
                "sender": st.session_state.active_character,
                "user_text": user_text,
                "text": r["dialogue"],
                "emotion": r["emotion"],
                "image_prompt_en": image_prompt_en,
                "tags": tags,
                "llm_success": True,
                "llm_attempts": result["attempts"],
                "audio_path": None,
                "image_path": None,
                "state": "Text Rendered",
                "image_queued": False,
                "audio_enabled": st.session_state.tts_enabled,
            }
        else:
            msg = {
                "id": msg_id,
                "sender": st.session_state.active_character,
                "user_text": user_text,
                "text": _t("error_generation_failed"),
                "emotion": "neutral",
                "image_prompt_en": "",
                "tags": [],
                "llm_success": False,
                "llm_attempts": result["attempts"],
                "audio_path": None,
                "image_path": None,
                "state": "Persist",
                "image_queued": False,
                "audio_enabled": False,
            }

        st.session_state.history.append(msg)

        print(f"[CHAT TTS] audio_enabled={msg['audio_enabled']}, backend={st.session_state.get('tts_backend')}")
        if msg["audio_enabled"]:
            task_q.put({
                "kind": "tts",
                "msg_id": msg_id,
                "emotion": msg["emotion"],
                "text": apply_name_reading(msg["text"], _active_character),
                "tts_backend": st.session_state.tts_backend,
                "tts_speaker_id": get_tts_speaker_id(_active_character, st.session_state.tts_backend),
            })
            msg["state"] = "TTS Running"
            st.session_state.interval_ms = ACTIVE_POLL_MS

        _image_task_base = {
            "kind": "image",
            "msg_id": msg_id,
            "t2i_backend": st.session_state.t2i_backend,
            "t2i_model": st.session_state.t2i_model,
            "t2i_width": st.session_state.t2i_width,
            "t2i_height": st.session_state.t2i_height,
        }
        trigger = st.session_state.t2i_trigger_mode
        msg["t2i_trigger"] = trigger
        if trigger == T2I_MODE_END:
            task_q.put({**_image_task_base,
                "emotion": msg["emotion"],
                "image_prompt_en": msg["image_prompt_en"],
            })
            msg["image_queued"] = True
        elif trigger == T2I_MODE_START:
            if len(st.session_state.history) >= 2:
                prev = st.session_state.history[-2]
                _prev_emotion = prev["emotion"]
                _prev_prompt = prev.get("image_prompt_en", "")
            else:
                _prev_emotion = "neutral"
                _prev_prompt = ""
            task_q.put({**_image_task_base,
                "emotion": _prev_emotion,
                "image_prompt_en": _prev_prompt,
            })
            msg["image_queued"] = True
            msg["image_emotion"] = _prev_emotion

        save_session(st.session_state.history, st.session_state.active_character)
        st.session_state.history = trim_session(st.session_state.history)
        st.rerun()

with tab_session:
    st.subheader(_t("session_title"))
    st.caption(_t("session_desc"))

    # --- 参加者選択 ---
    _all_choices = list_character_choices(_profiles)
    _session_participants = st.session_state.get("session_participants", [])

    selected = st.multiselect(
        _t("session_participants"),
        options=[cid for cid, _ in _all_choices],
        format_func=lambda cid: dict(_all_choices).get(cid, cid),
        default=_session_participants,
        key="session_participant_select",
    )
    st.session_state.session_participants = selected

    if len(selected) < 1:
        st.info("Select 1 or more characters." if _ui_lang == "en" else "1人以上のキャラクターを選択してください。")
    else:
        col_participants, col_backend_btn = st.columns([3, 1])
        with col_participants:
            _lbl_p = "Participants" if _ui_lang == "en" else "参加者"
            st.write(f"**{_lbl_p}:** {len(selected)}")
            for cid in selected:
                name = dict(_all_choices).get(cid, cid)
                st.write(f"  - {name}")
        with col_backend_btn:
            if st.button(_t("session_ai_assign"), key="session_backend_config"):
                st.session_state._show_backend_config = not st.session_state.get("_show_backend_config", False)

        if st.session_state.get("_show_backend_config"):
            with st.container(border=True):
                st.caption(_t("session_backend_desc"))
                _char_backends = st.session_state.get("session_char_backends", {})
                _backend_options = [_t("session_follow_settings")] + list(LLM_BACKEND_LABELS.keys())
                _backend_display = {_t("session_follow_settings"): _t("session_follow_settings")}
                _backend_display.update(LLM_BACKEND_LABELS)

                for cid in selected:
                    name = dict(_all_choices).get(cid, cid)
                    _cur = _char_backends.get(cid, _t("session_follow_settings"))
                    _cur_idx = _backend_options.index(_cur) if _cur in _backend_options else 0
                    _sel = st.selectbox(
                        name,
                        _backend_options,
                        index=_cur_idx,
                        format_func=lambda k: _backend_display.get(k, k),
                        key=f"session_backend_{cid}",
                    )
                    if _sel != _t("session_follow_settings"):
                        _char_backends[cid] = _sel
                    elif cid in _char_backends:
                        del _char_backends[cid]

                if st.button(_t("settings_save") if "💾 保存" == "x" else "💾 保存", key="save_session_backends"):
                    st.session_state.session_char_backends = _char_backends
                    st.session_state._show_backend_config = False
                    st.toast(_t("settings_saved"))
                    st.rerun()

        _sr_sets_tab = _load_session_rules()
        _sr_keys_tab = list(_sr_sets_tab.keys())
        _sr_labels_tab = {k: _sr_sets_tab[k].get("label", k) for k in _sr_keys_tab}
        if st.session_state.get("session_rule_set") not in _sr_keys_tab:
            st.session_state.session_rule_set = _sr_keys_tab[0]
        st.selectbox(
            _t("session_rule_label"),
            _sr_keys_tab,
            format_func=lambda k: _sr_labels_tab.get(k, k),
            key="session_rule_set",
        )

        _session_topic = st.text_input(_t("session_topic_label"), value=st.session_state.get("session_topic", ""), placeholder=_t("session_topic_placeholder"))

        if st.button(_t("session_start"), disabled=len(selected) < 1):
            import time as _ts
            st.session_state.session_active = True
            st.session_state.session_id = f"session_{int(_ts.time())}"
            st.session_state.session_round = 1
            st.session_state.session_turn = 0
            st.session_state.session_current_action = 0
            st.session_state.session_history = []
            st.session_state.session_pending_actions = []
            st.session_state.session_redo_used = False
            st.session_state.session_keeper_instruction = ""
            st.session_state.session_topic = _session_topic
            st.session_state.session_human_pending = []
            import random
            st.session_state.session_initiative = random.sample(selected, len(selected))
            st.session_state.session_counters = {cid: 0 for cid in selected}
            _init_label = "Started! Order: " if _ui_lang == "en" else "セッション開始！ イニシアチブ順: "
            st.success(f"{_init_label}{' → '.join(dict(_all_choices).get(c, c) for c in st.session_state.session_initiative)}")

    # 自動進行の値管理（widget keyとは別に保持）
    if st.session_state.get("_force_pause"):
        st.session_state._force_pause = False
        st.session_state._keeper_agnostic = False
        st.session_state._ka_cb = False
    _keeper_agnostic = st.session_state.get("_keeper_agnostic", False)

    # --- セッション進行表示 ---
    if st.session_state.get("session_active"):
        st.divider()
        initiative = st.session_state.get("session_initiative", [])
        round_num = st.session_state.get("session_round", 1)
        turn_idx = st.session_state.get("session_turn", 0)
        _name_map = dict(_all_choices)

        # --- 立ち絵背景 ---
        import base64 as _b64
        from pathlib import Path as _StPath
        _standing_bases = [_StPath(__file__).parent.parent / "data" / "public" / "characters", _StPath(__file__).parent.parent / "data" / "private" / "characters"]
        _standing_images = []
        for _p_cid in initiative:
            _sp = None
            for _sb in _standing_bases:
                _sp_candidate = _sb / _p_cid / "standing.png"
                if _sp_candidate.exists():
                    _sp = _sp_candidate
                    break
            if _sp and _sp.exists():
                _img_b64 = _b64.b64encode(_sp.read_bytes()).decode()
                _standing_images.append(_img_b64)
        st.write(f"**Round {round_num}** — Turn {turn_idx + 1}/{len(initiative)}")
        _counters = st.session_state.get("session_counters", {})
        if initiative:
            current_speaker = initiative[turn_idx % len(initiative)]
            _init_parts = []
            for _ic, _icid in enumerate(initiative):
                _iname = _name_map.get(_icid, _icid)
                _cnt = _counters.get(_icid, 0)
                _cnt_str = f"[{_cnt:+d}]" if _cnt != 0 else "[0]"
                if _ic == (turn_idx % len(initiative)):
                    _init_parts.append(f"**▶{_iname}**{_cnt_str}")
                else:
                    _init_parts.append(f"{_iname}{_cnt_str}")
            st.write(" → ".join(_init_parts))

        # 立ち絵背景（画面固定）
        if _standing_images:
            _n = len(_standing_images)
            _img_tags = ""
            for _i, _sb64 in enumerate(_standing_images):
                _margin_left = 20 + int((_i / _n) * 70)
                _img_tags += (
                    f'<img src="data:image/png;base64,{_sb64}" '
                    f'style="position:fixed; bottom:0; left:{_margin_left}%; '
                    f'height:60vh; width:auto; opacity:0.15; pointer-events:none; z-index:0;" />'
                )
            st.markdown(f'<div>{_img_tags}</div>', unsafe_allow_html=True)

        # セッション履歴表示（固定高さスクロール領域）
        from def_kari.safety.filters import (
            is_flagged as _sf_is_flagged,
            effective_level as _sf_effective,
            should_mask_text as _sf_mask_text,
            should_hide_audio as _sf_hide_audio,
            should_autoplay_audio as _sf_autoplay,
            should_hide_image as _sf_hide_image,
            should_blur_image as _sf_blur_image,
        )
        _session_safety = st.session_state.get("safety_level", "warn")
        from pathlib import Path as _SPath
        _icon_bases = [_SPath(__file__).parent.parent / "data" / "public" / "characters", _SPath(__file__).parent.parent / "data" / "private" / "characters"]
        _session_hist = st.session_state.get("session_history", [])
        _latest_unplayed_audio = None
        for _ah in _session_hist:
            if _ah.get("audio_path") and not _ah.get("audio_played"):
                _latest_unplayed_audio = _ah
                break
        _session_container = st.container(height=600)
        with _session_container:
            for msg in st.session_state.get("session_history", []):
                if msg.get("speaker") == "_keeper":
                    with st.chat_message("user", avatar="🎩"):
                        _lbl_k = "Keeper" if _ui_lang == "en" else "キーパー"
                        st.write(f"**{_lbl_k}:** {msg.get('text', '')}")
                        if msg.get("image_path") and os.path.exists(msg["image_path"]):
                            _img_tags = msg.get("tags") or []
                            _img_flagged = _sf_is_flagged(
                                _img_tags,
                                allowed_sexual=st.session_state.get("allowed_rating_sexual"),
                                allowed_violence=st.session_state.get("allowed_rating_violence"),
                            )
                            _img_level = _sf_effective(_session_safety, _img_flagged, False)
                            if _sf_hide_image(_img_level):
                                st.caption(_t("safety_image_hidden"))
                            else:
                                _clickable_image(msg["image_path"], width=400)
                else:
                    speaker_name = _name_map.get(msg.get("speaker", ""), msg.get("speaker", ""))
                    _speaker_icon = None
                    for _ib in _icon_bases:
                        _ic = _ib / msg.get("speaker", "") / "icon.png"
                        if _ic.exists():
                            _speaker_icon = _ic
                            break
                    _avatar = str(_speaker_icon) if _speaker_icon else "🎭"
                    with st.chat_message("assistant", avatar=_avatar):
                        _msg_tags = msg.get("tags") or []
                        _msg_flagged = _sf_is_flagged(
                            _msg_tags,
                            allowed_sexual=st.session_state.get("allowed_rating_sexual"),
                            allowed_violence=st.session_state.get("allowed_rating_violence"),
                        )
                        _msg_level = _sf_effective(_session_safety, _msg_flagged, False)

                        if _sf_mask_text(_msg_level):
                            st.write(f"**{speaker_name}:** " + _t('safety_masked'))
                        elif _msg_flagged and _msg_level == "warn":
                            st.warning(f"⚠ Safety warning: tags={_msg_tags}" if _ui_lang == "en" else f"⚠ セーフティ警告: tags={_msg_tags}")
                            st.write(f"**{speaker_name}:** {msg.get('text', '')}")
                        else:
                            st.write(f"**{speaker_name}:** {msg.get('text', '')}")

                        if msg.get("audio_path") and os.path.exists(msg["audio_path"]):
                            if _sf_hide_audio(_msg_level):
                                st.caption(_t("safety_audio_hidden"))
                            else:
                                _is_latest_audio = (msg is _latest_unplayed_audio)
                                _autoplay = _is_latest_audio and _sf_autoplay(_msg_level)
                                st.audio(msg["audio_path"], autoplay=_autoplay)
                                if _is_latest_audio:
                                    msg["audio_played"] = True



        _actions_per_turn = st.session_state.get("session_actions_per_turn", 3)

        def _build_session_prompt(speaker_id, speaker_name, speaker_char, session_hist, action_idx=0, turn_actions=None):
            """セッション用プロンプトを構築する。"""
            _topic = st.session_state.get("session_topic", "")
            _s_initiative = st.session_state.get("session_initiative", [])
            _other_names = [_name_map.get(c, c) for c in _s_initiative if c != speaker_id]

            _context_messages = []
            if session_hist:
                _transcript_lines = []
                for sh in session_hist:
                    if sh.get("speaker") == "_keeper":
                        _transcript_lines.append(f"【キーパー指示】{sh.get('text', '')}")
                    else:
                        _sname = _name_map.get(sh.get("speaker", ""), sh.get("speaker", ""))
                        _transcript_lines.append(f"【{_sname}】{sh.get('text', '')}")
                _transcript = "\n".join(_transcript_lines)
                _context_messages.append({
                    "role": "user",
                    "content": f"これまでのセッションの発言記録です:\n\n{_transcript}",
                })

            _rule_set = _load_session_rules().get(
                st.session_state.get("session_rule_set", "default"), {}
            ).get("rules", [])
            if _rule_set:
                _session_rule = "【セッションルール】\n" + "\n".join(f"・{r}" for r in _rule_set) + "\n"
            else:
                _session_rule = ""

            if not session_hist and action_idx == 0:
                _user_text = _session_rule
                _user_text += f"\nこれは複数の参加者による討論セッションです。"
                if _topic:
                    _user_text += f"\n今日のお題: 「{_topic}」"
                _user_text += f"\n参加者: {', '.join(_name_map.get(c, c) for c in _s_initiative)}"
                _user_text += f"\nあなたは{speaker_name}です。対話相手は{', '.join(_other_names)}です。"
                _user_text += f"\nまず簡潔に自己紹介し、このお題に対するあなたの考えや立場を述べてください。"
            elif action_idx == 0:
                _user_text = _session_rule
                _user_text += f"\nあなたは{speaker_name}です。対話相手は{', '.join(_other_names)}です。"
                if _topic:
                    _user_text += f"\n今日のお題は「{_topic}」です。"
                _user_text += "\n上記の発言記録を踏まえ、他の参加者の発言を具体的に引用しながら、あなた自身の立場から意見を述べてください。"
            else:
                _prev = "\n".join(f"・{a}" for a in (turn_actions or []))
                _directive_set = _load_action_directives().get(
                    st.session_state.get("session_action_directive_set", "default"), {}
                ).get("directives", {})
                _directive = _directive_set.get(str(action_idx), "")
                if _directive:
                    _user_text = (
                        f"あなたは{speaker_name}です。このターンであなたは既に以下の発言をしています:\n{_prev}\n\n"
                        f"【アクション{action_idx + 1}の指示】{_directive}"
                    )
                else:
                    _user_text = (
                        f"あなたは{speaker_name}です。このターンであなたは既に以下の発言をしています:\n{_prev}\n\n"
                        f"続けて発言してください。"
                )

            return _context_messages, _user_text

        def _execute_session_action(keeper_instruction=""):
            """1アクション分の発言を生成してセッション履歴に追加する。"""
            _s_initiative = st.session_state.get("session_initiative", [])
            _s_turn = st.session_state.get("session_turn", 0)
            _s_round = st.session_state.get("session_round", 1)
            _act_i = st.session_state.get("session_current_action", 0)
            _designated = st.session_state.get("_session_designated_next")
            _speaker_id = _designated if _designated else _s_initiative[_s_turn % len(_s_initiative)]
            _speaker_char = get_character(_speaker_id, _profiles)
            _speaker_name = _speaker_char.get("name", _speaker_id)

            # 明示的にリストをコピーして操作
            _new_hist = list(st.session_state.get("session_history", []))

            # このターンの既発言を収集
            _turn_actions = [
                h["text"] for h in _new_hist
                if h.get("round") == _s_round and h.get("turn") == _s_turn and h.get("speaker") == _speaker_id
            ]

            _ctx, _user_text = _build_session_prompt(
                _speaker_id, _speaker_name, _speaker_char,
                _new_hist, _act_i, _turn_actions,
            )

            if keeper_instruction and _act_i == 0:
                _user_text += f"\n\n【キーパーからの最優先指示 — 必ず従うこと】\n{keeper_instruction}\nこの指示に従わない発言は無効です。一般論ではなく、あなた自身の具体的な体験を語ってください。"

            # キャラクターごとのバックエンド設定（未設定はグローバル設定に従う）
            _char_backends = st.session_state.get("session_char_backends", {})
            _global_backend = st.session_state.get("llm_backend", DEFAULT_LLM_BACKEND)
            _s_backend = _char_backends.get(_speaker_id, _global_backend)
            if _s_backend == "textgen_webui":
                _s_model = get_loaded_model_name() or ""
            else:
                _s_model = _get_ext_model(_s_backend)
            _quirks = get_quirks(_s_model)
            print(f"[SESSION] speaker={_speaker_name}, backend={_s_backend}, model={_s_model}")

            with st.spinner(f"{_speaker_name} " + (f"thinking... ({_act_i + 1}/{_actions_per_turn})" if _ui_lang == "en" else f"が考えています... (アクション {_act_i + 1}/{_actions_per_turn})")):
                try:
                    _reply = generate_structured_reply(
                        user_text=_user_text,
                        history=_ctx,
                        character=_speaker_char,
                        backend=_s_backend,
                        model=_s_model,
                        quirks=_quirks,
                    )
                except Exception as _session_err:
                    _reply = {"result": {"dialogue": f"[エラー: {_session_err}]"}}

            _result = _reply.get("result") or {}
            _text = _result.get("dialogue", "") or _result.get("text", "")
            if not _text:
                _attempts = _reply.get("attempts", [])
                _last_err = _attempts[-1].get("errors", ["不明"]) if _attempts else ["不明"]
                _last_raw = _attempts[0].get("raw", "")[:100] if _attempts else ""
                _text = f"（応答失敗: {_last_err[0] if _last_err else '不明'} raw={_last_raw!r}）"

            _tags = _result.get("tags") or []
            if not _tags and _text:
                from def_kari.safety.filters import detect_tags_from_text
                _tags = detect_tags_from_text(_text)
            if st.session_state.get("force_rating_override"):
                _force_tag = st.session_state.get("force_rating_tag", "nsfw")
                if _force_tag not in _tags:
                    _tags = [_force_tag]
                st.session_state.force_rating_override = False

            _new_hist.append({
                "speaker": _speaker_id,
                "text": _text,
                "tags": _tags,
                "round": _s_round,
                "turn": _s_turn,
                "action": _act_i,
            })

            # 新しいリストとしてsession_stateに設定
            st.session_state.session_history = _new_hist

            # セッションTTS生成（同期）
            if st.session_state.get("tts_enabled") and _text and not _text.startswith("（応答失敗"):
                _tts_text = apply_name_reading(_text, _speaker_char)
                _tts_backend = st.session_state.get("tts_backend", "voicevox")
                _tts_speaker = get_tts_speaker_id(_speaker_char, _tts_backend)
                try:
                    from def_kari.workers._tts_synth import synthesize as _tts_synth
                    _tts_bytes = _tts_synth(_tts_text, _tts_speaker, _tts_backend)
                    _tts_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
                    os.makedirs(_tts_dir, exist_ok=True)
                    import time as _tt
                    _tts_path = os.path.join(_tts_dir, f"session_{_s_round}_{_s_turn}_{_act_i}_{int(_tt.time()*1000)}.wav")
                    with open(_tts_path, "wb") as _tf:
                        _tf.write(_tts_bytes)
                    _new_hist[-1]["audio_path"] = _tts_path
                    _wav_dur = _get_wav_duration(_tts_path) + 0.5
                    st.session_state._session_tts_wait = _wav_dur
                    print(f"[SESSION TTS] synced: {_speaker_name}, path={_tts_path}, duration={_wav_dur:.1f}s")
                except Exception as _tts_err:
                    print(f"[SESSION TTS] error: {_tts_err}")

            # 繰り返し発言ペナルティ判定
            _repeat_threshold = st.session_state.get("session_repeat_penalty_count", 3)
            if _repeat_threshold > 0:
                _speaker_texts = [h["text"] for h in _new_hist if h.get("speaker") == _speaker_id]
                if len(_speaker_texts) >= _repeat_threshold:
                    _recent = _speaker_texts[-_repeat_threshold:]
                    if len(set(_recent)) == 1:
                        _pen_counters = st.session_state.get("session_counters", {})
                        _pen_counters[_speaker_id] = _pen_counters.get(_speaker_id, 0) - 1
                        st.session_state.session_counters = _pen_counters
                        _pen_hist = list(st.session_state.get("session_history", []))
                        _pen_hist.append({"speaker": "_keeper", "text": f"⚠ {_speaker_name}が同一発言を{_repeat_threshold}回繰り返した [発言力-1]", "round": _s_round, "turn": _s_turn, "action": -1})
                        st.session_state.session_history = _pen_hist
                        print(f"[SESSION] repeat penalty: {_speaker_name} counter-1")

            # アクション進行 → ターン進行判定
            next_act = _act_i + 1
            if next_act >= _actions_per_turn:
                st.session_state.session_current_action = 0
                if st.session_state.get("_session_designated_next"):
                    st.session_state.pop("_session_designated_next", None)
                else:
                    next_turn = _s_turn + 1
                    if next_turn >= len(_s_initiative):
                        st.session_state.session_round = _s_round + 1
                        st.session_state.session_turn = 0
                    else:
                        st.session_state.session_turn = next_turn
                st.session_state.session_redo_used = False
            else:
                st.session_state.session_current_action = next_act

        # --- 投票処理中の判定 ---
        _vote = st.session_state.get("_session_vote")
        if _vote:
            _vote_type = _vote["type"]
            _vote_label = {"topic_change": ("Change Topic" if _ui_lang == "en" else "お題変更"), "expel": ("Expel" if _ui_lang == "en" else "参加者退場"), "end_session": ("End Session" if _ui_lang == "en" else "セッション終了"), "keeper_change": ("Keeper Change" if _ui_lang == "en" else "キーパー交代")}.get(_vote_type, _vote_type)
            _vote_detail = _vote.get("detail", "")
            st.warning(f"🗳 **投票中: {_vote_label}** — {_vote_detail}")

            _vote_results = _vote.get("results", {})
            _vote_pending_humans = []

            for _vid in initiative:
                _vchar = get_character(_vid, _profiles)
                _vname = _vchar.get("name", _vid)
                _vtype = _vchar.get("player_type", "ai")
                if _vid in _vote_results:
                    _vr = ("Yes" if _ui_lang == "en" else "賛成") if _vote_results[_vid] else ("No" if _ui_lang == "en" else "反対")
                    st.text(f"  {_vname}: {_vr}")
                elif _vtype == "ai":
                    st.text(f"  {_vname}: " + ("voting..." if _ui_lang == "en" else "投票中..."))
                else:
                    _vote_pending_humans.append(_vid)

            # AI参加者の自動投票（未投票のAIを処理）
            _ai_needs_vote = [cid for cid in initiative if cid not in _vote_results and get_character(cid, _profiles).get("player_type") == "ai"]
            if _ai_needs_vote:
                for _ai_vid in _ai_needs_vote:
                    _ai_vchar = get_character(_ai_vid, _profiles)
                    _ai_vname = _ai_vchar.get("name", _ai_vid)
                    _vote_prompt = (
                        f"あなたは{_ai_vname}です。以下の投票に賛成か反対かを答えてください。\n"
                        f"投票内容: {_vote_label} — {_vote_detail}\n"
                        f"「賛成」または「反対」の一言だけで答えてください。"
                    )
                    try:
                        _ai_backend = st.session_state.get("session_char_backends", {}).get(_ai_vid, st.session_state.get("llm_backend", DEFAULT_LLM_BACKEND))
                        if _ai_backend == "textgen_webui":
                            _ai_model = get_loaded_model_name() or ""
                        else:
                            _ai_model = _get_ext_model(_ai_backend)
                        _ai_reply = LLM_BACKENDS[_ai_backend]["chat"](
                            [{"role": "system", "content": _ai_vchar.get("persona_description", "")},
                             {"role": "user", "content": _vote_prompt}],
                            _ai_model, json_mode=False, options={"num_predict": 32},
                        )
                        _vote_results[_ai_vid] = ("賛成" in _ai_reply or "yes" in _ai_reply.lower())
                    except Exception:
                        _vote_results[_ai_vid] = True
                    print(f"[VOTE] {_ai_vname}: {'賛成' if _vote_results[_ai_vid] else '反対'}")
                _vote["results"] = _vote_results
                st.session_state._session_vote = _vote
                st.rerun()

            # 人間参加者の投票ボタン
            for _hp_vid in _vote_pending_humans:
                _hp_vname = _name_map.get(_hp_vid, _hp_vid)
                col_yes, col_no = st.columns(2)
                with col_yes:
                    if st.button(f"👍 {_hp_vname}: " + ("Yes" if _ui_lang == "en" else "賛成"), key=f"vote_yes_{_hp_vid}"):
                        _vote["results"][_hp_vid] = True
                        st.session_state._session_vote = _vote
                        st.rerun()
                with col_no:
                    if st.button(f"👎 {_hp_vname}: " + ("No" if _ui_lang == "en" else "反対"), key=f"vote_no_{_hp_vid}"):
                        _vote["results"][_hp_vid] = False
                        st.session_state._session_vote = _vote
                        st.rerun()

            # 全員投票完了の判定
            if len(_vote_results) == len(initiative):
                _yes_count = sum(1 for v in _vote_results.values() if v)
                _no_count = len(_vote_results) - _yes_count
                _passed = _yes_count > _no_count
                _result_text = f"🗳 投票結果: {_vote_label} — 賛成{_yes_count}/反対{_no_count} → {'✅ 可決' if _passed else '❌ 否決'}"
                _s_round_v = st.session_state.get("session_round", 1)
                _s_turn_v = st.session_state.get("session_turn", 0)
                _vhist = list(st.session_state.get("session_history", []))
                _vhist.append({"speaker": "_keeper", "text": _result_text, "round": _s_round_v, "turn": _s_turn_v, "action": -1})
                st.session_state.session_history = _vhist

                if _passed:
                    if _vote_type == "topic_change":
                        st.session_state.session_topic = _vote_detail
                        st.toast(f"お題が変更されました: {_vote_detail}")
                    elif _vote_type == "expel":
                        _expel_id = _vote.get("target_id")
                        if _expel_id:
                            _new_init = [cid for cid in st.session_state.get("session_initiative", []) if cid != _expel_id]
                            st.session_state.session_initiative = _new_init
                            _expel_name = _name_map.get(_expel_id, _expel_id)
                            st.toast(f"{_expel_name} " + ("expelled" if _ui_lang == "en" else "がセッションから退場しました"))
                    elif _vote_type == "end_session":
                        _end_session()
                        st.toast(_t("session_vote_ended"))

                st.session_state.pop("_session_vote", None)
                st.rerun()
            st.stop()

        # --- 割り込み処理中の判定 ---
        _interrupt = st.session_state.get("_session_interrupt")
        if _interrupt:
            _int_speaker_id = _interrupt["speaker_id"]
            _int_char = get_character(_int_speaker_id, _profiles)
            _int_name = _int_char.get("name", _int_speaker_id)
            st.warning(f"⚡ **{_int_name}** が割り込み中")

            _int_pending = st.session_state.get("session_human_pending", [])
            if _int_pending:
                st.caption(f"📝 {len(_int_pending)} " + ("pending" if _ui_lang == "en" else "積み上げ中"))
                for _ii, _itxt in enumerate(_int_pending):
                    st.text(f"  {_ii + 1}. {_itxt}")

            with st.form("interrupt_form", clear_on_submit=True, border=False):
                _icol_input, _icol_submit = st.columns([4, 1])
                with _icol_input:
                    _int_text = st.text_input(f"⚡ {_int_name}", placeholder="Enter interrupt dialogue..." if _ui_lang == "en" else "割り込み台詞を入力...", label_visibility="collapsed")
                with _icol_submit:
                    _int_submitted = st.form_submit_button("📝 Send" if _ui_lang == "en" else "📝 送信", use_container_width=True)
            if _int_submitted and _int_text:
                _new_int = list(st.session_state.get("session_human_pending", [])) + [_int_text]
                st.session_state.session_human_pending = _new_int
                st.rerun()

            _int_pending = st.session_state.get("session_human_pending", [])
            _has_int_pending = bool(_int_pending)

            if st.button(_t("session_interrupt_done"), key="interrupt_end", disabled=not _has_int_pending):
                _s_round_i = st.session_state.get("session_round", 1)
                _s_turn_i = st.session_state.get("session_turn", 0)
                _new_hist = list(st.session_state.get("session_history", []))
                for _ii, _itxt in enumerate(_int_pending):
                    _new_hist.append({
                        "speaker": _int_speaker_id,
                        "text": _itxt,
                        "round": _s_round_i,
                        "turn": _s_turn_i,
                        "action": _ii,
                    })
                st.session_state.session_history = _new_hist
                st.session_state.session_human_pending = []
                st.session_state.pop("_session_interrupt", None)
                st.rerun()
            st.stop()

        # --- 現在のターンの発言者情報（次発言者指定があれば上書き） ---
        _designated = st.session_state.get("_session_designated_next")
        if _designated:
            _cur_speaker_id = _designated
        else:
            _cur_speaker_id = initiative[turn_idx % len(initiative)]
        _cur_speaker_char = get_character(_cur_speaker_id, _profiles)
        _cur_player_type = _cur_speaker_char.get("player_type", "ai")
        _cur_speaker_name = _cur_speaker_char.get("name", _cur_speaker_id)
        _is_human_turn = (_cur_player_type == "human")

        # --- 発言力がマイナスの場合、強制スキップ ---
        _counters = st.session_state.get("session_counters", {})
        if _counters.get(_cur_speaker_id, 0) < 0:
            st.warning(f"⚠ **{_cur_speaker_name}** は発言力 [{_counters[_cur_speaker_id]}] のため強制スキップ")
            _counters[_cur_speaker_id] = _counters.get(_cur_speaker_id, 0) + 1
            st.session_state.session_counters = _counters
            next_turn_fs = turn_idx + 1
            if next_turn_fs >= len(initiative):
                st.session_state.session_round = round_num + 1
                st.session_state.session_turn = 0
            else:
                st.session_state.session_turn = next_turn_fs
            st.session_state.session_current_action = 0
            import time; time.sleep(0.5)
            st.rerun()

        # --- キーパー介入フォーム（人間ターン以外で表示） ---
        if not _is_human_turn:
            _pending_actions = st.session_state.get("session_pending_actions", [])
            if _pending_actions:
                st.caption(f"📝 {len(_pending_actions)} " + ("pending" if _ui_lang == "en" else "積み上げ中"))
                for _ai, _act in enumerate(_pending_actions):
                    st.text(f"  {_ai + 1}. {_act}")

            with st.form("keeper_action_form", clear_on_submit=True, border=False):
                    _col_input, _col_submit = st.columns([4, 1])
                    with _col_input:
                        _action_text = st.text_input("🎩 Keeper Action" if _ui_lang == "en" else "🎩 キーパーアクション", placeholder=("e.g. Tell personal experience" if _ui_lang == "en" else "例: 思想ではなく個人的な体験を語れ"), label_visibility="collapsed")
                    with _col_submit:
                        _form_submitted = st.form_submit_button("📝 Send" if _ui_lang == "en" else "📝 送信", use_container_width=True)
            if _form_submitted and _action_text:
                _new_pending = list(st.session_state.get("session_pending_actions", [])) + [_action_text]
                st.session_state.session_pending_actions = _new_pending
                if _keeper_agnostic:
                    st.session_state._force_pause = True
                st.rerun()

            _pending_actions = st.session_state.get("session_pending_actions", [])
            _has_pending = bool(_pending_actions)

        # --- 人間プレイヤーターン入力 ---
        if _is_human_turn:
            # 自動進行中なら一時停止して手動モードへ
            if _keeper_agnostic:
                st.session_state._force_pause = True
                st.session_state._was_auto_before_human = True
            # アクション上限到達で自動発言完了
            if st.session_state.pop("_human_auto_end", False):
                _human_pending_auto = st.session_state.get("session_human_pending", [])
                if _human_pending_auto:
                    _s_round_h = st.session_state.get("session_round", 1)
                    _s_turn_h = st.session_state.get("session_turn", 0)
                    _new_hist = list(st.session_state.get("session_history", []))
                    for _hi, _htxt in enumerate(_human_pending_auto):
                        _new_hist.append({
                            "speaker": _cur_speaker_id,
                            "text": _htxt,
                            "round": _s_round_h,
                            "turn": _s_turn_h,
                            "action": _hi,
                        })
                    st.session_state.session_history = _new_hist
                    st.session_state.session_human_pending = []
                    if st.session_state.get("tts_enabled") and st.session_state.get("tts_human_enabled"):
                        _tts_backend_ae = st.session_state.get("tts_backend", "voicevox")
                        _tts_speaker_ae = get_tts_speaker_id(_cur_speaker_char, _tts_backend_ae)
                        try:
                            from def_kari.workers._tts_synth import synthesize as _tts_synth
                            import time as _tt
                            _tts_dir_ae = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
                            os.makedirs(_tts_dir_ae, exist_ok=True)
                            for _hi, _htxt in enumerate(_human_pending_auto):
                                _tts_text_ae = apply_name_reading(_htxt, _cur_speaker_char)
                                _tts_bytes_ae = _tts_synth(_tts_text_ae, _tts_speaker_ae, _tts_backend_ae)
                                _tts_path_ae = os.path.join(_tts_dir_ae, f"session_{_s_round_h}_{_s_turn_h}_{_hi}_{int(_tt.time()*1000)}.wav")
                                with open(_tts_path_ae, "wb") as _tf:
                                    _tf.write(_tts_bytes_ae)
                                _new_hist[-(len(_human_pending_auto) - _hi)]["audio_path"] = _tts_path_ae
                                _wav_dur_ae = _get_wav_duration(_tts_path_ae) + 0.5
                                if _hi < len(_human_pending_auto) - 1:
                                    _tt.sleep(_wav_dur_ae)
                                else:
                                    st.session_state._session_tts_wait = _wav_dur_ae
                            st.session_state.session_history = _new_hist
                        except Exception as _tts_err:
                            print(f"[SESSION TTS] auto-end error: {_tts_err}")
                    next_turn_ae = _s_turn_h + 1
                    if next_turn_ae >= len(initiative):
                        st.session_state.session_round = _s_round_h + 1
                        st.session_state.session_turn = 0
                    else:
                        st.session_state.session_turn = next_turn_ae
                    st.session_state.session_current_action = 0
                    if st.session_state.get("_was_auto_before_human"):
                        st.session_state._keeper_agnostic = True
                        st.session_state._ka_cb = True
                        st.session_state.pop("_was_auto_before_human", None)
                    st.rerun()

            st.info(f"👤 **{_cur_speaker_name}** " + ("'s turn. Enter dialogue." if _ui_lang == "en" else "のターンです。台詞を入力してください。"))

            _human_pending = st.session_state.get("session_human_pending", [])
            if _human_pending:
                st.caption(f"📝 {len(_human_pending)} " + ("pending" if _ui_lang == "en" else "積み上げ中"))
                for _hi, _htxt in enumerate(_human_pending):
                    st.text(f"  {_hi + 1}. {_htxt}")

            with st.form("human_turn_form", clear_on_submit=True, border=False):
                _hcol_input, _hcol_submit = st.columns([4, 1])
                with _hcol_input:
                    _human_text = st.text_input(f"👤 {_cur_speaker_name}", placeholder="Enter dialogue..." if _ui_lang == "en" else "台詞を入力...", label_visibility="collapsed")
                with _hcol_submit:
                    _human_submitted = st.form_submit_button("📝 Send" if _ui_lang == "en" else "📝 送信", use_container_width=True)
            if _human_submitted and _human_text:
                _new_human = list(st.session_state.get("session_human_pending", [])) + [_human_text]
                st.session_state.session_human_pending = _new_human
                if len(_new_human) >= _actions_per_turn:
                    st.session_state._human_auto_end = True
                st.rerun()

            _human_pending = st.session_state.get("session_human_pending", [])
            _has_human_pending = bool(_human_pending)

            _human_counter = _counters.get(_cur_speaker_id, 0)
            col_hend, col_hextend, col_hskip, col_hredo, col_hstop = st.columns(5)

            with col_hend:
                if st.button(_t("session_turn_end"), key="human_turn_end", disabled=not _has_human_pending):
                    _s_round_h = st.session_state.get("session_round", 1)
                    _s_turn_h = st.session_state.get("session_turn", 0)
                    _new_hist = list(st.session_state.get("session_history", []))
                    for _hi, _htxt in enumerate(_human_pending):
                        _new_hist.append({
                            "speaker": _cur_speaker_id,
                            "text": _htxt,
                            "round": _s_round_h,
                            "turn": _s_turn_h,
                            "action": _hi,
                        })
                    st.session_state.session_history = _new_hist
                    st.session_state.session_human_pending = []
                    # セッションTTS生成（人間プレイヤー、同期、1アクションずつ再生待機）
                    if st.session_state.get("tts_enabled") and st.session_state.get("tts_human_enabled"):
                        _tts_backend_h = st.session_state.get("tts_backend", "voicevox")
                        _tts_speaker_h = get_tts_speaker_id(_cur_speaker_char, _tts_backend_h)
                        try:
                            from def_kari.workers._tts_synth import synthesize as _tts_synth
                            import time as _tt
                            _tts_dir_h = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
                            os.makedirs(_tts_dir_h, exist_ok=True)
                            for _hi, _htxt in enumerate(_human_pending):
                                _tts_text_h = apply_name_reading(_htxt, _cur_speaker_char)
                                _tts_bytes_h = _tts_synth(_tts_text_h, _tts_speaker_h, _tts_backend_h)
                                _tts_path_h = os.path.join(_tts_dir_h, f"session_{_s_round_h}_{_s_turn_h}_{_hi}_{int(_tt.time()*1000)}.wav")
                                with open(_tts_path_h, "wb") as _tf:
                                    _tf.write(_tts_bytes_h)
                                _new_hist[-(len(_human_pending) - _hi)]["audio_path"] = _tts_path_h
                                _wav_dur_h = _get_wav_duration(_tts_path_h) + 0.5
                                if _hi < len(_human_pending) - 1:
                                    _tt.sleep(_wav_dur_h)
                                else:
                                    st.session_state._session_tts_wait = _wav_dur_h
                            st.session_state.session_history = _new_hist
                        except Exception as _tts_err:
                            print(f"[SESSION TTS] human error: {_tts_err}")
                    # ターン進行
                    next_turn_h = _s_turn_h + 1
                    if next_turn_h >= len(initiative):
                        st.session_state.session_round = _s_round_h + 1
                        st.session_state.session_turn = 0
                    else:
                        st.session_state.session_turn = next_turn_h
                    st.session_state.session_current_action = 0
                    # 自動進行復帰
                    if st.session_state.get("_was_auto_before_human"):
                        st.session_state._keeper_agnostic = True
                        st.session_state._ka_cb = True
                        st.session_state.pop("_was_auto_before_human", None)
                    st.rerun()

            with col_hextend:
                if st.button(_t("session_turn_extend"), key="human_turn_extend", disabled=not _has_human_pending or _human_counter <= 0):
                    _s_round_h = st.session_state.get("session_round", 1)
                    _s_turn_h = st.session_state.get("session_turn", 0)
                    _new_hist = list(st.session_state.get("session_history", []))
                    for _hi, _htxt in enumerate(_human_pending):
                        _new_hist.append({
                            "speaker": _cur_speaker_id,
                            "text": _htxt,
                            "round": _s_round_h,
                            "turn": _s_turn_h,
                            "action": _hi,
                        })
                    st.session_state.session_history = _new_hist
                    st.session_state.session_human_pending = []
                    # 発言力-1（Turn延長）
                    _ext_counters = st.session_state.get("session_counters", {})
                    _ext_counters[_cur_speaker_id] = _ext_counters.get(_cur_speaker_id, 0) - 1
                    st.session_state.session_counters = _ext_counters
                    # ターンを進めない（同じ人が続行）
                    st.session_state.session_current_action = 0
                    st.rerun()

            with col_hskip:
                if st.button(_t("session_turn_skip"), key="human_turn_skip", disabled=_has_human_pending):
                    _s_round_h = st.session_state.get("session_round", 1)
                    _s_turn_h = st.session_state.get("session_turn", 0)
                    # 発言力+1（自主スキップ）
                    _sk_counters = st.session_state.get("session_counters", {})
                    _sk_counters[_cur_speaker_id] = _sk_counters.get(_cur_speaker_id, 0) + 1
                    st.session_state.session_counters = _sk_counters
                    # 履歴に記録
                    _sk_hist = list(st.session_state.get("session_history", []))
                    _sk_hist.append({"speaker": "_keeper", "text": f"⏭ {_cur_speaker_name}がスキップ [発言力+1]", "round": _s_round_h, "turn": _s_turn_h, "action": -1})
                    st.session_state.session_history = _sk_hist
                    # ターン進行（発言なし）
                    next_turn_h = _s_turn_h + 1
                    if next_turn_h >= len(initiative):
                        st.session_state.session_round = _s_round_h + 1
                        st.session_state.session_turn = 0
                    else:
                        st.session_state.session_turn = next_turn_h
                    st.session_state.session_current_action = 0
                    if st.session_state.get("_was_auto_before_human"):
                        st.session_state._keeper_agnostic = True
                        st.session_state._ka_cb = True
                        st.session_state.pop("_was_auto_before_human", None)
                    st.rerun()

            with col_hredo:
                if st.button("🔄 Redo" if _ui_lang == "en" else "🔄 やり直し", key="human_turn_redo", disabled=not _has_human_pending):
                    st.session_state.session_human_pending = []
                    st.rerun()

            with col_hstop:
                if st.button(("⏹ End" if _ui_lang == "en" else "⏹ セッション終了"), key="human_turn_stop"):
                    _end_session()
                    st.session_state.session_human_pending = []
                    st.info(_t("session_ended"))
                    st.rerun()

            # --- 挿図ボタン（人間プレイヤー用、発言力-1） ---
            if st.button("🎨 Illust [-1]" if _ui_lang == "en" else "🎨 挿図 [発言力-1]", key="human_illustration", disabled=_human_counter <= 0):
                _ill_counters = st.session_state.get("session_counters", {})
                _ill_counters[_cur_speaker_id] = _ill_counters.get(_cur_speaker_id, 0) - 1
                st.session_state.session_counters = _ill_counters
                with st.spinner(_t("image_generating")):
                    _generate_session_illustration()
                st.rerun()

            # --- 次発言者指名（expander方式） ---
            _other_participants = [cid for cid in initiative if cid != _cur_speaker_id]
            if _other_participants:
                with st.expander(f"👉 " + (f"Designate [-1, current: {_human_counter}]" if _ui_lang == "en" else f"次発言者を指名する [発言力-1、現在: {_human_counter}]"), expanded=False):
                    _desig_target = st.selectbox(
                        "Designate" if _ui_lang == "en" else "指名先",
                        _other_participants,
                        format_func=lambda cid: _name_map.get(cid, cid),
                        key="human_designate_target",
                    )
                    if st.button("👉 Designate & End Turn" if _ui_lang == "en" else "👉 指名して発言完了", key="human_designate_confirm", disabled=not _has_human_pending or _human_counter <= 0):
                        _s_round_h = st.session_state.get("session_round", 1)
                        _s_turn_h = st.session_state.get("session_turn", 0)
                        _new_hist = list(st.session_state.get("session_history", []))
                        for _hi, _htxt in enumerate(_human_pending):
                            _new_hist.append({
                                "speaker": _cur_speaker_id,
                                "text": _htxt,
                                "round": _s_round_h,
                                "turn": _s_turn_h,
                                "action": _hi,
                            })
                        _desig_name = _name_map.get(_desig_target, _desig_target)
                        _new_hist.append({"speaker": "_keeper", "text": f"👉 {_cur_speaker_name}が{_desig_name}を次発言者に指名 [発言力-1]", "round": _s_round_h, "turn": _s_turn_h, "action": -1})
                        st.session_state.session_history = _new_hist
                        st.session_state.session_human_pending = []
                        _des_counters = st.session_state.get("session_counters", {})
                        _des_counters[_cur_speaker_id] = _des_counters.get(_cur_speaker_id, 0) - 1
                        st.session_state.session_counters = _des_counters
                        st.session_state._session_designated_next = _desig_target
                        st.session_state.session_current_action = 0
                        if st.session_state.get("_was_auto_before_human"):
                            st.session_state._keeper_agnostic = True
                            st.session_state._ka_cb = True
                            st.session_state.pop("_was_auto_before_human", None)
                        st.rerun()

            # --- 人間プレイヤーの投票発議（発言力3以上） ---
            with st.expander(f"🗳 " + (f"Call Vote [-3, current: {_human_counter}]" if _ui_lang == "en" else f"投票を発議する [発言力-3、現在: {_human_counter}]"), expanded=False):
                _pv_types = {
                    "topic_change": ("Change Topic" if _ui_lang == "en" else "お題変更"),
                    "expel": ("Expel" if _ui_lang == "en" else "参加者退場"),
                    "end_session": ("End Session" if _ui_lang == "en" else "セッション終了"),
                }
                _pv_type = st.selectbox("Vote Type" if _ui_lang == "en" else "投票種別", list(_pv_types.keys()), format_func=lambda k: _pv_types[k], key="player_vote_type")
                if _pv_type == "topic_change":
                    _pv_detail = st.text_input("New Topic" if _ui_lang == "en" else "新しいお題", key="player_vote_detail")
                elif _pv_type == "expel":
                    _pv_expel_opts = [cid for cid in initiative if cid != _cur_speaker_id]
                    _pv_detail = st.selectbox("Target" if _ui_lang == "en" else "退場対象", _pv_expel_opts, format_func=lambda cid: _name_map.get(cid, cid), key="player_vote_expel")
                else:
                    _pv_detail = "End session?" if _ui_lang == "en" else "セッションを終了しますか？"

                if st.button("🗳 Start Vote" if _ui_lang == "en" else "🗳 投票開始", key="player_start_vote", disabled=_human_counter < 3):
                        _pv_counters = st.session_state.get("session_counters", {})
                        _pv_counters[_cur_speaker_id] = _pv_counters.get(_cur_speaker_id, 0) - 3
                        st.session_state.session_counters = _pv_counters
                        _pv_data = {
                            "type": _pv_type,
                            "detail": _pv_detail if _pv_type != "expel" else _name_map.get(_pv_detail, _pv_detail),
                            "results": {_cur_speaker_id: True},
                            "initiator": _cur_speaker_id,
                        }
                        if _pv_type == "expel":
                            _pv_data["target_id"] = _pv_detail
                        st.session_state._session_vote = _pv_data
                        _pv_hist = list(st.session_state.get("session_history", []))
                        _pv_hist.append({"speaker": "_keeper", "text": f"🗳 {_cur_speaker_name}が投票を発議 [発言力-3]: {_pv_types[_pv_type]}", "round": st.session_state.get("session_round", 1), "turn": st.session_state.get("session_turn", 0), "action": -1})
                        st.session_state.session_history = _pv_hist
                        st.rerun()

        # --- 自動進行（AIターンのみ。人間ターンは自動停止） ---
        elif _keeper_agnostic and not _is_human_turn:
            if st.button(_t("session_pause"), key="session_pause"):
                st.session_state._force_pause = True
                st.rerun()

            _prev_tts_wait = st.session_state.pop("_session_tts_wait", 0)
            import time as _tw
            _action_start = _tw.time()

            _saved_keeper_auto = st.session_state.pop("session_keeper_instruction", "")
            _execute_session_action(_saved_keeper_auto)

            # LLM+TTS生成にかかった時間を差し引いて残り時間だけ待機
            _elapsed = _tw.time() - _action_start
            _remaining = _prev_tts_wait - _elapsed
            if _remaining > 0:
                _tw.sleep(_remaining)

            st.rerun()

        # --- 通常モード: 手動進行（AIターン） ---
        else:

            # 直前のAIアクションがあればリテイク可能
            _session_hist = st.session_state.get("session_history", [])
            _last_ai_action = next(
                (h for h in reversed(_session_hist) if h.get("speaker") not in ("_keeper", None)),
                None,
            )
            _can_retake = _last_ai_action is not None and not _has_pending

            col_end, col_redo, col_retake, col_fskip, col_next, col_stop = st.columns(6)

            with col_end:
                if st.button(_t("session_turn_end"), key="action_end", disabled=not _has_pending):
                    _keeper_text = _pending_actions[0] if len(_pending_actions) == 1 else "\n".join(f"・{a}" for a in _pending_actions)
                    _s_round_k = st.session_state.get("session_round", 1)
                    _s_turn_k = st.session_state.get("session_turn", 0)
                    _new = list(st.session_state.get("session_history", []))
                    _new.append({"speaker": "_keeper", "text": _keeper_text, "round": _s_round_k, "turn": _s_turn_k, "action": -1})
                    st.session_state.session_history = _new
                    st.session_state.session_keeper_instruction = _keeper_text
                    st.session_state.session_pending_actions = []
                    st.rerun()

            with col_redo:
                _redo_used = st.session_state.get("session_redo_used", False)
                if st.button("🔄 Redo" if _ui_lang == "en" else "🔄 やり直し", key="action_redo", disabled=_redo_used or not _pending_actions):
                    st.session_state.session_pending_actions = []
                    st.session_state.session_redo_used = True
                    st.info("Actions discarded. (Redo unavailable this turn)" if _ui_lang == "en" else "アクションを破棄しました。（このターンではやり直しは使えません）")
                    st.rerun()

            with col_retake:
                if st.button(_t("session_retake"), key="session_retake", disabled=not _can_retake):
                    _rt_hist = list(st.session_state.get("session_history", []))
                    if _rt_hist:
                        _removed = _rt_hist.pop()
                        st.session_state.session_history = _rt_hist
                        st.session_state.session_round = _removed.get("round", st.session_state.get("session_round", 1))
                        st.session_state.session_turn = _removed.get("turn", st.session_state.get("session_turn", 0))
                        st.session_state.session_current_action = _removed.get("action", 0)
                        if _removed.get("speaker") != "_keeper":
                            st.session_state._session_designated_next = _removed.get("speaker")
                        _saved_keeper_rt = st.session_state.pop("session_keeper_instruction", "")
                        _execute_session_action(_saved_keeper_rt)
                        st.session_state.pop("_session_designated_next", None)
                    st.rerun()

            with col_next:
                if st.button(_t("session_next"), key="session_next_turn", disabled=_has_pending):
                    _prev_tts_wait_m = st.session_state.pop("_session_tts_wait", 0)
                    import time as _tw
                    _action_start_m = _tw.time()
                    _saved_keeper = st.session_state.pop("session_keeper_instruction", "")
                    _execute_session_action(_saved_keeper)
                    _elapsed_m = _tw.time() - _action_start_m
                    _remaining_m = _prev_tts_wait_m - _elapsed_m
                    if _remaining_m > 0:
                        _tw.sleep(_remaining_m)
                    st.session_state.session_pending_actions = []
                    st.session_state.session_redo_used = False
                    st.rerun()

            with col_fskip:
                if st.button(_t("session_force_skip"), key="keeper_force_skip"):
                    _fsk_counters = st.session_state.get("session_counters", {})
                    _fsk_counters[_cur_speaker_id] = _fsk_counters.get(_cur_speaker_id, 0) + 1
                    st.session_state.session_counters = _fsk_counters
                    _fsk_round = st.session_state.get("session_round", 1)
                    _fsk_turn = st.session_state.get("session_turn", 0)
                    _fsk_hist = list(st.session_state.get("session_history", []))
                    _fsk_hist.append({"speaker": "_keeper", "text": f"🎩 {_cur_speaker_name}を強制スキップ [発言力+1]", "round": _fsk_round, "turn": _fsk_turn, "action": -1})
                    st.session_state.session_history = _fsk_hist
                    next_turn_fsk = _fsk_turn + 1
                    if next_turn_fsk >= len(initiative):
                        st.session_state.session_round = _fsk_round + 1
                        st.session_state.session_turn = 0
                    else:
                        st.session_state.session_turn = next_turn_fsk
                    st.session_state.session_current_action = 0
                    st.session_state.session_pending_actions = []
                    st.rerun()

            with col_stop:
                if st.button(("⏹ End" if _ui_lang == "en" else "⏹ セッション終了"), key="session_stop"):
                    _end_session()
                    st.session_state.session_pending_actions = []
                    st.info(_t("session_ended"))
                    st.rerun()

            # --- 人間プレイヤーの割り込みボタン（AIターン中に表示） ---
            _human_participants = [cid for cid in initiative if get_character(cid, _profiles).get("player_type") == "human"]
            for _hp_id in _human_participants:
                _hp_name = _name_map.get(_hp_id, _hp_id)
                _hp_counter = _counters.get(_hp_id, 0)
                if st.button(f"⚡ {_hp_name} " + ("interrupt [-2]" if _ui_lang == "en" else "割り込み [発言力-2]"), key=f"interrupt_{_hp_id}", disabled=_hp_counter < 2):
                    _int_counters = st.session_state.get("session_counters", {})
                    _int_counters[_hp_id] = _int_counters.get(_hp_id, 0) - 2
                    st.session_state.session_counters = _int_counters
                    st.session_state._session_interrupt = {"speaker_id": _hp_id}
                    st.session_state.session_human_pending = []
                    if _keeper_agnostic:
                        st.session_state._force_pause = True
                        st.session_state._was_auto_before_human = True
                    st.rerun()

        # --- 挿図ボタン（キーパー用、AIターン中） ---
        if not _is_human_turn:
            if st.button(_t("session_keeper_illustration"), key="keeper_illustration"):
                with st.spinner(_t("image_generating")):
                    _generate_session_illustration()
                st.rerun()

        # --- 投票発議（キーパー機能、人間ターン中は非表示） ---
        if not _is_human_turn:
            with st.expander("🗳 Call Vote" if _ui_lang == "en" else "🗳 投票を発議する", expanded=False):
                _vote_types = {
                    "topic_change": "お題変更",
                    "expel": "参加者退場",
                    "end_session": "セッション終了",
                }
                _vote_type_sel = st.selectbox("投票種別", list(_vote_types.keys()), format_func=lambda k: _vote_types[k], key="vote_type_sel")
                if _vote_type_sel == "topic_change":
                    _vote_detail_input = st.text_input("新しいお題", key="vote_detail_input")
                elif _vote_type_sel == "expel":
                    _expel_options = [cid for cid in initiative]
                    _vote_detail_input = st.selectbox("退場対象", _expel_options, format_func=lambda cid: _name_map.get(cid, cid), key="vote_expel_target")
                else:
                    _vote_detail_input = "セッションを終了しますか？"

                if st.button("🗳 Start Vote" if _ui_lang == "en" else "🗳 投票開始", key="start_vote"):
                    _vote_data = {
                        "type": _vote_type_sel,
                        "detail": _vote_detail_input if _vote_type_sel != "expel" else _name_map.get(_vote_detail_input, _vote_detail_input),
                        "results": {},
                    }
                    if _vote_type_sel == "expel":
                        _vote_data["target_id"] = _vote_detail_input
                    st.session_state._session_vote = _vote_data
                    if _keeper_agnostic:
                        st.session_state._force_pause = True
                    st.rerun()

    # --- フッター ---
    st.divider()
    def _on_keeper_agnostic_change():
        st.session_state._keeper_agnostic = st.session_state._ka_cb
    st.checkbox(
        "Auto-advance" if _ui_lang == "en" else "自動進行",
        value=st.session_state.get("_keeper_agnostic", False),
        key="_ka_cb",
        on_change=_on_keeper_agnostic_change,
    )

with tab_thinking:
    st.subheader(_t("debug_title"))
    if st.session_state.history:
        latest = st.session_state.history[-1]

        _raw_response = ""
        if latest.get("llm_attempts"):
            _raw_response = latest["llm_attempts"][0].get("raw", "")

        st.subheader(_t("debug_raw"))
        st.code(_raw_response or "(なし)", language=None)

        st.subheader("Processed" if _ui_lang == "en" else "加工後")
        st.write("**画面表示テキスト:**", latest.get("text", ""))
        st.write("**image_prompt_en:**", latest.get("image_prompt_en", ""))
        st.write("**tags:**", latest.get("tags", []))
        st.write("**emotion:**", latest.get("emotion", "neutral"))
        st.write("**最終判定:**", ("✅ OK" if _ui_lang == "en" else "✅ 成功") if latest.get("llm_success") else ("❌ Fail" if _ui_lang == "en" else "❌ 失敗"))

        st.divider()
        st.subheader("Fallback Chain" if _ui_lang == "en" else "フォールバックチェーン詳細")
        for a in latest.get("llm_attempts", []):
            st.write(a.get("stage", ""))
            if a.get("raw"):
                st.code(a["raw"][:500])
            for e in a.get("errors", []):
                st.write(e)

        _debug_lines = []
        _debug_lines.append("=== LLM生応答 ===")
        _debug_lines.append(_raw_response or "(なし)")
        _debug_lines.append("")
        _debug_lines.append("=== 加工後 ===")
        _debug_lines.append(f"text: {latest.get('text', '')}")
        _debug_lines.append(f"image_prompt_en: {latest.get('image_prompt_en', '')}")
        _debug_lines.append(f"tags: {latest.get('tags', [])}")
        _debug_lines.append(f"emotion: {latest.get('emotion', 'neutral')}")
        _debug_lines.append(f"最終判定: {'成功' if latest.get('llm_success') else '失敗'}")
        _debug_lines.append("")
        _debug_lines.append("=== フォールバックチェーン ===")
        for a in latest.get("llm_attempts", []):
            _debug_lines.append(a.get("stage", ""))
            if a.get("raw"):
                _debug_lines.append(a["raw"][:500])
            for e in a.get("errors", []):
                _debug_lines.append(e)
            _debug_lines.append("")
        _debug_text = "\n".join(_debug_lines)

        st.divider()
        st.subheader(_t("debug_copy"))
        st.code(_debug_text, language=None)

with tab_character:
    st.subheader(_t("char_select"))
    _char_choices = list_character_choices(_profiles)
    _char_ids = [c[0] for c in _char_choices]
    _char_labels = {c[0]: c[1] for c in _char_choices}
    _cur_idx = _char_ids.index(st.session_state.active_character) if st.session_state.active_character in _char_ids else 0
    new_char = st.selectbox(
        _t("char_select_label"),
        _char_ids,
        index=_cur_idx,
        format_func=lambda k: _char_labels.get(k, k),
    )
    if new_char != st.session_state.active_character:
        _prev_name = _char_labels.get(st.session_state.active_character, "")
        _new_name = _char_labels.get(new_char, new_char)

        # --- Reconstruct & Reenact ---
        save_session(st.session_state.history, st.session_state.active_character)
        st.session_state.active_character = new_char
        full = load_full(new_char)
        st.session_state.history = full[-MAX_VISIBLE_TURNS:] if full else []
        for m in st.session_state.history:
            m.setdefault("llm_attempts", [])
        st.session_state._history_character = new_char
        st.toast(f"🎭 Reenact: {_new_name}")

        if st.session_state.get("character_greeting", True):
            st.session_state._pending_greeting = {
                "previous_name": _prev_name,
                "new_name": _new_name,
            }
        save_settings(st.session_state)
        st.rerun()

    st.divider()
    st.subheader(_t("char_voice_settings"))

    @st.fragment(run_every=f"{st.session_state.get('status_poll_sec', DEFAULT_STATUS_POLL_SEC)}s")
    def _voice_settings():
        _char_for_voice = get_character(st.session_state.get("active_character"))
        _raw_bp_voice = get_raw_profile(st.session_state.active_character, _profiles)

        if st.session_state.tts_backend == "voicevox":
            from def_kari.backends import is_voicevox_running
            if is_voicevox_running():
                try:
                    import requests as _req
                    _vv_resp = _req.get("http://127.0.0.1:50021/speakers", timeout=5)
                    _vv_resp.raise_for_status()
                    _speakers = []
                    for _char in _vv_resp.json():
                        for _style in _char.get("styles", []):
                            _speakers.append({"id": _style["id"], "label": f"{_char['name']}({_style['name']})"})
                    if _speakers:
                        _speaker_labels = {s["id"]: s["label"] for s in _speakers}
                        _speaker_ids = [s["id"] for s in _speakers]
                        _cur_speaker = _char_for_voice.get("voicevox_speaker_id") or 2
                        _cur_idx = _speaker_ids.index(_cur_speaker) if _cur_speaker in _speaker_ids else 0
                        _vv_key = f"char_voicevox_speaker_{st.session_state.active_character}"
                        _selected_speaker = st.selectbox(
                            "VOICEVOX Speaker" if _ui_lang == "en" else "VOICEVOXスピーカー",
                            _speaker_ids,
                            index=_cur_idx,
                            format_func=lambda k: _speaker_labels.get(k, str(k)),
                            key=_vv_key,
                        )
                        _col_save_vv, _col_test_vv = st.columns(2)
                        with _col_save_vv:
                            if st.button("💾 Save Speaker" if _ui_lang == "en" else "💾 スピーカーを保存", key=f"save_vv_speaker_{st.session_state.active_character}"):
                                _dmc = _raw_bp_voice.setdefault("default_model_config", {})
                                _dmc["voicevox_speaker_id"] = _selected_speaker
                                save_profile(st.session_state.active_character, _raw_bp_voice)
                                st.success(f"Saved: {_speaker_labels.get(_selected_speaker, _selected_speaker)}")
                        with _col_test_vv:
                            if st.button("🔊 Test Voice" if _ui_lang == "en" else "🔊 テスト音声生成", key=f"test_vv_speaker_{st.session_state.active_character}"):
                                try:
                                    _test_text = "あめんぼ、あかいな、あいうえお"
                                    _tts_resp = _req.post(
                                        f"http://127.0.0.1:50021/audio_query?speaker={_selected_speaker}&text={_test_text}",
                                        timeout=10,
                                    )
                                    _tts_resp.raise_for_status()
                                    _synth_resp = _req.post(
                                        f"http://127.0.0.1:50021/synthesis?speaker={_selected_speaker}",
                                        json=_tts_resp.json(),
                                        timeout=30,
                                    )
                                    _synth_resp.raise_for_status()
                                    st.session_state._tts_test_audio = _synth_resp.content
                                except Exception as _test_err:
                                    _te = "Test failed: " if _ui_lang == "en" else "テスト再生失敗: "
                                    st.error(f"{_te}{_test_err}")
                        if st.session_state.get("_tts_test_audio"):
                            st.audio(st.session_state._tts_test_audio, format="audio/wav")
                except Exception:
                    st.caption("VOICEVOX not responding." if _ui_lang == "en" else "VOICEVOXが応答していません。")
            else:
                st.caption("VOICEVOX not running." if _ui_lang == "en" else "VOICEVOXが起動していません。")

        elif st.session_state.tts_backend == "irodori":
            from def_kari.backends import is_irodori_running, IRODORI_DIR
            if is_irodori_running():
                _voices_dir = os.path.join(IRODORI_DIR, "voices")
                _voice_files = []
                if os.path.isdir(_voices_dir):
                    _voice_files = [
                        os.path.splitext(f)[0]
                        for f in sorted(os.listdir(_voices_dir))
                        if f.lower().endswith((".wav", ".mp3", ".flac", ".ogg"))
                    ]
                _options = _voice_files
                _cur_voice = _char_for_voice.get("irodori_speaker_id") or ""
                _iro_key = f"char_irodori_voice_{st.session_state.active_character}"
                _final_voice = st.selectbox(
                    "Irodori-TTS Voice",
                    _options,
                    index=_options.index(_cur_voice) if _cur_voice in _options else 0,
                    key=_iro_key,
                    accept_new_options=True,
                    placeholder="Voice名を入力または選択",
                ) or ""
                st.caption(f"Voice: {_final_voice or 'sample'}")
                _col_save_iro, _col_test_iro = st.columns(2)
                with _col_save_iro:
                    if st.button("💾 Save Voice" if _ui_lang == "en" else "💾 Voiceを保存", key=f"save_irodori_voice_{st.session_state.active_character}"):
                        _dmc = _raw_bp_voice.setdefault("default_model_config", {})
                        _dmc["irodori_speaker_id"] = _final_voice or "sample"
                        save_profile(st.session_state.active_character, _raw_bp_voice)
                        st.success(f"Saved: {_final_voice or 'sample'}")
                with _col_test_iro:
                    if st.button("🔊 テスト音声生成", key=f"test_irodori_voice_{st.session_state.active_character}"):
                        try:
                            import requests as _iro_req
                            _test_voice = _final_voice or "sample"
                            _iro_resp = _iro_req.post(
                                "http://127.0.0.1:8088/v1/audio/speech",
                                json={"model": "default", "voice": _test_voice, "input": "あめんぼ、あかいな、あいうえお"},
                                timeout=300,
                            )
                            _iro_resp.raise_for_status()
                            st.session_state._tts_test_audio = _iro_resp.content
                        except Exception as _test_err:
                            st.error(f"テスト再生失敗: {_test_err}")
                if st.session_state.get("_tts_test_audio"):
                    st.audio(st.session_state._tts_test_audio, format="audio/wav")
            else:
                st.caption("Irodori-TTS not running." if _ui_lang == "en" else "Irodori-TTSが起動していません。")
    _voice_settings()

    st.divider()
    st.subheader(_t("char_image"))

    from def_kari.characters import _find_character_dir
    _char_img_dir = _find_character_dir(st.session_state.active_character)
    _char_img_dir.mkdir(parents=True, exist_ok=True)
    _icon_path = _char_img_dir / "icon.png"
    _standing_path = _char_img_dir / "standing.png"

    col_icon, col_standing = st.columns(2)

    with col_icon:
        st.caption(_t("char_icon_label"))
        if _icon_path.exists():
            st.image(str(_icon_path), width=128)
        else:
            st.caption(_t("char_unset"))

        _icon_upload = st.file_uploader(_t("char_icon_upload"), type=["png", "jpg", "webp"], key=f"icon_upload_{st.session_state.active_character}")
        if _icon_upload:
            from PIL import Image as _PILImage
            _img = _PILImage.open(_icon_upload).convert("RGB")
            _img = _img.resize((512, 512), _PILImage.LANCZOS)
            _img.save(str(_icon_path), "PNG")
            st.success(_t("char_icon_saved"))
            st.rerun()

        if st.button(_t("char_icon_generate"), key="gen_icon"):
            _char_data = get_character(st.session_state.active_character, _profiles)
            _icon_prompt = _char_data.get("appearance_tags", "")
            if _icon_prompt:
                _icon_prompt = f"portrait, face close-up, {_icon_prompt}, white background, simple background"
                task_q.put({
                    "kind": "image",
                    "msg_id": f"icon_{st.session_state.active_character}",
                    "image_prompt_en": _icon_prompt,
                    "emotion": "neutral",
                    "t2i_width": 512,
                    "t2i_height": 512,
                    "t2i_backend": st.session_state.get("t2i_backend"),
                    "t2i_model": st.session_state.get("t2i_model"),
                    "_save_to": str(_icon_path),
                })
                st.info(_t("image_requested_icon"))

    with col_standing:
        st.caption(_t("char_standing_label"))
        if _standing_path.exists():
            st.image(str(_standing_path), width=200)
        else:
            st.caption(_t("char_unset"))

        _standing_upload = st.file_uploader(_t("char_standing_upload"), type=["png", "jpg", "webp"], key=f"standing_upload_{st.session_state.active_character}")
        if _standing_upload:
            from PIL import Image as _PILImage
            _img = _PILImage.open(_standing_upload).convert("RGB")
            _img = _img.resize((832, 1216), _PILImage.LANCZOS)
            _img.save(str(_standing_path), "PNG")
            st.success(_t("char_standing_saved"))
            st.rerun()

        if st.button(_t("char_standing_generate"), key="gen_standing"):
            _char_data = get_character(st.session_state.active_character, _profiles)
            _standing_prompt = _char_data.get("appearance_tags", "")
            if _standing_prompt:
                _standing_prompt = f"full body, standing, {_standing_prompt}, white background, simple background"
                task_q.put({
                    "kind": "image",
                    "msg_id": f"standing_{st.session_state.active_character}",
                    "image_prompt_en": _standing_prompt,
                    "emotion": "neutral",
                    "t2i_width": 832,
                    "t2i_height": 1216,
                    "t2i_backend": st.session_state.get("t2i_backend"),
                    "t2i_model": st.session_state.get("t2i_model"),
                    "_save_to": str(_standing_path),
                })
                st.info(_t("image_requested_standing"))

    st.divider()
    st.subheader(_t("char_profile_edit"))

    import json as _json
    _raw_bp = get_raw_profile(st.session_state.active_character, _profiles)
    _bp_json_str = _json.dumps(_raw_bp, ensure_ascii=False, indent=2)

    _edited_json = st.text_area(
        "base_profile (JSON)",
        value=_bp_json_str,
        height=400,
        key=f"edit_bp_{st.session_state.active_character}",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button(_t("char_profile_save")):
            try:
                _parsed_bp = _json.loads(_edited_json)
                save_profile(st.session_state.active_character, _parsed_bp)
                st.success("保存しました。")
                st.rerun()
            except _json.JSONDecodeError as e:
                st.error(f"JSONパースエラー: {e}")
    with col2:
        if st.button("🗑 会話履歴をクリア"):
            clear_history(st.session_state.active_character)
            st.session_state.history = []
            st.success("履歴をクリアしました。")
            st.rerun()

with tab_episode:
    _EPISODES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "private", "episodes")

    def _load_episodes() -> list:
        if not os.path.isdir(_EPISODES_DIR):
            return []
        episodes = []
        for f in sorted(os.listdir(_EPISODES_DIR)):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(_EPISODES_DIR, f), encoding="utf-8") as fh:
                    ep = _json.load(fh)
                    ep.setdefault("id", os.path.splitext(f)[0])
                    ep.setdefault("title", os.path.splitext(f)[0])
                    episodes.append(ep)
            except (_json.JSONDecodeError, OSError):
                pass
        return episodes

    def _save_episode(ep: dict) -> None:
        os.makedirs(_EPISODES_DIR, exist_ok=True)
        title = ep.get("title", "untitled")
        safe_name = title.replace("/", "_").replace("\\", "_").replace(":", "_")
        path = os.path.join(_EPISODES_DIR, f"{safe_name}.json")
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(ep, f, ensure_ascii=False, indent=2)

    def _delete_episode(ep: dict) -> None:
        title = ep.get("title", "")
        safe_name = title.replace("/", "_").replace("\\", "_").replace(":", "_")
        path = os.path.join(_EPISODES_DIR, f"{safe_name}.json")
        if os.path.exists(path):
            os.remove(path)


    @st.dialog("Plot Settings" if _ui_lang == "en" else "プロット設定")
    def _render_plot_dialog(ep_id, ep_title):
        episodes = _load_episodes()
        current = next((e for e in episodes if e["id"] == ep_id), {"plot": ""}) if ep_id else {"plot": ""}

        _dk = ep_id or "new"
        _default_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "public", "episode_prompts")

        col_open, col_path = st.columns([1, 4])
        with col_open:
            if st.button("📂 Open" if _ui_lang == "en" else "📂 開く", key=f"ep_file_open_{_dk}"):
                import tkinter as tk
                from tkinter import filedialog
                _root = tk.Tk()
                _root.withdraw()
                _root.attributes("-topmost", True)
                _init_dir = os.path.dirname(st.session_state.get(f"ep_plot_path_{_dk}", "")) or _default_dir
                _selected = filedialog.askopenfilename(
                    initialdir=_init_dir,
                    filetypes=[("Text", "*.txt *.md"), ("All", "*.*")],
                    parent=_root,
                )
                _root.destroy()
                if _selected:
                    _selected = _selected.replace("/", os.sep)
                    with open(_selected, encoding="utf-8") as _lf:
                        st.session_state[f"ep_plot_{_dk}"] = _lf.read().strip()
                    st.session_state[f"ep_plot_path_{_dk}"] = _selected
                    st.session_state[f"ep_plot_ver_{_dk}"] = st.session_state.get(f"ep_plot_ver_{_dk}", 0) + 1
                    st.rerun(scope="fragment")
        with col_path:
            _cur_path = st.session_state.get(f"ep_plot_path_{_dk}", "") or current.get("plot_file", "")
            if _cur_path:
                st.caption(os.path.basename(_cur_path))

        st.divider()

        _plot_ver = st.session_state.get(f"ep_plot_ver_{_dk}", 0)
        _plot_val = st.session_state.get(f"ep_plot_{_dk}", current.get("plot", ""))
        _plot = st.text_area(
            "Plot" if _ui_lang == "en" else "プロット",
            value=_plot_val, height=400, key=f"ep_plot_input_{_dk}_{_plot_ver}",
        )

        _save_path = st.session_state.get(f"ep_plot_path_{_dk}", "") or current.get("plot_file", "")

        c_save, c_apply = st.columns(2)
        with c_save:
            if st.button("💾 Save" if _ui_lang == "en" else "💾 保存", key="ep_plot_save"):
                _ep_data = next((e for e in episodes if e["id"] == ep_id), None) if ep_id else None
                if _ep_data is None:
                    _ep_data = {"id": str(uuid.uuid4()), "title": ep_title or "Untitled", "body": ""}
                    st.session_state.episode_selected_id = _ep_data["title"]
                _ep_data["plot"] = _plot
                _ep_data["plot_file"] = _save_path
                if _save_path:
                    _abs_save = _save_path if os.path.isabs(_save_path) else os.path.join(os.path.dirname(os.path.dirname(__file__)), _save_path)
                    os.makedirs(os.path.dirname(_abs_save), exist_ok=True)
                    with open(_abs_save, "w", encoding="utf-8") as _sf:
                        _sf.write(_plot + "\n")
                _save_episode(_ep_data)
                st.success("Saved." if _ui_lang == "en" else "保存しました。")
        with c_apply:
            if st.button("✅ Apply" if _ui_lang == "en" else "✅ 反映", key="ep_plot_apply"):
                _ep_data = next((e for e in episodes if e["id"] == ep_id), None) if ep_id else None
                if _ep_data is None:
                    _ep_data = {"id": str(uuid.uuid4()), "title": ep_title or "Untitled", "body": ""}
                    st.session_state.episode_selected_id = _ep_data["title"]
                _ep_data["plot"] = _plot
                _ep_data["plot_file"] = _save_path
                if _save_path:
                    _abs_save = _save_path if os.path.isabs(_save_path) else os.path.join(os.path.dirname(os.path.dirname(__file__)), _save_path)
                    os.makedirs(os.path.dirname(_abs_save), exist_ok=True)
                    with open(_abs_save, "w", encoding="utf-8") as _sf:
                        _sf.write(_plot + "\n")
                _save_episode(_ep_data)
                st.rerun()

    st.subheader(_t("tab_episode"))
    episodes = _load_episodes()
    ep_titles = [e["title"] for e in episodes]
    ep_options = [None] + ep_titles
    ep_labels = {None: "+ New" if _ui_lang == "en" else "+ 新規作品"}
    ep_labels.update({t: t for t in ep_titles})

    if "episode_selected_id" not in st.session_state:
        st.session_state.episode_selected_id = ep_titles[0] if ep_titles else None

    _ep_idx = ep_options.index(st.session_state.episode_selected_id) if st.session_state.episode_selected_id in ep_options else 0
    sel_ep_id = st.selectbox("Select" if _ui_lang == "en" else "作品を選択", ep_options, index=_ep_idx, format_func=lambda k: ep_labels[k])
    st.session_state.episode_selected_id = sel_ep_id

    cur_ep = next((e for e in episodes if e["title"] == sel_ep_id), {"id": None, "title": "", "body": ""}) if sel_ep_id else {"id": None, "title": "", "body": ""}
    _ek = cur_ep.get("title") or "new"
    ep_title = st.text_input("Title" if _ui_lang == "en" else "タイトル", value=cur_ep["title"], key=f"ep_title_{_ek}")

    col_plot_btn, col_plot_info, col_ep_llm = st.columns([1, 2, 2])
    with col_plot_btn:
        if st.button("📝 Plot" if _ui_lang == "en" else "📝 プロット設定", key="ep_plot_open"):
            _render_plot_dialog(cur_ep["id"], ep_title)
    with col_ep_llm:
        _ep_backend_keys = list(LLM_BACKENDS.keys())
        _ep_cur_backend = st.session_state.get("episode_llm_backend", st.session_state.get("llm_backend", DEFAULT_LLM_BACKEND))
        if _ep_cur_backend not in _ep_backend_keys:
            _ep_cur_backend = _ep_backend_keys[0]
        st.session_state.episode_llm_backend = st.selectbox(
            "LLM" if _ui_lang == "en" else "LLM",
            _ep_backend_keys,
            index=_ep_backend_keys.index(_ep_cur_backend),
            format_func=lambda k: LLM_BACKEND_LABELS.get(k, k),
            key="ep_llm_sel",
            label_visibility="collapsed",
        )
    with col_plot_info:
        _plot_file = cur_ep.get("plot_file", "")
        if _plot_file:
            st.caption(f"✅ {os.path.basename(_plot_file)}")
        elif cur_ep.get("plot"):
            st.caption("✅ Set" if _ui_lang == "en" else "✅ 設定済み")
        else:
            st.caption("Not set" if _ui_lang == "en" else "未設定")

    _draft_key = f"ep_draft_{_ek}"
    _draft_ver = st.session_state.get(f"ep_draft_ver_{_ek}", 0)
    _body_ver = st.session_state.get(f"ep_body_ver_{_ek}", 0)

    col_body, col_draft = st.columns(2)
    with col_body:
        ep_body = st.text_area("Body" if _ui_lang == "en" else "本文", value=cur_ep["body"], height=400, key=f"ep_body_{_ek}_{_body_ver}")

        import re as _re
        _ch_nums = [int(m) for m in _re.findall(r"--- Chapter (\d+) ---", ep_body)]
        _cur_ch = max(_ch_nums) if _ch_nums else 0
        _sc_pattern = f"--- Chapter {_cur_ch} ---" if _cur_ch else ""
        if _cur_ch:
            _after_ch = ep_body.split(_sc_pattern)[-1]
            _sc_nums = [int(m) for m in _re.findall(r"--- Scene (\d+) ---", _after_ch)]
            _cur_sc = max(_sc_nums) if _sc_nums else 0
        else:
            _cur_sc = 0

        if not ep_body.strip():
            _init_marker = "--- Chapter 1 ---\n--- Scene 1 ---\n"
        else:
            _init_marker = None

        c_save, c_ai, c_chsc, _c_sp, c_del = st.columns([2, 2, 3, 1, 2])
        with c_save:
            if st.button("💾 Save" if _ui_lang == "en" else "💾 保存", key="ep_save"):
                if not ep_title:
                    st.warning("Enter a title." if _ui_lang == "en" else "タイトルを入力してください。")
                else:
                    _ep_data = dict(cur_ep)
                    _ep_data["title"] = ep_title
                    _ep_data["body"] = ep_body
                    _save_episode(_ep_data)
                    st.session_state.episode_selected_id = ep_title
                    st.success("Saved." if _ui_lang == "en" else "保存しました。")
                    st.rerun()
        with c_ai:
            if st.button("✍ Generate" if _ui_lang == "en" else "✍ 生成", key="ep_continue"):
                _sys = cur_ep.get("plot", "")
                if not _sys:
                    _sys = ("Continue the story naturally. Maintain the tone, style, and world-building. "
                            "Do not repeat the given text. Write only new content.") if _ui_lang == "en" else (
                            "与えられた物語の続きを、文体や世界観を保ったまま自然に書き続けてください。"
                            "与えられたテキストを繰り返してはいけません。新しい展開のみを書いてください。")
                _msgs = [
                    {"role": "system", "content": _sys},
                    {"role": "user", "content": ep_body or ("No text yet. Start the story." if _ui_lang == "en" else "(まだ本文はありません。物語の冒頭を書き始めてください。)")},
                ]
                _ep_backend = st.session_state.get("episode_llm_backend", st.session_state.get("llm_backend", DEFAULT_LLM_BACKEND))
                if _ep_backend == "textgen_webui":
                    _ep_model = get_loaded_model_name() or ""
                else:
                    _ep_model = _get_ext_model(_ep_backend)
                _candidates = []
                _n_candidates = st.session_state.get("episode_candidate_count", 3)
                for _ci in range(_n_candidates):
                    with st.spinner(f"{'Generating' if _ui_lang == 'en' else '生成中'} {_ci + 1}/{_n_candidates} ..."):
                        try:
                            from def_kari.models.registry import get_llm_profile
                            _ep_profile = get_llm_profile(_ep_model)
                            _ep_max = _ep_profile.get("max_tokens", 2048)
                            _ep_gen = _ep_profile.get("generation_params", {})
                            _ep_opts = {"num_predict": _ep_max}
                            _ep_opts.update(_ep_gen)
                            _cont = LLM_BACKENDS[_ep_backend]["chat"](_msgs, _ep_model, json_mode=False, options=_ep_opts)
                        except Exception as _ep_err:
                            st.error(f"#{_ci + 1}: {_ep_err}")
                            _cont = None
                    if _cont:
                        _candidates.append(_cont)
                if _candidates:
                    st.session_state[f"ep_candidates_{_ek}"] = _candidates
                    st.session_state[f"ep_draft_ver_{_ek}"] = _draft_ver + 1
                    st.rerun()
        with c_chsc:
            _cch, _csc = st.columns(2)
            with _cch:
                if st.button("New Ch" if _ui_lang == "en" else "新章", key="ep_ch_end"):
                    _new_ch = _cur_ch + 1
                    _marker = f"\n--- Chapter {_new_ch} ---\n--- Scene 1 ---\n"
                    if _init_marker and not ep_body.strip():
                        _new_body = _init_marker
                    else:
                        _new_body = ep_body + _marker
                    _ep_data = dict(cur_ep)
                    _ep_data["title"] = ep_title or "Untitled"
                    _ep_data["body"] = _new_body
                    _save_episode(_ep_data)
                    st.session_state.episode_selected_id = _ep_data["title"]
                    st.session_state[f"ep_body_ver_{_ek}"] = _body_ver + 1
                    st.rerun()
            with _csc:
                if st.button("New Sc" if _ui_lang == "en" else "新場面", key="ep_sc_end"):
                    _new_sc = _cur_sc + 1
                    if _init_marker and not ep_body.strip():
                        _new_body = _init_marker
                    else:
                        _marker = f"\n--- Scene {_new_sc} ---\n"
                        _new_body = ep_body + _marker
                    _ep_data = dict(cur_ep)
                    _ep_data["title"] = ep_title or "Untitled"
                    _ep_data["body"] = _new_body
                    _save_episode(_ep_data)
                    st.session_state.episode_selected_id = _ep_data["title"]
                    st.session_state[f"ep_body_ver_{_ek}"] = _body_ver + 1
                    st.rerun()

        with c_del:
            if cur_ep.get("title") and st.button("🗑 Delete" if _ui_lang == "en" else "🗑 削除", key="ep_delete"):
                _delete_episode(cur_ep)
                st.session_state.episode_selected_id = None
                st.rerun()

    with col_draft:
        _candidates = st.session_state.get(f"ep_candidates_{_ek}", [])
        if _candidates:
            _tab_labels = [f"#{i+1}" for i in range(len(_candidates))]
            _tabs = st.tabs(_tab_labels)
            for _ti, _tab in enumerate(_tabs):
                with _tab:
                    st.text_area(
                        f"#{_ti+1}",
                        value=_candidates[_ti],
                        height=350,
                        key=f"ep_cand_{_ek}_{_draft_ver}_{_ti}",
                        label_visibility="collapsed",
                    )
                    _ca, _cc = st.columns(2)
                    with _ca:
                        if st.button("⬇ Append" if _ui_lang == "en" else "⬇ 本文に追加", key=f"ep_pick_{_ti}"):
                            new_body = f"{ep_body}\n{_candidates[_ti]}" if ep_body else _candidates[_ti]
                            _ep_data = dict(cur_ep)
                            _ep_data["title"] = ep_title or "Untitled"
                            _ep_data["body"] = new_body
                            _save_episode(_ep_data)
                            st.session_state.episode_selected_id = _ep_data["title"]
                            st.session_state.pop(f"ep_candidates_{_ek}", None)
                            st.session_state[f"ep_draft_ver_{_ek}"] = _draft_ver + 1
                            st.session_state[f"ep_body_ver_{_ek}"] = _body_ver + 1
                            st.rerun()
                    with _cc:
                        if st.button("🗑 Clear" if _ui_lang == "en" else "🗑 クリア", key=f"ep_clear_{_ti}"):
                            st.session_state.pop(f"ep_candidates_{_ek}", None)
                            st.session_state[f"ep_draft_ver_{_ek}"] = _draft_ver + 1
                            st.rerun()
        else:
            st.caption("No candidates yet." if _ui_lang == "en" else "「生成」で候補が表示されます。")

    # --- Episode T2I Settings Dialog ---
    @st.dialog("T2I Settings" if _ui_lang == "en" else "T2I設定")
    def _render_t2i_dialog():
        from def_kari.config import T2I_BACKENDS, T2I_BACKEND_LABELS, DEFAULT_T2I_BACKEND
        _cur_t2i = st.session_state.get("episode_t2i_backend", st.session_state.get("t2i_backend", DEFAULT_T2I_BACKEND))
        if _cur_t2i not in T2I_BACKENDS:
            _cur_t2i = T2I_BACKENDS[0]
        _new_t2i = st.selectbox(
            "Backend" if _ui_lang == "en" else "バックエンド",
            T2I_BACKENDS,
            index=T2I_BACKENDS.index(_cur_t2i),
            format_func=lambda k: T2I_BACKEND_LABELS.get(k, k),
            key="ep_t2i_backend_sel",
        )
        _model_val = st.session_state.get(f"episode_t2i_model_{_new_t2i}", st.session_state.get("episode_t2i_model", st.session_state.get("t2i_model", "")))
        if _new_t2i in ("a1111", "comfyui"):
            try:
                from def_kari.workers._t2i_generate import list_a1111_models, list_comfyui_models
                _models = list_a1111_models() if _new_t2i == "a1111" else list_comfyui_models()
                if _models:
                    if _model_val and _model_val not in _models:
                        _models.append(_model_val)
                    _mi = _models.index(_model_val) if _model_val in _models else 0
                    _model_val = st.selectbox("Model" if _ui_lang == "en" else "モデル", _models, index=_mi, key="ep_t2i_model_sel")
                else:
                    _model_val = st.text_input("Model" if _ui_lang == "en" else "モデル", value=_model_val, key="ep_t2i_model_input")
            except Exception:
                _model_val = st.text_input("Model" if _ui_lang == "en" else "モデル", value=_model_val, key="ep_t2i_model_input")
        elif _new_t2i == "huggingface":
            _hf_presets = [
                "black-forest-labs/FLUX.1-schnell",
                "stabilityai/stable-diffusion-xl-base-1.0",
                "stabilityai/stable-diffusion-2-1",
            ]
            if _model_val and _model_val not in _hf_presets:
                _hf_presets.append(_model_val)
            _hi = _hf_presets.index(_model_val) if _model_val in _hf_presets else 0
            _model_val = st.selectbox("Model" if _ui_lang == "en" else "モデル", _hf_presets, index=_hi, key="ep_t2i_hf_sel")
            _custom = st.text_input("Custom" if _ui_lang == "en" else "カスタム", placeholder="user/model-name", key="ep_t2i_hf_custom")
            if _custom:
                _model_val = _custom
        elif _new_t2i == "civitai":
            _civitai_history = list(st.session_state.get("ep_t2i_civitai_history", []))
            if _model_val and _model_val not in _civitai_history:
                _civitai_history.insert(0, _model_val)
            _ci_idx = _civitai_history.index(_model_val) if _model_val in _civitai_history else 0
            if _civitai_history:
                _model_val = st.selectbox("Model" if _ui_lang == "en" else "モデル", _civitai_history, index=_ci_idx, key="ep_t2i_civitai_sel")
            _custom_civitai = st.text_input("New" if _ui_lang == "en" else "新規", placeholder="URL / AIR", key="ep_t2i_civitai_new")
            if _custom_civitai:
                _model_val = _custom_civitai
                if _custom_civitai not in _civitai_history:
                    _civitai_history.insert(0, _custom_civitai)
                st.session_state["ep_t2i_civitai_history"] = _civitai_history
        else:
            _model_val = st.text_input("Model" if _ui_lang == "en" else "モデル", value=_model_val, key="ep_t2i_model_input")
        if st.button("✅ Apply" if _ui_lang == "en" else "✅ 反映", key="ep_t2i_apply"):
            st.session_state["episode_t2i_backend"] = _new_t2i
            st.session_state["episode_t2i_model"] = _model_val
            st.session_state[f"episode_t2i_model_{_new_t2i}"] = _model_val
            st.rerun()

    # --- Episode TTS / T2I (full width, below 2-column layout) ---
    _ep_scenes = _re.split(r"(--- Scene \d+ ---)", ep_body)
    _ep_scene_list = []
    _sc_label = ""
    for _seg in _ep_scenes:
        if _re.match(r"--- Scene \d+ ---", _seg):
            _sc_label = _seg.strip()
        elif _seg.strip():
            _clean = _re.sub(r"--- Chapter \d+ ---", "", _seg).strip()
            if _clean:
                _ep_scene_list.append((_sc_label or "Scene", _clean))

    col_ep_tts_cur, col_ep_t2i_cur, col_ep_scene_sel, col_ep_tts_sel, col_ep_t2i_sel, col_ep_t2i_cfg = st.columns([1, 1, 2, 1, 1, 1])
    _cur_scene_text = _ep_scene_list[-1][1] if _ep_scene_list else _re.sub(r"--- (?:Chapter|Scene) \d+ ---", "", ep_body).strip()
    with col_ep_tts_cur:
        if st.button("🔊 Current" if _ui_lang == "en" else "🔊 現場面", key="ep_tts_cur"):
            if _cur_scene_text:
                st.session_state["_ep_tts_target"] = _cur_scene_text
            else:
                st.warning("No text." if _ui_lang == "en" else "本文がありません。")
    with col_ep_t2i_cur:
        if st.button("🎨 Current" if _ui_lang == "en" else "🎨 現挿絵", key="ep_t2i_cur"):
            if _cur_scene_text:
                st.session_state["_ep_t2i_target"] = _cur_scene_text
            else:
                st.warning("No text." if _ui_lang == "en" else "本文がありません。")
    with col_ep_scene_sel:
        if _ep_scene_list:
            _scene_options = [f"{sl}" for sl, _ in _ep_scene_list]
            _sel_scene = st.selectbox("Scene", _scene_options, key="ep_scene_sel", label_visibility="collapsed")
            _sel_idx = _scene_options.index(_sel_scene)
        else:
            _sel_idx = -1
    with col_ep_tts_sel:
        if _sel_idx >= 0 and st.button("🔊 Select" if _ui_lang == "en" else "🔊 選択読上", key="ep_tts_sel"):
            st.session_state["_ep_tts_target"] = _ep_scene_list[_sel_idx][1]
    with col_ep_t2i_sel:
        if _sel_idx >= 0 and st.button("🎨 Select" if _ui_lang == "en" else "🎨 選択挿絵", key="ep_t2i_sel"):
            st.session_state["_ep_t2i_target"] = _ep_scene_list[_sel_idx][1]
    with col_ep_t2i_cfg:
        if st.button("⚙ T2I", key="ep_t2i_cfg"):
            _render_t2i_dialog()
    if f"ep_media_{_ek}" not in st.session_state:
        st.session_state[f"ep_media_{_ek}"] = []
    _ep_media_list = st.session_state[f"ep_media_{_ek}"]

    _ep_media_container = st.container()
    with _ep_media_container:
        for _med in _ep_media_list:
            with st.chat_message("assistant"):
                if _med["type"] == "tts":
                    st.caption(_med["text"])
                    st.audio(_med["audio"], format="audio/wav")
                elif _med["type"] == "t2i":
                    st.caption(f"Prompt: {_med['prompt'][:200]}")
                    _clickable_image(_med["path"])

        if st.session_state.get("_ep_tts_target"):
            _tts_text = st.session_state.pop("_ep_tts_target").strip()
            _tts_text = _re.sub(r"--- (?:Chapter|Scene) \d+ ---", "", _tts_text).strip()
            if _tts_text:
                    _tts_backend = st.session_state.get("tts_backend", "voicevox")
                    _active_char = get_character(st.session_state.get("active_character", ""), _profiles)
                    _tts_spk = get_tts_speaker_id(_active_char, _tts_backend)
                    _MAX_CHUNK = 400
                    _sentences = []
                    for _line in _tts_text.split("\n"):
                        _line = _line.strip()
                        if not _line:
                            continue
                        for _sent in _re.split(r"(?<=。)", _line):
                            _sent = _sent.strip()
                            if _sent:
                                _sentences.append(_sent)
                    _chunks = []
                    _buf = ""
                    for _sent in _sentences:
                        if _buf and len(_buf) + len(_sent) > _MAX_CHUNK:
                            _chunks.append(_buf)
                            _buf = _sent
                        else:
                            _buf = f"{_buf}{_sent}" if _buf else _sent
                    if _buf:
                        _chunks.append(_buf)
                    from def_kari.workers._tts_synth import synthesize
                    import io, wave, time
                    def _wav_bytes_duration(data: bytes) -> float:
                        try:
                            with wave.open(io.BytesIO(data), "r") as wf:
                                return wf.getnframes() / wf.getframerate()
                        except Exception:
                            return 2.0
                    _next_audio = None
                    _next_chunk_text = None
                    try:
                        _next_audio = synthesize(apply_name_reading(_chunks[0], _active_char), _tts_spk, _tts_backend)
                        _next_chunk_text = _chunks[0]
                    except Exception as _tts_err:
                        st.error(str(_tts_err))
                    for _ci in range(len(_chunks)):
                        if _next_audio is None:
                            break
                        _cur_audio = _next_audio
                        _cur_text = _next_chunk_text
                        _ep_media_list.append({"type": "tts", "text": _cur_text, "audio": _cur_audio})
                        with st.chat_message("assistant"):
                            st.caption(_cur_text)
                            st.audio(_cur_audio, format="audio/wav", autoplay=True)
                        _dur = _wav_bytes_duration(_cur_audio) + 0.5
                        _gen_start = time.time()
                        _next_audio = None
                        _next_chunk_text = None
                        if _ci + 1 < len(_chunks):
                            try:
                                _next_audio = synthesize(apply_name_reading(_chunks[_ci + 1], _active_char), _tts_spk, _tts_backend)
                                _next_chunk_text = _chunks[_ci + 1]
                            except Exception as _tts_err:
                                st.error(str(_tts_err))
                        _elapsed = time.time() - _gen_start
                        _wait = max(0, _dur - _elapsed)
                        if _wait > 0:
                            time.sleep(_wait)

        if st.session_state.get("_ep_t2i_target"):
            _t2i_src = st.session_state.pop("_ep_t2i_target")
            _t2i_plot = cur_ep.get("plot", "")
            _ep_t2i_backend = st.session_state.get("episode_llm_backend", st.session_state.get("llm_backend", DEFAULT_LLM_BACKEND))
            if _ep_t2i_backend == "textgen_webui":
                _t2i_llm_model = get_loaded_model_name() or ""
            else:
                _t2i_llm_model = _get_ext_model(_ep_t2i_backend)
            _t2i_sys = ("You are an image prompt generator. Given a scene from a story, generate a concise English image prompt "
                        "suitable for AI image generation (Stable Diffusion style). Output ONLY the prompt, no explanation.")
            if _t2i_plot:
                _t2i_sys += f"\n\nStory context:\n{_t2i_plot[:500]}"
            _t2i_msgs = [
                {"role": "system", "content": _t2i_sys},
                {"role": "user", "content": _t2i_src[:1000]},
            ]
            with st.spinner("Generating image prompt..." if _ui_lang == "en" else "画像プロンプト生成中..."):
                try:
                    _img_prompt = LLM_BACKENDS[_ep_t2i_backend]["chat"](_t2i_msgs, _t2i_llm_model, json_mode=False, options={"num_predict": 150})
                except Exception as _ip_err:
                    st.error(str(_ip_err))
                    _img_prompt = None
            if _img_prompt:
                with st.spinner("Generating image..." if _ui_lang == "en" else "画像生成中..."):
                    try:
                        from def_kari.workers._t2i_generate import generate_image
                        _ep_img_path = generate_image(
                            prompt=_img_prompt,
                            width=st.session_state.get("episode_t2i_width", 1216),
                            height=st.session_state.get("episode_t2i_height", 832),
                            model_name=st.session_state.get("episode_t2i_model", st.session_state.get("t2i_model", "")),
                            backend=st.session_state.get("episode_t2i_backend", st.session_state.get("t2i_backend", "a1111")),
                        )
                        _ep_media_list.append({"type": "t2i", "prompt": _img_prompt, "path": _ep_img_path})
                        with st.chat_message("assistant"):
                            st.caption(f"Prompt: {_img_prompt[:200]}")
                            _clickable_image(_ep_img_path)
                    except Exception as _t2i_err:
                        st.error(str(_t2i_err))

with tab_thought:
    st.subheader(_t("thought_title"))
    st.caption(_t("thought_desc"))

    _THOUGHTS_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "private", "thoughts.json")

    def _load_thoughts() -> list:
        if not os.path.exists(_THOUGHTS_PATH):
            return []
        try:
            import json as _jt
            with open(_THOUGHTS_PATH, encoding="utf-8") as f:
                return _jt.load(f)
        except (_json.JSONDecodeError, OSError):
            return []

    def _save_thoughts(thoughts: list) -> None:
        import json as _jt
        os.makedirs(os.path.dirname(_THOUGHTS_PATH), exist_ok=True)
        with open(_THOUGHTS_PATH, "w", encoding="utf-8") as f:
            _jt.dump(thoughts, f, ensure_ascii=False, indent=2)

    _thoughts = _load_thoughts()
    _input_ver = st.session_state.get("thinking_input_version", 0)
    _thinking_input = st.text_area(_t("thought_input_label"), height=150, key=f"thinking_input_{_input_ver}")

    if st.button(_t("thought_submit"), key="thinking_submit", disabled=not _thinking_input):
        _messages = [
            {
                "role": "system",
                "content": "あなたはユーザーの思考の整理・深掘りを助ける汎用アシスタントです。"
                "ユーザーの入力内容を要約・整理したうえで、新たな視点や問いを提示し、"
                "ユーザー自身が考えを深められるように応答してください。",
            },
            {"role": "user", "content": _thinking_input},
        ]
        if st.session_state.llm_backend == "textgen_webui":
            _th_model = get_loaded_model_name() or ""
        else:
            _th_model = _get_ext_model(st.session_state.llm_backend)
        with st.spinner(_t("chat_thinking")):
            try:
                _th_output = LLM_BACKENDS[st.session_state.llm_backend]["chat"](
                    _messages, _th_model, json_mode=False
                )
            except Exception as _th_err:
                st.error(f"応答の生成に失敗しました: {_th_err}")
                _th_output = None
        if _th_output:
            _thoughts.append({
                "id": str(uuid.uuid4()),
                "input": _thinking_input,
                "output": _th_output,
                "model": _th_model,
            })
            _save_thoughts(_thoughts)
            st.session_state.thinking_input_version = _input_ver + 1
            st.rerun()

    if _thoughts:
        st.subheader(_t("thought_history"))
        for _th in reversed(_thoughts):
            with st.expander(_th["input"].splitlines()[0][:40] if _th.get("input") else "(無題)"):
                st.markdown(f"**IN:** {_th['input']}")
                _th_model_label = _th.get("model", "")
                st.markdown(f"**OUT:** {_th['output']}")
                if _th_model_label:
                    st.caption(f"model: {_th_model_label}")
                if st.button("🗑 削除", key=f"thinking_delete_{_th['id']}"):
                    _thoughts = [t for t in _thoughts if t["id"] != _th["id"]]
                    _save_thoughts(_thoughts)
                    st.rerun()

with tab_settings:
    with st.expander("📁 Backend Directories" if _ui_lang == "en" else "📁 バックエンドディレクトリ設定", expanded=False):
        st.caption("Configure backend directories and URLs." if _ui_lang == "en" else "各バックエンドのインストールディレクトリとURLを設定します。変更後は「💾 保存して再起動」を押してください。")

        _dir_settings = {
            "TEXTGEN_WEBUI_DIR": {"label": "TGW Directory" if _ui_lang == "en" else "TGW ディレクトリ", "default": ""},
            "VOICEVOX_DIR": {"label": "VOICEVOX Directory" if _ui_lang == "en" else "VOICEVOX ディレクトリ", "default": ""},
            "VOICEVOX_URL": {"label": "VOICEVOX URL", "default": "http://127.0.0.1:50021"},
            "IRODORI_TTS_DIR": {"label": "Irodori-TTS Directory" if _ui_lang == "en" else "Irodori-TTS ディレクトリ", "default": ""},
            "IRODORI_TTS_URL": {"label": "Irodori-TTS URL", "default": "http://127.0.0.1:8088"},
            "KOKORO_TTS_DIR": {"label": "Kokoro TTS Directory" if _ui_lang == "en" else "Kokoro TTS ディレクトリ", "default": ""},
            "KOKORO_TTS_URL": {"label": "Kokoro TTS URL", "default": "http://127.0.0.1:8766"},
            "A1111_DIR": {"label": "A1111 Directory" if _ui_lang == "en" else "A1111 ディレクトリ", "default": ""},
            "A1111_URL": {"label": "A1111 URL", "default": "http://localhost:7860"},
            "COMFYUI_DIR": {"label": "ComfyUI Directory" if _ui_lang == "en" else "ComfyUI ディレクトリ", "default": ""},
            "COMFYUI_URL": {"label": "ComfyUI URL", "default": "http://127.0.0.1:8188"},
        }
        _dir_values = {}
        for _dk, _dv in _dir_settings.items():
            _dir_values[_dk] = st.text_input(
                _dv["label"],
                value=os.environ.get(_dk, _dv["default"]),
                key=f"dir_setting_{_dk}",
            )

        if st.button("💾 Save & Restart" if _ui_lang == "en" else "💾 保存して再起動", key="save_dir_settings"):
            _env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
            _lines = []
            for _dk, _val in _dir_values.items():
                _lines.append(f"{_dk}={_val}")
            with open(_env_path, "w", encoding="utf-8") as _ef:
                _ef.write("\n".join(_lines) + "\n")
            for _dk, _val in _dir_values.items():
                os.environ[_dk] = _val
            st.toast("Directory settings saved. Restart to apply." if _ui_lang == "en" else "ディレクトリ設定を保存しました。再起動すると反映されます。")

    st.subheader(_t("settings_user_lang"))
    _lang_options = ["ja", "en", "zh", "ko", "es", "fr", "de"]
    _lang_labels = {"ja": "日本語", "en": "English", "zh": "中文", "ko": "한국어", "es": "Español", "fr": "Français", "de": "Deutsch"}
    _prev_lang = st.session_state.get("user_language", "ja")
    if _prev_lang not in _lang_options:
        _prev_lang = "ja"
    _new_lang = st.selectbox(
        _t("settings_response_lang"),
        _lang_options,
        index=_lang_options.index(_prev_lang),
        format_func=lambda k: _lang_labels.get(k, k),
        key="user_language_sel",
    )
    st.session_state.user_language = _new_lang
    if _new_lang != _prev_lang:
        st.rerun()

    st.divider()

    st.subheader(_t("settings_llm_backend"))
    backend_keys = list(LLM_BACKEND_LABELS)
    _prev_llm = st.session_state.llm_backend
    st.session_state.llm_backend = st.selectbox(
        _t("settings_backend_label"),
        backend_keys,
        index=backend_keys.index(st.session_state.llm_backend)
        if st.session_state.llm_backend in backend_keys
        else 0,
        format_func=lambda k: LLM_BACKEND_LABELS[k],
    )
    if st.session_state.llm_backend != _prev_llm:
        st.rerun()

    @st.fragment(run_every=f"{st.session_state.get('status_poll_sec', DEFAULT_STATUS_POLL_SEC)}s")
    def _llm_status():
        if st.session_state.llm_backend == "textgen_webui":
            if tgw_is_running():
                if tgw_model_loaded():
                    _loaded = get_loaded_model_name() or ""
                    _tgw_msg = f"✅ TGW running. Model: {_loaded}" if _ui_lang == "en" else f"✅ TGW起動中。モデル: {_loaded}"
                    st.caption(_tgw_msg)
                    st.session_state.tgw_autoload_attempted = False
                else:
                    st.warning("⚠️ TGW running but no model loaded." if _ui_lang == "en" else "⚠️ TGWは起動していますがモデルが未ロードです。")
            else:
                st.error("❌ TGW not running." if _ui_lang == "en" else "❌ TGWが起動していません。")
        elif st.session_state.llm_backend == "ollama":
            try:
                import requests as _req
                _req.get("http://localhost:11434/api/tags", timeout=2).raise_for_status()
                st.caption("✅ Ollama running" if _ui_lang == "en" else "✅ Ollama起動中")
            except Exception:
                st.error("❌ Ollama not running." if _ui_lang == "en" else "❌ Ollamaが起動していません。")
    _llm_status()

    if st.session_state.llm_backend == "textgen_webui":
        available_models = list_available_models()
        if available_models:
            cur_autoload = st.session_state.tgw_autoload_model
            idx = available_models.index(cur_autoload) if cur_autoload in available_models else 0
            selected = st.selectbox(
                "Auto-load model on TGW start" if _ui_lang == "en" else "TGW起動時に自動ロードするモデル",
                available_models,
                index=idx,
            )
            if selected != cur_autoload:
                st.session_state.tgw_autoload_model = selected
                st.session_state.tgw_autoload_attempted = False
            if st.button("Load Now" if _ui_lang == "en" else "今すぐロード"):
                load_model_async(selected)
                st.session_state.tgw_autoload_attempted = True
                st.toast(f"Loading **{selected}**..." if _ui_lang == "en" else f"モデル **{selected}** のロードを開始しました。")
    else:
        _svc_id = st.session_state.llm_backend
        _svc_key_id = None
        for _s in _load_api_services():
            if _s["id"] == _svc_id:
                _svc_key_id = _s["id"]
                break
        _has_key = bool(
            os.environ.get(f"{_svc_id.upper()}_API_KEY")
            or secrets_store.get_api_key(_svc_key_id or _svc_id)
        )
        if _has_key:
            st.caption(f"✅ {LLM_BACKEND_LABELS.get(_svc_id, _svc_id)} — " + ("API key set" if _ui_lang == "en" else "APIキー設定済み"))
            try:
                _ext_models = LLM_BACKENDS[_svc_id]["list_models"]()
                if _ext_models:
                    _per_backend_key = f"llm_ext_model_{_svc_id}"
                    _cur_ext_model = st.session_state.get(_per_backend_key) or st.session_state.get("llm_ext_model") or LLM_BACKENDS[_svc_id]["default_model"]
                    _ext_idx = _ext_models.index(_cur_ext_model) if _cur_ext_model in _ext_models else 0
                    _selected_model = st.selectbox(
                        "Model" if _ui_lang == "en" else "モデル",
                        _ext_models,
                        index=_ext_idx,
                        key=f"llm_ext_model_sel_{_svc_id}",
                    )
                    st.session_state[_per_backend_key] = _selected_model
                    st.session_state.llm_ext_model = _selected_model
            except Exception:
                st.caption("Failed to get model list." if _ui_lang == "en" else "モデル一覧の取得に失敗しました。")
        else:
            st.warning(f"⚠ {LLM_BACKEND_LABELS.get(_svc_id, _svc_id)} — " + ("API key not set." if _ui_lang == "en" else "APIキー未設定。APIキー管理から設定してください。"))

    # 現在のモデル名を取得
    if st.session_state.llm_backend == "textgen_webui":
        _cur_model_for_params = get_loaded_model_name() or ""
    else:
        _cur_model_for_params = _get_ext_model(st.session_state.llm_backend)

    if _cur_model_for_params:
        from def_kari.models.registry import get_llm_profile, _save_profile
        _cur_profile = get_llm_profile(_cur_model_for_params)

        with st.expander(f"📋 " + ("Model Profile: " if _ui_lang == "en" else "モデルプロファイル: ") + f"{_cur_model_for_params}", expanded=False):
            _new_native_lang = st.selectbox(
                "native_language" if _ui_lang == "en" else "native_language（モデルの主言語）",
                ["ja", "en", "zh", "ko"],
                index=["ja", "en", "zh", "ko"].index(_cur_profile.get("native_language", "en")) if _cur_profile.get("native_language", "en") in ["ja", "en", "zh", "ko"] else 1,
                key="prof_native_lang",
            )
            _new_nsfw = st.selectbox(
                "nsfw_tolerance" if _ui_lang == "en" else "nsfw_tolerance（NSFW耐性）",
                ["sfw", "nsfw", "hentai"],
                index=["sfw", "nsfw", "hentai"].index(_cur_profile.get("nsfw_tolerance", "sfw")) if _cur_profile.get("nsfw_tolerance", "sfw") in ["sfw", "nsfw", "hentai"] else 0,
                key="prof_nsfw",
            )
            _new_model_type = st.selectbox(
                "model_type" if _ui_lang == "en" else "model_type（モデル種別）",
                ["chat", "novel", "instruct"],
                index=["chat", "novel", "instruct"].index(_cur_profile.get("model_type", "chat")) if _cur_profile.get("model_type", "chat") in ["chat", "novel", "instruct"] else 0,
                key="prof_model_type",
            )
            _new_max_tokens = st.number_input(
                "max_tokens" if _ui_lang == "en" else "max_tokens（最大出力トークン数）",
                min_value=64, max_value=16384, step=64,
                value=int(_cur_profile.get("max_tokens", 512)),
                key="prof_max_tokens",
            )

            st.caption("quirks")
            _cur_quirks = _cur_profile.get("quirks", {})
            _new_json_capable = st.checkbox("json_capable" if _ui_lang == "en" else "json_capable（JSON出力可能）", value=_cur_quirks.get("json_capable", True), key="prof_json_capable")
            _new_appends_meta = st.checkbox("appends_meta_text" if _ui_lang == "en" else "appends_meta_text（メタテキスト付与）", value=_cur_quirks.get("appends_meta_text", False), key="prof_appends_meta")
            _new_outputs_url = st.checkbox("outputs_url_in_prompt" if _ui_lang == "en" else "outputs_url_in_prompt（URLを出力する）", value=_cur_quirks.get("outputs_url_in_prompt", False), key="prof_outputs_url")
            _new_emotion_in_text = st.checkbox("emotion_in_text" if _ui_lang == "en" else "emotion_in_text（テキスト中に感情表現）", value=_cur_quirks.get("emotion_in_text", False), key="prof_emotion_text")

            st.caption("Generation Params" if _ui_lang == "en" else "生成パラメータ")
            _cur_gen = _cur_profile.get("generation_params", {})
            _new_temp = st.slider("Temperature", min_value=0.1, max_value=2.0, step=0.1, value=float(_cur_gen.get("temperature", 0.7)), key="prof_temperature")
            _new_top_p = st.slider("Top P", min_value=0.1, max_value=1.0, step=0.05, value=float(_cur_gen.get("top_p", 0.9)), key="prof_top_p")
            _new_rep = st.slider("Repetition Penalty", min_value=1.0, max_value=2.0, step=0.05, value=float(_cur_gen.get("repetition_penalty", 1.1)), key="prof_rep_penalty")

            if st.button("💾 Save Profile" if _ui_lang == "en" else "💾 プロファイルを保存", key="save_llm_profile"):
                _updated = {
                    "native_language": _new_native_lang,
                    "nsfw_tolerance": _new_nsfw,
                    "model_type": _new_model_type,
                    "max_tokens": _new_max_tokens,
                    "quirks": {
                        "json_capable": _new_json_capable,
                        "appends_meta_text": _new_appends_meta,
                        "outputs_url_in_prompt": _new_outputs_url,
                        "emotion_in_text": _new_emotion_in_text,
                    },
                    "generation_params": {
                        "temperature": _new_temp,
                        "top_p": _new_top_p,
                        "repetition_penalty": _new_rep,
                    },
                }
                _save_profile(_cur_model_for_params, _updated)
                st.toast(f"Saved: {_cur_model_for_params}" if _ui_lang == "en" else f"プロファイルを保存しました: {_cur_model_for_params}")
                st.rerun()

    st.divider()

    st.subheader(_t("settings_tts_backend"))
    tts_options = ["voicevox", "irodori", "kokoro", "gemini_tts"]
    tts_labels = {"voicevox": "VOICEVOX ENGINE" + ("" if _ui_lang == "en" else "(ローカル)"), "irodori": "Irodori-TTS" + ("" if _ui_lang == "en" else "(ローカル)"), "kokoro": "Kokoro TTS" + ("" if _ui_lang == "en" else "(ローカル)"), "gemini_tts": "Gemini API TTS"}
    _prev_tts = st.session_state.get("tts_backend", "voicevox")
    st.session_state.tts_backend = st.selectbox(
        _t("settings_tts_label"),
        tts_options,
        index=tts_options.index(_prev_tts)
        if _prev_tts in tts_options
        else 0,
        format_func=lambda k: tts_labels.get(k, k),
    )
    if st.session_state.tts_backend != _prev_tts:
        from def_kari.backends import stop_voicevox, stop_irodori
        if _prev_tts == "voicevox":
            stop_voicevox()
        elif _prev_tts == "irodori":
            stop_irodori()
        st.session_state._voicevox_start_attempted = False
        st.session_state._irodori_start_attempted = False
        st.rerun()
    @st.fragment(run_every=f"{st.session_state.get('status_poll_sec', DEFAULT_STATUS_POLL_SEC)}s")
    def _tts_status():
        if st.session_state.tts_backend == "voicevox":
            from def_kari.backends import is_voicevox_running, start_voicevox
            if is_voicevox_running():
                st.caption("✅ VOICEVOX running" if _ui_lang == "en" else "✅ VOICEVOX起動中")
            else:
                if not st.session_state.get("_voicevox_start_attempted"):
                    st.session_state._voicevox_start_attempted = True
                    start_voicevox()
                st.caption("⏳ Waiting for VOICEVOX..." if _ui_lang == "en" else "⏳ VOICEVOX起動待ち...")
        elif st.session_state.tts_backend == "irodori":
            from def_kari.backends import is_irodori_running, start_irodori
            if is_irodori_running():
                st.caption("✅ Irodori-TTS running" if _ui_lang == "en" else "✅ Irodori-TTS起動中")
            else:
                if not st.session_state.get("_irodori_start_attempted"):
                    st.session_state._irodori_start_attempted = True
                    start_irodori()
                st.caption("⏳ Waiting for Irodori-TTS..." if _ui_lang == "en" else "⏳ Irodori-TTS起動待ち...")
    _tts_status()

    st.divider()

    st.subheader(_t("settings_t2i_backend"))
    _prev_t2i_backend = st.session_state.get("t2i_backend", DEFAULT_T2I_BACKEND)
    st.session_state.t2i_backend = st.selectbox(
        _t("settings_t2i_label"),
        T2I_BACKENDS,
        index=T2I_BACKENDS.index(_prev_t2i_backend),
        format_func=lambda k: T2I_BACKEND_LABELS.get(k, k),
    )
    if st.session_state.t2i_backend != _prev_t2i_backend:
        st.session_state.t2i_model = None
        st.rerun()

    @st.fragment(run_every=f"{st.session_state.get('status_poll_sec', DEFAULT_STATUS_POLL_SEC)}s")
    def _t2i_status():
        if st.session_state.t2i_backend == "a1111":
            from def_kari.backends import is_a1111_running
            if is_a1111_running():
                st.caption("✅ A1111 running" if _ui_lang == "en" else "✅ A1111起動中")
            else:
                st.caption("⏳ Waiting for A1111..." if _ui_lang == "en" else "⏳ A1111起動待ち...")
    _t2i_status()

    if st.session_state.t2i_backend == "a1111":
        from def_kari.workers._t2i_generate import list_a1111_models, get_a1111_current_model
        _a1111_models = list_a1111_models()
        if _a1111_models:
            _cur_model = st.session_state.get("t2i_model") or get_a1111_current_model() or _a1111_models[0]
            _model_idx = _a1111_models.index(_cur_model) if _cur_model in _a1111_models else 0
            st.session_state.t2i_model = st.selectbox(
                "A1111 Checkpoint" if _ui_lang == "en" else "A1111 モデル(チェックポイント)",
                _a1111_models,
                index=_model_idx,
            )
        else:
            st.caption("⚠ A1111 not running or no models found." if _ui_lang == "en" else "⚠ A1111が起動していないか、モデルが見つかりません。")

    elif st.session_state.t2i_backend == "comfyui":
        from def_kari.workers._t2i_generate import list_comfyui_models, list_comfyui_workflows
        _comfy_models = list_comfyui_models()
        if _comfy_models:
            _cur_comfy = st.session_state.get("t2i_model") or _comfy_models[0]
            _comfy_idx = _comfy_models.index(_cur_comfy) if _cur_comfy in _comfy_models else 0
            st.session_state.t2i_model = st.selectbox("Model" if _ui_lang == "en" else "モデル", _comfy_models, index=_comfy_idx, key="comfyui_model")
            _wf_list = list_comfyui_workflows()
            if _wf_list:
                _cur_wf = st.session_state.get("comfyui_workflow", "default")
                if _cur_wf not in _wf_list:
                    _cur_wf = _wf_list[0]
                st.session_state.comfyui_workflow = st.selectbox("Workflow" if _ui_lang == "en" else "ワークフロー", _wf_list, index=_wf_list.index(_cur_wf), key="comfyui_wf_sel")
            st.caption("✅ ComfyUI running" if _ui_lang == "en" else "✅ ComfyUI起動中")
        else:
            st.warning("⚠ ComfyUI not running or no models found." if _ui_lang == "en" else "⚠ ComfyUIが起動していないか、モデルが見つかりません。")

    elif st.session_state.t2i_backend == "huggingface":
        _hf_key = os.environ.get("HF_TOKEN") or secrets_store.get_api_key("huggingface") or ""
        if _hf_key:
            st.caption("✅ HF token set" if _ui_lang == "en" else "✅ Hugging Face APIトークン設定済み")
        else:
            st.warning("⚠ HF token not set." if _ui_lang == "en" else "⚠ Hugging Face APIトークンが未設定です。「🔑 APIキー管理を開く」から設定してください。")
        _hf_models = [
            "black-forest-labs/FLUX.1-schnell",
            "stabilityai/stable-diffusion-xl-base-1.0",
            "stabilityai/stable-diffusion-2-1",
        ]
        _cur_hf_model = st.session_state.get("t2i_model") or _hf_models[0]
        if _cur_hf_model not in _hf_models:
            _hf_models.append(_cur_hf_model)
        _hf_idx = _hf_models.index(_cur_hf_model)
        st.session_state.t2i_model = st.selectbox("Model" if _ui_lang == "en" else "モデル", _hf_models, index=_hf_idx, key="hf_t2i_model")
        _custom_model = st.text_input("Custom Model ID" if _ui_lang == "en" else "カスタムモデルID", placeholder="例: user/model-name", key="hf_t2i_custom")
        if _custom_model:
            st.session_state.t2i_model = _custom_model

    elif st.session_state.t2i_backend == "civitai":
        _civitai_key = os.environ.get("CIVITAI_API_TOKEN") or secrets_store.get_api_key("civitai") or ""
        if _civitai_key:
            os.environ["CIVITAI_API_TOKEN"] = _civitai_key
            st.caption("✅ Civitai API key set" if _ui_lang == "en" else "✅ Civitai APIキー設定済み")
        else:
            st.warning("⚠ Civitai API key not set." if _ui_lang == "en" else "⚠ Civitai APIキーが未設定です。「🔑 APIキー管理を開く」から設定してください。")

        import json as _json
        import re as _re
        from pathlib import Path as _Path
        from urllib.parse import urlparse as _urlparse, parse_qs as _parse_qs
        import requests as _req

        _eco_map_path = _Path(__file__).parent.parent / "data" / "civitai_ecosystem_map.json"
        _ECOSYSTEM_MAP = {}
        if _eco_map_path.exists():
            try:
                _ECOSYSTEM_MAP = _json.loads(_eco_map_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        _CIVITAI_PRESETS_PATH = _Path(__file__).parent.parent / "data" / "civitai_models.json"

        def _load_presets():
            if _CIVITAI_PRESETS_PATH.exists():
                try:
                    return _json.loads(_CIVITAI_PRESETS_PATH.read_text(encoding="utf-8"))
                except Exception:
                    pass
            return []

        def _save_presets(presets):
            _CIVITAI_PRESETS_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CIVITAI_PRESETS_PATH.write_text(_json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8")

        _presets = _load_presets()
        _preset_labels = {p["label"]: p["model_air"] for p in _presets}
        _options = list(_preset_labels.keys())

        _cur_air = st.session_state.get("t2i_model") or ""
        _cur_label = next((p["label"] for p in _presets if p["model_air"] == _cur_air), None)

        _selected = st.selectbox(
            "Model" if _ui_lang == "en" else "モデル",
            _options if _options else [_t("unregistered")],
            index=_options.index(_cur_label) if _cur_label in _options else 0,
            disabled=not _options,
        )
        if _options and _selected != _t("unregistered"):
            st.session_state.t2i_model = _preset_labels[_selected]

        with st.expander(_t("model_management"), expanded=False):
            _civitai_url_input = st.text_input(
                "Civitai Model URL" if _ui_lang == "en" else "CivitaiモデルページURL",
                value="",
                placeholder="https://civitai.com/models/12345?modelVersionId=67890",
                key="civitai_url_input",
            )
            if _civitai_url_input and st.button("🔄 URL to AIR" if _ui_lang == "en" else "🔄 URLからAIRに変換"):
                try:
                    _parsed_url = _urlparse(_civitai_url_input)
                    _model_match = _re.search(r"/models/(\d+)", _parsed_url.path)
                    if not _model_match:
                        st.error("Cannot extract model ID from URL" if _ui_lang == "en" else "URLからモデルIDを取得できません。")
                    else:
                        _model_id = _model_match.group(1)
                        _version_id = _parse_qs(_parsed_url.query).get("modelVersionId", [None])[0]
                        if _version_id:
                            _vresp = _req.get(f"https://civitai.com/api/v1/model-versions/{_version_id}", timeout=15)
                            _vresp.raise_for_status()
                            _base_model = _vresp.json().get("baseModel", "")
                        else:
                            _mresp = _req.get(f"https://civitai.com/api/v1/models/{_model_id}", timeout=15)
                            _mresp.raise_for_status()
                            _versions = _mresp.json().get("modelVersions", [])
                            _version_id = str(_versions[0]["id"]) if _versions else None
                            _base_model = _versions[0].get("baseModel", "") if _versions else ""
                        if _version_id:
                            _eco = _ECOSYSTEM_MAP.get(_base_model.strip().lower())
                            if not _eco:
                                _eco = _re.sub(r"[^a-z0-9]", "", _base_model.lower()) or "sd1"
                            _air = f"urn:air:{_eco}:checkpoint:civitai:{_model_id}@{_version_id}"
                            st.session_state.t2i_model = _air
                            st.success(f"AIR: {_air} (baseModel: {_base_model})")
                except Exception as _e:
                    _ce = "Conversion error: " if _ui_lang == "en" else "変換エラー: "
                    st.error(f"{_ce}{_e}")

            _civitai_air = st.text_input(
                "AIR format (direct input)" if _ui_lang == "en" else "AIR形式（直接入力）",
                value=st.session_state.get("t2i_model") or "",
                placeholder="urn:air:<ecosystem>:checkpoint:civitai:<modelId>@<versionId>",
                key="civitai_air_input",
            )
            if _civitai_air:
                st.session_state.t2i_model = _civitai_air

            if _civitai_air and _civitai_air.startswith("urn:air:"):
                _matched = next((p for p in _presets if p["model_air"] == _civitai_air), None)
                if _matched:
                    if st.button(f"🗑 {_matched['label']}" + (" delete" if _ui_lang == "en" else " 削除")):
                        _presets = [p for p in _presets if p["label"] != _matched["label"]]
                        _save_presets(_presets)
                        st.toast("Deleted." if _ui_lang == "en" else "削除しました。")
                        st.rerun()
                else:
                    _new_label = st.text_input("Label" if _ui_lang == "en" else "登録名", placeholder="例: MiaoMiao / Illustrious v1.4", key="civitai_new_label")
                    if st.button("➕ Register" if _ui_lang == "en" else "➕ 登録"):
                        if not _new_label:
                            st.warning("Enter a name." if _ui_lang == "en" else "名前を入力してください。")
                        elif _new_label in _preset_labels:
                            st.warning("Name already exists." if _ui_lang == "en" else "同じ名前が既に登録されています。")
                        else:
                            _presets.append({"label": _new_label, "model_air": _civitai_air})
                            _save_presets(_presets)
                            st.toast(f"Registered: {_new_label}" if _ui_lang == "en" else f"「{_new_label}」を登録しました。")
                            st.rerun()

    st.subheader("T2I Image Size" if _ui_lang == "en" else "T2I画像サイズ")
    _col_w, _col_h = st.columns(2)
    with _col_w:
        st.session_state.t2i_width = st.number_input("Width" if _ui_lang == "en" else "幅", min_value=256, max_value=2048, value=st.session_state.get("t2i_width", 512), step=64)
    with _col_h:
        st.session_state.t2i_height = st.number_input("Height" if _ui_lang == "en" else "高さ", min_value=256, max_value=2048, value=st.session_state.get("t2i_height", 768), step=64)

    st.subheader("Quality Tags & Negative Prompt" if _ui_lang == "en" else "品質タグ・ネガティブプロンプト")
    from def_kari.models.t2i_profiles import get_quality_settings, save_quality_settings
    _cur_t2i_model = st.session_state.get("t2i_model")
    _cur_qt, _cur_neg = get_quality_settings(_cur_t2i_model)
    _new_qt = st.text_input("Quality Tags" if _ui_lang == "en" else "品質タグ(プロンプト末尾に付加)", value=_cur_qt)
    _new_neg = st.text_input("Negative Prompt" if _ui_lang == "en" else "ネガティブプロンプト", value=_cur_neg)
    if st.button("💾 Save Quality" if _ui_lang == "en" else "💾 品質設定を保存") and _cur_t2i_model:
        save_quality_settings(_cur_t2i_model, _new_qt, _new_neg)
        st.success(f"Quality saved: {_cur_t2i_model}" if _ui_lang == "en" else f"モデル {_cur_t2i_model} の品質設定を保存しました。")
    if not _cur_t2i_model:
        st.caption("Default values used when no model selected." if _ui_lang == "en" else "モデルが選択されていない場合、デフォルト値が使用されます。")

    st.divider()

    st.subheader("T2I Prompt Format" if _ui_lang == "en" else "T2Iモデル プロンプト記法")
    st.session_state.t2i_prompt_format = st.selectbox(
        _t("settings_t2i_prompt_format"),
        T2I_PROMPT_FORMATS,
        index=T2I_PROMPT_FORMATS.index(st.session_state.get("t2i_prompt_format", DEFAULT_T2I_PROMPT_FORMAT)),
        format_func=lambda k: T2I_PROMPT_FORMAT_LABELS.get(k, k),
        help=("natural: For natural language models (Flux etc).\ndanbooru: For tag-based models (Illustrious etc)." if _ui_lang == "en" else "natural: Flux等の自然言語対応モデル向け。\ndanbooru: Illustrious等のタグ形式モデル向け。"),
    )

    st.subheader(_t("settings_c2_method"))
    c2_options = ["none", "argos", "library", "deepl", "llm"]
    c2_labels = {
        "none": "Off" if _ui_lang == "en" else "利用しない",
        "argos": "Argos (Offline)" if _ui_lang == "en" else "Argos Translate(オフライン)",
        "library": "Google Translate (Free)" if _ui_lang == "en" else "Google翻訳(無料)",
        "deepl": "DeepL API" if _ui_lang == "en" else "DeepL API(高品質)",
        "llm": "LLM Translation" if _ui_lang == "en" else "LLM翻訳(TGW/Ollama等で英訳)",
    }
    st.session_state.c2_method = st.radio(
        "C2: Translate dialogue to image tags" if _ui_lang == "en" else "C2方式: 対話テキストを翻訳して画像タグに変換",
        c2_options,
        index=c2_options.index(st.session_state.c2_method)
        if st.session_state.c2_method in c2_options
        else 0,
        format_func=lambda k: c2_labels.get(k, k),
        horizontal=True,
    )
    if st.session_state.c2_method == "deepl":
        _deepl_key = os.environ.get("DEEPL_API_KEY") or secrets_store.get_api_key("deepl") or st.session_state.get("deepl_api_key", "")
        if _deepl_key:
            st.session_state.deepl_api_key = _deepl_key
            st.caption("✅ DeepL API key set" if _ui_lang == "en" else "✅ DeepL APIキー設定済み")
        else:
            st.warning("⚠ DeepL API key not set." if _ui_lang == "en" else "⚠ DeepL APIキーが未設定です。「🔑 APIキー管理を開く」から設定してください。")

    st.session_state.emotion_tag_enabled = st.checkbox(
        _t("settings_emotion_tag"),
        value=st.session_state.get("emotion_tag_enabled", True),
    )

    st.divider()
    st.subheader("Chat Mode" if _ui_lang == "en" else "チャットモード")
    st.checkbox(
        _t("char_greeting"),
        value=st.session_state.get("character_greeting", True),
        key="character_greeting",
    )
    st.number_input(
        "Max undo history" if _ui_lang == "en" else "元に戻す(undo)の最大保持件数",
        min_value=1,
        max_value=10,
        value=st.session_state.get("undo_max_history", 5),
        key="undo_max_history",
    )

    st.divider()
    st.subheader(_t("settings_session_mode"))
    st.slider(
        _t("settings_actions_per_turn"),
        min_value=1, max_value=5,
        key="session_actions_per_turn",
    )
    st.slider(
        _t("settings_repeat_penalty"),
        min_value=0, max_value=10,
        key="session_repeat_penalty_count",
    )

    st.caption(_t("settings_session_img_size"))
    col_sw, col_sh = st.columns(2)
    with col_sw:
        st.number_input("Width" if _ui_lang == "en" else "幅", min_value=128, max_value=2048, step=64, key="session_t2i_width")
    with col_sh:
        st.number_input("Height" if _ui_lang == "en" else "高さ", min_value=128, max_value=2048, step=64, key="session_t2i_height")

    _ad_sets = _load_action_directives()
    _ad_keys = list(_ad_sets.keys())
    _ad_labels = {k: _ad_sets[k].get("label", k) for k in _ad_keys}
    if st.session_state.get("session_action_directive_set") not in _ad_keys:
        st.session_state.session_action_directive_set = _ad_keys[0]
    st.selectbox(
        _t("session_action_directive") if False else "Action Directives" if _ui_lang == "en" else "アクション方向性指示",
        _ad_keys,
        format_func=lambda k: _ad_labels.get(k, k),
        key="session_action_directive_set",
    )

    st.divider()
    st.subheader("Episode Mode" if _ui_lang == "en" else "エピソードモード")
    st.slider(
        "Candidates" if _ui_lang == "en" else "生成候補数",
        min_value=1, max_value=5, value=st.session_state.get("episode_candidate_count", 3),
        key="episode_candidate_count",
    )
    st.caption("Illustration Size" if _ui_lang == "en" else "挿絵サイズ")
    col_ew, col_eh = st.columns(2)
    with col_ew:
        st.number_input("Width" if _ui_lang == "en" else "幅", min_value=128, max_value=2048, step=64, value=st.session_state.get("episode_t2i_width", 1216), key="episode_t2i_width")
    with col_eh:
        st.number_input("Height" if _ui_lang == "en" else "高さ", min_value=128, max_value=2048, step=64, value=st.session_state.get("episode_t2i_height", 832), key="episode_t2i_height")

    st.divider()
    st.subheader(_t("settings_apikey"))
    if st.button(_t("settings_apikey_open")):
        _render_api_key_dialog()

    st.divider()
    if st.button(_t("settings_save")):
        save_settings(st.session_state)
        st.success(_t("settings_saved"))


@st.fragment(run_every=f"{st.session_state.interval_ms}ms")
def _poll_events():
    events = drain_events(result_q)

    if st.session_state.t2i_trigger_mode == T2I_MODE_INTERVAL:
        now = time.time()
        if now - st.session_state.last_interval_image_time >= IMAGE_INTERVAL_SEC:
            for m in st.session_state.history:
                if not m.get("image_queued") and not m.get("image_path"):
                    task_q.put({
                        "kind": "image",
                        "msg_id": m["id"],
                        "emotion": m.get("emotion", "neutral"),
                        "image_prompt_en": m.get("image_prompt_en", ""),
                        "t2i_backend": st.session_state.t2i_backend,
                        "t2i_model": st.session_state.t2i_model,
                        "t2i_width": st.session_state.t2i_width,
                        "t2i_height": st.session_state.t2i_height,
                    })
                    m["image_queued"] = True
                    st.session_state.last_interval_image_time = now
                    break

    if not events:
        if st.session_state.interval_ms != IDLE_POLL_MS:
            st.session_state.interval_ms = IDLE_POLL_MS
        return

    for event in events:
        apply_event(event, st.session_state.history)

    all_done = all(
        m.get("state") in ("Persist", "TTS Completed")
        for m in st.session_state.history
    )
    if all_done:
        for m in st.session_state.history:
            if m.get("state") == "TTS Completed" and not m.get("image_queued"):
                m["state"] = "Persist"

    save_session(st.session_state.history, st.session_state.active_character)
    st.session_state.history = trim_session(st.session_state.history)
    st.rerun()


_poll_events()
