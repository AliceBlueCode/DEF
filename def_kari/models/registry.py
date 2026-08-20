"""F-5: モデル特性数値マスタのローダー(基本設計5.1節)

LLMモデルプロファイルはdata/llm_profiles/に1モデル1ファイルで管理する。
旧一括ファイル(data/llm_model_profiles.json, poc/data/llm_model_profiles.json)はフォールバックとして読み込む。
"""

import json
from pathlib import Path

_MASTER_PATH = Path(__file__).parent / "model_master.json"
_LLM_PROFILES_DIR = Path(__file__).parent.parent.parent / "data" / "llm_profiles"
_LLM_PROFILES_PATH = Path(__file__).parent.parent.parent / "data" / "llm_model_profiles.json"
_POC_LLM_PROFILES_PATH = Path(__file__).parent.parent.parent / "poc" / "data" / "llm_model_profiles.json"

MODEL_TYPES = ("chat", "novel", "instruct")
DEFAULT_MODEL_TYPE = "chat"

DEFAULT_QUIRKS = {
    "json_capable": True,
    "appends_meta_text": False,
    "outputs_url_in_prompt": False,
    "emotion_in_text": False,
    "leaks_thinking": False,
    # tool-calling(OpenAI互換のtools/tool_choice)に対応しているモデルか。
    # 未知のモデルは非対応として扱う(安全側デフォルト)。対応可否はモデル
    # 依存のため自動判定はせず、data/llm_profiles/配下で手動記録する運用
    # （gm/judgment_planner.pyが判定決定の経路選択に使う）。
    "tool_calling_capable": False,
}

_DEFAULT_PROFILE_TEMPLATE = {
    "native_language": "en",
    "nsfw_tolerance": "sfw",
    "model_type": "chat",
    "context_length": 8192,
    "max_tokens": 1024,
    "quirks": None,  # filled at creation time
    "generation_params": {},
}


def load_model_master() -> dict:
    return json.loads(_MASTER_PATH.read_text(encoding="utf-8"))


def _load_llm_profiles() -> dict:
    profiles = {}
    # 個別ファイル（data/llm_profiles/*.json）を優先読み込み
    if _LLM_PROFILES_DIR.exists():
        for path in sorted(_LLM_PROFILES_DIR.glob("*.json")):
            try:
                with open(path, encoding="utf-8") as f:
                    profiles.update(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass
    # フォールバック: 旧一括ファイル
    if not profiles:
        for path in (_LLM_PROFILES_PATH, _POC_LLM_PROFILES_PATH):
            if path.exists():
                try:
                    with open(path, encoding="utf-8") as f:
                        profiles.update(json.load(f))
                except (json.JSONDecodeError, OSError):
                    pass
    return profiles


def get_llm_profile(model_name: str) -> dict:
    profiles = _load_llm_profiles()
    return profiles.get(model_name, {})


def get_or_create_llm_profile(model_name: str) -> dict:
    """プロファイルが存在しなければデフォルト値で生成・保存して返す。"""
    profiles = _load_llm_profiles()
    if model_name in profiles:
        return profiles[model_name]
    profile = {k: v for k, v in _DEFAULT_PROFILE_TEMPLATE.items()}
    profile["quirks"] = dict(DEFAULT_QUIRKS)
    _save_profile(model_name, profile)
    return profile


def get_prompt_language(model_id: str, master: dict | None = None) -> str:
    master = master or load_model_master()
    entry = master.get(model_id, {})
    return entry.get("prompt_language", "en")


def get_model_type(model_name: str) -> str:
    profile = get_llm_profile(model_name)
    return profile.get("model_type", DEFAULT_MODEL_TYPE)


def get_max_tokens(model_name: str, default: int = 512) -> int:
    profile = get_llm_profile(model_name)
    return profile.get("max_tokens", default)


def get_quirks(model_name: str) -> dict:
    profile = get_llm_profile(model_name)
    quirks = dict(DEFAULT_QUIRKS)
    quirks.update(profile.get("quirks", {}))
    if not profile.get("quirks"):
        model_type = profile.get("model_type", DEFAULT_MODEL_TYPE)
        if model_type == "novel":
            quirks["json_capable"] = False
            quirks["appends_meta_text"] = True
    return quirks


def _save_profile(model_name: str, profile: dict) -> None:
    _LLM_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = _LLM_PROFILES_DIR / f"{model_name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({model_name: profile}, f, ensure_ascii=False, indent=2)


def get_prompt_format(model_id: str, master: dict | None = None) -> str:
    master = master or load_model_master()
    entry = master.get(model_id, {})
    return entry.get("prompt_format", "danbooru")
