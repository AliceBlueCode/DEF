"""サイドバー: レーティング設定、セーフティ強度切替(F-8)、TTS設定(F-11)、T2Iトリガー(F-15)、状態表示"""

import streamlit as st

from def_kari.config import T2I_MODES, T2I_MODE_LABELS, DEFAULT_STATUS_POLL_SEC
from def_kari.i18n import t
from def_kari.safety.filters import SAFETY_LEVELS

_SEXUAL_STRENGTH = {
    "general_only": {"label": "全年齢", "allowed": ["general"]},
    "r15": {"label": "R15", "allowed": ["general", "sfw"]},
    "r18": {"label": "R18", "allowed": ["general", "sfw", "nsfw"]},
    "unlimited": {"label": "無制限", "allowed": ["general", "sfw", "nsfw", "hentai"]},
}

_VIOLENCE_STRENGTH = {
    "general_only": {"label": "全年齢", "allowed": ["general"]},
    "action": {"label": "アクション", "allowed": ["general", "violence"]},
    "horror": {"label": "ホラー", "allowed": ["general", "violence", "gore"]},
    "unlimited": {"label": "無制限", "allowed": ["general", "violence", "gore", "extreme"]},
}


def render_sidebar() -> None:
    with st.sidebar:
        _lang = st.session_state.get("user_language", "ja")
        _t = lambda key: t(key, lang=_lang)

        SAFETY_LABELS = {
            "off": _t("sidebar_safety_off"),
            "warn": _t("sidebar_safety_warn"),
            "mask": _t("sidebar_safety_mask"),
        }


        with st.expander(_t("sidebar_rating"), expanded=False):
            st.caption(_t("sidebar_rating_desc"))

            _sexual_keys = list(_SEXUAL_STRENGTH.keys())
            _cur_sexual = st.session_state.get("rating_sexual_strength", "general_only")
            if _cur_sexual not in _sexual_keys:
                _cur_sexual = "general_only"
            _sexual_labels = {
                "general_only": _t("general"),
                "r15": _t("r15"),
                "r18": _t("r18"),
                "unlimited": _t("unlimited"),
            }
            st.markdown(f"**{_t('sidebar_rating_sexual')}**")
            _new_sexual = st.radio(
                _t("sidebar_rating_sexual"),
                _sexual_keys,
                index=_sexual_keys.index(_cur_sexual),
                format_func=lambda k: _sexual_labels.get(k, k),
                horizontal=True,
                key="rating_sexual_radio",
                label_visibility="collapsed",
            )
            st.session_state.rating_sexual_strength = _new_sexual
            st.session_state.allowed_rating_sexual = _SEXUAL_STRENGTH[_new_sexual]["allowed"]

            _violence_keys = list(_VIOLENCE_STRENGTH.keys())
            _cur_violence = st.session_state.get("rating_violence_strength", "general_only")
            if _cur_violence not in _violence_keys:
                _cur_violence = "general_only"
            _violence_labels = {
                "general_only": _t("general"),
                "action": _t("action_mode"),
                "horror": _t("horror_mode"),
                "unlimited": _t("unlimited"),
            }
            st.markdown(f"**{_t('sidebar_rating_violence')}**")
            _new_violence = st.radio(
                _t("sidebar_rating_violence"),
                _violence_keys,
                index=_violence_keys.index(_cur_violence),
                format_func=lambda k: _violence_labels.get(k, k),
                horizontal=True,
                key="rating_violence_radio",
                label_visibility="collapsed",
            )
            st.session_state.rating_violence_strength = _new_violence
            st.session_state.allowed_rating_violence = _VIOLENCE_STRENGTH[_new_violence]["allowed"]

        st.subheader(_t("sidebar_safety"))
        _prev_safety = st.session_state.get("safety_level", "warn")
        st.session_state.safety_level = st.radio(
            _t("sidebar_safety"),
            SAFETY_LEVELS,
            index=SAFETY_LEVELS.index(_prev_safety),
            format_func=lambda k: SAFETY_LABELS.get(k, k),
            horizontal=True,
            label_visibility="collapsed",
        )
        if st.session_state.safety_level != _prev_safety:
            for m in st.session_state.get("history", []):
                m["audio_autoplayed"] = True

        _override_tags_options = ["nsfw", "hentai", "violence", "gore", "extreme", "sfw"]
        col_ovr_cb, col_ovr_sel = st.columns([1, 2])
        with col_ovr_cb:
            st.session_state.force_rating_override = st.checkbox(
                _t("sidebar_force_rating"),
                value=st.session_state.get("force_rating_override", False),
            )
        with col_ovr_sel:
            st.session_state.force_rating_tag = st.selectbox(
                "強制レーティング",
                _override_tags_options,
                index=_override_tags_options.index(st.session_state.get("force_rating_tag", "nsfw")),
                label_visibility="collapsed",
                disabled=not st.session_state.get("force_rating_override", False),
            )

        st.subheader(_t("sidebar_tts"))
        st.session_state.tts_enabled = st.checkbox(
            _t("sidebar_tts_enable"),
            value=st.session_state.get("tts_enabled", True),
        )
        st.session_state.tts_human_enabled = st.checkbox(
            _t("sidebar_tts_human"),
            value=st.session_state.get("tts_human_enabled", False),
        )

        st.subheader(_t("sidebar_t2i_trigger"))
        _t2i_mode_labels = {
            "end": _t("t2i_mode_end"),
            "start": _t("t2i_mode_start"),
            "manual": _t("t2i_mode_manual"),
            "interval": _t("t2i_mode_interval"),
        }
        st.session_state.t2i_trigger_mode = st.radio(
            _t("sidebar_t2i_trigger"),
            T2I_MODES,
            index=T2I_MODES.index(st.session_state.get("t2i_trigger_mode", T2I_MODES[0])),
            format_func=lambda k: _t2i_mode_labels.get(k, k),
            label_visibility="collapsed",
        )

        col_poll_label, col_poll_input, col_poll_unit = st.columns([3, 1, 0.5])
        with col_poll_label:
            st.caption(_t("sidebar_poll_interval"))
        with col_poll_input:
            st.session_state.status_poll_sec = st.number_input(
                "sec",
                min_value=1,
                max_value=60,
                value=st.session_state.get("status_poll_sec", DEFAULT_STATUS_POLL_SEC),
                key="status_poll_input",
                label_visibility="collapsed",
            )
        with col_poll_unit:
            st.caption("秒")

        vram_lock = st.session_state.get("_vram_lock")
        if vram_lock:
            if vram_lock.locked():
                st.warning("⚡ vram_lock保持中 (T2I実行中)")
            else:
                st.caption("✅ vram_lock: 解放中")

        st.divider()
        from def_kari import __version__
        st.caption(f"DEF(kari) v{__version__}")
