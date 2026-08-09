"""T2Iモデルごとの品質タグ・ネガティブプロンプト管理"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"
POC_DATA_DIR = Path(__file__).parent.parent.parent / "poc" / "data"
PROFILES_PATH = DATA_DIR / "t2i_model_profiles.json"
POC_PROFILES_PATH = POC_DATA_DIR / "t2i_model_profiles.json"

DEFAULT_QUALITY_TAGS = "masterpiece, best quality"
DEFAULT_NEGATIVE_PROMPT = "lowres, bad anatomy, worst quality"
DEFAULT_STEPS = 20
DEFAULT_CFG_SCALE = 7.0

DEFAULT_PROFILE = {
    "quality_tags": DEFAULT_QUALITY_TAGS,
    "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
    "steps": DEFAULT_STEPS,
    "cfg_scale": DEFAULT_CFG_SCALE,
}


def _load_profiles() -> dict:
    profiles = {}
    for path in (PROFILES_PATH, POC_PROFILES_PATH):
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    profiles.update(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass
    return profiles


def get_tag_format(model_name: str | None) -> str:
    """タグ形式を返す ('danbooru' | 'e621' | 'natural' | 'other')。デフォルトは 'danbooru'。"""
    profiles = _load_profiles()
    profile = profiles.get(model_name, {}) if model_name else {}
    return profile.get("tag_format", "danbooru")


def get_current_tag_format() -> str:
    """設定から現在アクティブなT2Iモデルの tag_format を取得する。"""
    try:
        from def_kari.settings import load_settings
        settings = load_settings()
        t2i_backend = settings.get("t2i_backend", "")
        t2i_model = settings.get(f"t2i_model_{t2i_backend}", "") if t2i_backend else ""
        return get_tag_format(t2i_model or None)
    except Exception:
        return "danbooru"


def get_quality_settings(model_name: str | None) -> tuple[str, str]:
    """(quality_tags, negative_prompt) を返す。"""
    profiles = _load_profiles()
    profile = profiles.get(model_name, {}) if model_name else {}
    return (
        profile.get("quality_tags", DEFAULT_QUALITY_TAGS),
        profile.get("negative_prompt", DEFAULT_NEGATIVE_PROMPT),
    )


def get_profile(model_name: str | None) -> dict:
    profiles = _load_profiles()
    stored = profiles.get(model_name, {}) if model_name else {}
    return {**DEFAULT_PROFILE, **stored}


def save_profile(model_name: str, profile: dict) -> None:
    profiles = {}
    if PROFILES_PATH.exists():
        try:
            with open(PROFILES_PATH, encoding="utf-8") as f:
                profiles = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    profiles[model_name] = profile
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)


def save_quality_settings(model_name: str, quality_tags: str, negative_prompt: str) -> None:
    profiles = {}
    if PROFILES_PATH.exists():
        try:
            with open(PROFILES_PATH, encoding="utf-8") as f:
                profiles = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    if model_name not in profiles:
        profiles[model_name] = {}
    profiles[model_name]["quality_tags"] = quality_tags
    profiles[model_name]["negative_prompt"] = negative_prompt
    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROFILES_PATH, "w", encoding="utf-8") as f:
        json.dump(profiles, f, ensure_ascii=False, indent=2)
