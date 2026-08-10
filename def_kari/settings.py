"""設定の永続化(data/settings.json)"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
SETTINGS_PATH = DATA_DIR / "mvp_settings.json"

PERSISTED_KEYS = [
    "safety_level",
    "tts_enabled",
    "tts_human_enabled",
    "tts_backend",
    "llm_backend",
    "tgw_autoload_model",
    "c2_method",
    "active_character",
    "t2i_trigger_mode",
    "t2i_prompt_mode",
    "undo_max_history",
    "character_greeting",
    "t2i_prompt_format",
    "t2i_backend",
    "t2i_model",
    "t2i_model_a1111",
    "t2i_model_comfyui",
    "t2i_model_civitai",
    "t2i_model_huggingface",
    "t2i_width",
    "t2i_height",
    "llm_ext_model",
    "llm_ext_model_openai",
    "llm_ext_model_gemini",
    "llm_ext_model_anthropic",
    "llm_ext_model_ollama",
    "status_poll_sec",
    "session_actions_per_turn",
    "session_action_directive_set",
    "session_repeat_penalty_count",
    "user_language",
    "emotion_tag_enabled",
    "rating_sexual_strength",
    "rating_violence_strength",
    "allowed_rating_sexual",
    "allowed_rating_violence",
    "comfyui_workflow",
    "session_t2i_width",
    "session_t2i_height",
    "session_rule_set",
    "episode_candidate_count",
    "episode_t2i_width",
    "episode_t2i_height",
    "vote_force_approve",
    "keeper_judgment_mode",
    "tts_voicevox_cpu_mode",
    "jwt_secret",
    "disconnect_timeout_sec",
    "session_daily_generation_limit",
    "session_auto_illustrate",
]


def load_settings() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_PATH.exists():
        return {}
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_jwt_secret(secret: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    current: dict = {}
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                current = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    current["jwt_secret"] = secret
    tmp = str(SETTINGS_PATH) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    import os as _os
    _os.replace(tmp, str(SETTINGS_PATH))


def get_jwt_secret() -> str:
    """JWT秘密鍵を返す。未設定なら自動生成してsettings.jsonに保存する。"""
    import secrets as _secrets
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    current: dict = {}
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                current = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    if current.get("jwt_secret"):
        return current["jwt_secret"]
    new_secret = _secrets.token_hex(32)
    _write_jwt_secret(new_secret)
    return new_secret


def regenerate_jwt_secret() -> str:
    """JWT秘密鍵を強制的に再生成する（設定タブからの手動再生成用）。

    get_jwt_secret() と異なり、既存値の有無に関わらず新しい値で上書きする。
    再生成前に発行された全JWTは新しい鍵で検証できなくなり無効になる。
    呼び出し元（APIルート側）で全WS接続を強制切断すること。
    """
    import secrets as _secrets
    new_secret = _secrets.token_hex(32)
    _write_jwt_secret(new_secret)
    return new_secret


def save_settings(session_state) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings = {}
    for key in PERSISTED_KEYS:
        if key in session_state:
            val = session_state[key]
            if val == "None":
                val = None
            settings[key] = val
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
