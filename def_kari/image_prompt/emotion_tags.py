"""D方式: emotionに応じた補助タグをimage_prompt_enに追記する。"""

import json
from pathlib import Path

_DICT_PATH = Path(__file__).parent.parent.parent / "data" / "emotion_tag_dict.json"


def _load_emotion_tag_dict() -> dict:
    try:
        with open(_DICT_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def apply_emotion_tags(image_prompt_en: str, emotion) -> str:
    """emotionに紐づく補助タグをimage_prompt_enに追記する。

    emotionは文字列または配列（複合感情）。
    image_prompt_enに既に含まれているタグは重複追加しない。
    """
    _dict = _load_emotion_tag_dict()
    emotions = emotion if isinstance(emotion, list) else [emotion]
    existing = [t.strip() for t in image_prompt_en.split(",")]
    new_tags = []
    for emo in emotions:
        for tag in _dict.get(emo, []):
            if tag not in existing and tag not in new_tags:
                new_tags.append(tag)
    return ", ".join(filter(None, [image_prompt_en, *new_tags]))
