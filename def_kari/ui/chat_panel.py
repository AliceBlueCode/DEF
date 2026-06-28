"""チャット履歴描画・再生成・手動画像生成ボタン"""

import copy
import os
from pathlib import Path

import streamlit as st
from PIL import Image, ImageFilter

_ICON_BASES = [
    Path(__file__).parent.parent.parent / "data" / "public" / "characters",
    Path(__file__).parent.parent.parent / "data" / "private" / "characters",
]


def _get_avatar(character_id: str) -> str:
    for _base in _ICON_BASES:
        icon = _base / character_id / "icon.png"
        if icon.exists():
            return str(icon)
    return "🤖"

from def_kari.config import LOAD_BATCH, ACTIVE_POLL_MS, DEFAULT_UNDO_MAX_HISTORY
from def_kari.i18n import t
from def_kari.safety.filters import (
    effective_level,
    is_flagged,
    should_blur_image,
    should_hide_audio,
    should_hide_image,
    should_mask_text,
    should_autoplay_audio,
)
from def_kari.history.store import lazy_load_more


def _get_blurred_path(image_path: str) -> str:
    base, ext = os.path.splitext(image_path)
    blurred_path = f"{base}_blurred{ext}"
    if os.path.exists(blurred_path):
        return blurred_path
    try:
        img = Image.open(image_path)
        blurred = img.filter(ImageFilter.GaussianBlur(radius=20))
        blurred.save(blurred_path)
        return blurred_path
    except Exception:
        return image_path


def _snapshot(msg: dict) -> dict:
    return copy.deepcopy({k: v for k, v in msg.items() if k not in ("_undo_stack", "_redo_stack")})


def _push_undo(msg: dict) -> None:
    stack = msg.setdefault("_undo_stack", [])
    stack.append(_snapshot(msg))
    max_history = st.session_state.get("undo_max_history", DEFAULT_UNDO_MAX_HISTORY)
    if len(stack) > max_history:
        del stack[:len(stack) - 5]
    msg["_redo_stack"] = []


def _regenerate_audio(msg: dict, task_q) -> None:
    _push_undo(msg)
    msg["audio_path"] = None
    msg["audio_error"] = None
    msg["audio_autoplayed"] = False
    if st.session_state.get("tts_enabled", True):
        from def_kari.characters import get_character, apply_name_reading, get_tts_speaker_id
        _char = get_character(st.session_state.get("active_character"))
        _backend = st.session_state.get("tts_backend", "voicevox")
        task_q.put({
            "kind": "tts",
            "msg_id": msg["id"],
            "emotion": msg["emotion"],
            "text": apply_name_reading(msg["text"], _char),
            "tts_backend": _backend,
            "tts_speaker_id": get_tts_speaker_id(_char, _backend),
        })
        msg["state"] = "TTS Running"
    st.session_state.interval_ms = ACTIVE_POLL_MS


def _regenerate_image(msg: dict, task_q) -> None:
    _push_undo(msg)
    msg["image_path"] = None
    msg["image_queued"] = True
    msg["image_error"] = None
    if msg.get("state") == "Persist":
        msg["state"] = "TTS Completed"
    task_q.put({
        "kind": "image",
        "msg_id": msg["id"],
        "emotion": msg.get("emotion", "neutral"),
        "image_prompt_en": msg.get("image_prompt_en", ""),
        "t2i_backend": st.session_state.get("t2i_backend", "a1111"),
        "t2i_model": st.session_state.get("t2i_model"),
        "t2i_width": st.session_state.get("t2i_width", 512),
        "t2i_height": st.session_state.get("t2i_height", 768),
    })
    st.session_state.interval_ms = ACTIVE_POLL_MS


