"""F-7/F-8: セーフティタグに基づくフィルタリング判定(基本設計5.1節)

レーティング設定（allowed_rating_sexual/allowed_rating_violence）と連携し、
許容範囲外のコンテンツにセーフティ強度（off/warn/mask）を適用する。
"""

SAFETY_OFF = "off"
SAFETY_WARN = "warn"
SAFETY_MASK = "mask"

SAFETY_LEVELS = [SAFETY_OFF, SAFETY_WARN, SAFETY_MASK]

_TAG_TO_SEXUAL_RATING = {
    "nsfw": "nsfw",
    "hentai": "hentai",
    "sfw": "sfw",
}

_TAG_TO_VIOLENCE_RATING = {
    "violence": "violence",
    "gore": "gore",
    "extreme": "extreme",
}

_NSFW_KEYWORDS = {
    "nsfw", "hentai", "sex", "nude", "naked", "erotic",
    "卑猥", "性的", "裸", "エロ", "快感", "淫", "喘",
    "セックス", "おっぱい", "ちんちん", "まんこ", "射精",
}

_VIOLENCE_KEYWORDS = {
    "gore", "guro", "グロ", "流血", "殺害", "拷問", "切断",
}


def detect_tags_from_text(text: str) -> list[str]:
    """LLMがtagsを空で返した場合のフォールバック検出。"""
    lower = text.lower()
    tags = []
    for kw in _NSFW_KEYWORDS:
        if kw in lower:
            if "nsfw" not in tags:
                tags.append("nsfw")
            break
    for kw in _VIOLENCE_KEYWORDS:
        if kw in lower:
            if "violence" not in tags:
                tags.append("violence")
            break
    return tags


def is_flagged(tags: list[str] | None, allowed_sexual: list[str] | None = None, allowed_violence: list[str] | None = None) -> bool:
    if not tags:
        return False
    if allowed_sexual is None and allowed_violence is None:
        return bool(tags)
    allowed_sexual = allowed_sexual or ["general"]
    allowed_violence = allowed_violence or ["general"]
    for tag in tags:
        if tag in _TAG_TO_SEXUAL_RATING:
            if _TAG_TO_SEXUAL_RATING[tag] not in allowed_sexual:
                return True
        if tag in _TAG_TO_VIOLENCE_RATING:
            if _TAG_TO_VIOLENCE_RATING[tag] not in allowed_violence:
                return True
    return False


def effective_level(global_level: str, flagged: bool, unlocked: bool) -> str:
    if not flagged:
        return SAFETY_OFF
    if unlocked:
        return SAFETY_OFF
    return global_level


def should_mask_text(level: str) -> bool:
    return level == SAFETY_MASK


def should_blur_image(level: str) -> bool:
    return level == SAFETY_WARN


def should_hide_image(level: str) -> bool:
    return level == SAFETY_MASK


def should_autoplay_audio(level: str) -> bool:
    return level == SAFETY_OFF


def should_hide_audio(level: str) -> bool:
    return level == SAFETY_MASK
