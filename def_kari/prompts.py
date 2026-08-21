"""セッション系プロンプトテキストの外出し先(data/session_prompts.json)。

`{key: {"ja": "...", "en": "..."}}`形式、`{placeholder}`は呼び出し側で
`.format(**kwargs)`する。元は`api/routes/session_lobby.py`にあったが、
`gm/`パッケージ(api/routes/へ依存しない層)からも使うため中立な場所へ移設
(2026-08-21、gm_agent.py§2-4対応)。`session_lobby.py`は同名のエイリアスで
再exportしており、既存の呼び出し箇所(session_voting.py・session.py)は無改修。
"""

import json
from pathlib import Path

_BASE_DATA = Path(__file__).parent.parent / "data"
_SESSION_PROMPTS_PATH = _BASE_DATA / "session_prompts.json"
_session_prompts_cache: dict = {}


def load_session_prompts() -> dict:
    global _session_prompts_cache
    if _session_prompts_cache:
        return _session_prompts_cache
    try:
        with open(_SESSION_PROMPTS_PATH, encoding="utf-8") as f:
            _session_prompts_cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return _session_prompts_cache


def sp(key: str, lang: str) -> str:
    """session_prompts.json から言語別テキストを取得。"""
    entry = load_session_prompts().get(key, {})
    return entry.get(lang) or entry.get("ja") or ""
