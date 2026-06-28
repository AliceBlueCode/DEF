"""F-2: Queue/Threadシングルトン管理(基本設計3.3節)"""

import queue

import streamlit as st


@st.cache_resource
def get_queues() -> tuple[queue.Queue, queue.Queue]:
    """task_q(タスク投入用)とresult_q(完了通知用)のシングルトンペアを返す。"""
    return queue.Queue(), queue.Queue()