def _regenerate_turn(msg: dict, task_q) -> None:
    _push_undo(msg)

    try:
        from def_kari.llm.client import generate_structured_reply
        from def_kari.llm.backend import DEFAULT_LLM_BACKEND, LLM_BACKENDS
        from def_kari.models.registry import get_quirks
        from def_kari.llm.tgw_manager import get_loaded_model_name
        from def_kari.characters import get_character, apply_name_reading, get_tts_speaker_id

        _backend = st.session_state.get("llm_backend", DEFAULT_LLM_BACKEND)
        if _backend == "textgen_webui":
            _model_name = get_loaded_model_name() or ""
        else:
            _model_name = st.session_state.get("llm_ext_model") or LLM_BACKENDS[_backend]["default_model"]
        _quirks = get_quirks(_model_name)
        _character = get_character(st.session_state.get("active_character"))

        history_before = [
            m for m in st.session_state.get("history", [])
            if m["id"] != msg["id"]
        ]

        result = generate_structured_reply(
            msg["user_text"],
            history=history_before,
            model=_model_name,
            character=_character,
            backend=_backend,
            quirks=_quirks,
        )

        if result["success"] and result["result"]:
            r = result["result"]
            msg["text"] = r["dialogue"]
            msg["emotion"] = r["emotion"]
            msg["image_prompt_en"] = r["image_prompt_en"]
            msg["tags"] = r["tags"]
            if not msg["tags"]:
                from def_kari.safety.filters import detect_tags_from_text
                msg["tags"] = detect_tags_from_text(msg["user_text"] + " " + r["dialogue"])
        else:
            _err_detail = ""
            if result.get("attempts"):
                for a in result["attempts"]:
                    for e in a.get("errors", []):
                        _err_detail += f"\n{e}"
            msg["text"] = f"(再生成に失敗しました: {_err_detail.strip() or '不明なエラー'})"
            msg["emotion"] = "neutral"

        msg["llm_success"] = result["success"]
        msg["llm_attempts"] = result["attempts"]
    except Exception as _regen_err:
        msg["text"] = f"(再生成エラー: {_regen_err})"
        msg["emotion"] = "neutral"
        msg["llm_success"] = False
        msg["llm_attempts"] = [{"stage": "再生成エラー", "raw": "", "errors": [str(_regen_err)]}]
    msg.pop("safety_unlocked", None)

    msg["audio_path"] = None
    msg["audio_error"] = None
    msg["audio_autoplayed"] = False
    if st.session_state.get("tts_enabled", True):
        _backend = st.session_state.get("tts_backend", "voicevox")
        task_q.put({
            "kind": "tts",
            "msg_id": msg["id"],
            "emotion": msg["emotion"],
            "text": apply_name_reading(msg["text"], _character),
            "tts_backend": _backend,
            "tts_speaker_id": get_tts_speaker_id(_character, _backend),
        })
        msg["state"] = "TTS Running"

    msg["image_path"] = None
    msg["image_queued"] = True
    msg["image_error"] = None
    task_q.put({
        "kind": "image",
        "msg_id": msg["id"],
        "emotion": msg.get("emotion", "neutral"),
        "image_prompt_en": msg.get("image_prompt_en", ""),
        "t2i_backend": st.session_state.get("t2i_backend", "a1111"),
        "t2i_model": st.session_state.get("t2i_model"),
        "t2i_width": st.session_state.get("t2i_width", 512),
        "t2i_height": st.session_state.get("t2i_height", 768),
    })
    st.session_state.interval_ms = ACTIVE_POLL_MS


def _undo(msg: dict) -> None:
    undo_stack = msg.get("_undo_stack") or []
    if not undo_stack:
        return
    redo_stack = msg.setdefault("_redo_stack", [])
    redo_stack.append(_snapshot(msg))
    prev = undo_stack.pop()
    msg.clear()
    msg.update(prev)
    msg["_undo_stack"] = undo_stack
    msg["_redo_stack"] = redo_stack
    st.session_state.interval_ms = ACTIVE_POLL_MS


def _redo(msg: dict) -> None:
    redo_stack = msg.get("_redo_stack") or []
    if not redo_stack:
        return
    undo_stack = msg.setdefault("_undo_stack", [])
    undo_stack.append(_snapshot(msg))
    nxt = redo_stack.pop()
    msg.clear()
    msg.update(nxt)
    msg["_undo_stack"] = undo_stack
    msg["_redo_stack"] = redo_stack
    st.session_state.interval_ms = ACTIVE_POLL_MS


def _delete_turn(msg: dict) -> None:
    from def_kari.history.store import save_session
    st.session_state.history = [
        m for m in st.session_state.history if m["id"] != msg["id"]
    ]
    save_session(st.session_state.history, st.session_state.get("active_character", "character_luna_001"))


