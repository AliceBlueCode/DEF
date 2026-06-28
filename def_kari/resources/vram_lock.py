"""F-13-1: vram_lockシングルトン(基本設計5.3節)"""

import threading

import streamlit as st


@st.cache_resource
def get_vram_lock() -> threading.Lock:
    return threading.Lock()