def render_chat_panel(task_q) -> None:
    _lang = st.session_state.get("user_language", "ja")
    _t = lambda key: t(key, lang=_lang)
    history = st.session_state.get("history", [])
    global_level = st.session_state.get("safety_level", "warn")

    if st.button(_t("chat_load_more")):
        char_id = st.session_state.get("active_character", "character_luna_001")
        st.session_state.history = lazy_load_more(history, LOAD_BATCH, char_id)
        for m in st.session_state.history:
            m.setdefault("llm_attempts", [])
        st.rerun()

    for msg in history:
        tags = msg.get("tags") or []
        flagged = is_flagged(
            tags,
            allowed_sexual=st.session_state.get("allowed_rating_sexual"),
            allowed_violence=st.session_state.get("allowed_rating_violence"),
        )
        tag_str = ", ".join(tags) or "なし"

        with st.chat_message("user"):
            st.write(msg.get("user_text", ""))

        _char_id = msg.get("sender") or st.session_state.get("active_character", "")
        with st.chat_message("assistant", avatar=_get_avatar(_char_id)):
            if flagged:
                unlocked = st.toggle(
                    _t("chat_unlock_safety"),
                    value=msg.get("safety_unlocked", False),
                    key=f"unlock_{msg['id']}",
                )
                msg["safety_unlocked"] = unlocked

            eff = effective_level(global_level, flagged, msg.get("safety_unlocked", False))

            if should_mask_text(eff):
                st.write(_t("safety_masked"))
            else:
                st.write(msg.get("text", ""))
                if flagged and eff == "warn":
                    st.warning(f"⚠ safety tags: {tag_str}")

            st.caption(
                f"emotion: {msg.get('emotion', 'neutral')} / "
                f"state: {msg.get('state', '?')} / "
                f"safety tags: {tag_str}"
            )

            if msg.get("audio_path"):
                if should_hide_audio(eff):
                    st.caption(_t("safety_audio_hidden"))
                else:
                    autoplay = should_autoplay_audio(eff) and not msg.get("audio_autoplayed")
                    st.audio(msg["audio_path"], autoplay=autoplay)
                    if autoplay:
                        msg["audio_autoplayed"] = True
            elif not msg.get("audio_enabled", True):
                st.caption(_t("chat_audio_disabled"))
            elif msg.get("state") not in ("Persist", None):
                st.caption(_t("chat_audio_generating"))

            if msg.get("image_path"):
                if should_hide_image(eff):
                    st.caption(_t("safety_image_hidden"))
                elif should_blur_image(eff):
                    blurred = _get_blurred_path(msg["image_path"])
                    st.image(blurred, width=200)
                    st.caption(_t("chat_image_blurred"))
                else:
                    _filename = os.path.basename(msg["image_path"])
                    _static_url = f"/app/static/{_filename}"
                    st.markdown(
                        f'<a href="{_static_url}" target="_blank">'
                        f'<img src="{_static_url}" width="200" style="cursor:pointer; border-radius:4px;">'
                        f'</a>',
                        unsafe_allow_html=True,
                    )
            elif msg.get("image_queued") and msg.get("state") != "Persist":
                st.caption(_t("chat_image_generating"))

            if msg.get("image_error"):
                st.error(f"画像生成に失敗しました: {msg['image_error']}")

            # 再生成・undo/redo・削除ボタン
            undo_stack = msg.get("_undo_stack") or []
            redo_stack = msg.get("_redo_stack") or []
            extra = (1 if undo_stack else 0) + (1 if redo_stack else 0)
            cols = st.columns(3 + extra + 1)
            col_idx = 0
            with cols[col_idx]:
                if st.button(_t("chat_regen_cycle"), key=f"regen_turn_{msg['id']}"):
                    _regenerate_turn(msg, task_q)
                    st.rerun()
            col_idx += 1
            with cols[col_idx]:
                if st.button(_t("chat_regen_audio"), key=f"regen_audio_{msg['id']}"):
                    _regenerate_audio(msg, task_q)
                    st.rerun()
            col_idx += 1
            with cols[col_idx]:
                if st.button(_t("chat_regen_image"), key=f"regen_image_{msg['id']}"):
                    _regenerate_image(msg, task_q)
                    st.rerun()
            col_idx += 1
            if undo_stack:
                with cols[col_idx]:
                    if st.button(f"↩️ 戻す ({len(undo_stack)})", key=f"undo_{msg['id']}"):
                        _undo(msg)
                        st.rerun()
                col_idx += 1
            if redo_stack:
                with cols[col_idx]:
                    if st.button(f"↪️ やり直す ({len(redo_stack)})", key=f"redo_{msg['id']}"):
                        _redo(msg)
                        st.rerun()
                col_idx += 1
            with cols[-1]:
                if st.button(_t("chat_delete"), key=f"delete_{msg['id']}"):
                    _delete_turn(msg)
                    st.rerun()
