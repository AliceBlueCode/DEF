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


# 招待コードのレーティング(SFW/R15/R18/UNL)ごとに許容するcontent_policyの値。
# 基本設計書「性的表現/暴力表現フィルタリング強度」の対応表と同じ並び
# (全年齢=SFW/R15/R18/無制限=UNL)をそのまま使う。
_INVITE_RATING_ALLOWED_SEXUAL = {
    "SFW": ["general"],
    "R15": ["general", "sfw"],
    "R18": ["general", "sfw", "nsfw"],
    "UNL": ["general", "sfw", "nsfw", "hentai"],
}
_INVITE_RATING_ALLOWED_VIOLENCE = {
    "SFW": ["general"],
    "R15": ["general", "violence"],
    "R18": ["general", "violence", "gore"],
    "UNL": ["general", "violence", "gore", "extreme"],
}


def character_rating_exceeds_invite(content_policy: dict | None, session_rating: str) -> bool:
    """キャラクター自身のcontent_policy(rating_sexual/rating_violence)が、
    招待コードのレーティング上限を超えているかを判定する(マルチプレイ設計書
    §3.2「招待コードのレーティング」の期待挙動: R18キャラはSFWセッションで拒否)。

    is_flagged()が「生成された発言の一時的なtags」対セッション設定の
    allowed_sexual/allowed_violence(ユーザーが自由に変えられる個人の表示設定)を
    比較する関数なのに対し、こちらは「キャラクター自身が申告しているレーティング」
    対「招待コード発行時に固定されたレーティング上限」を比較する、参加資格の
    ゲートとして働く別の関心事。ローカル/ソロ利用の生成そのものは対象外
    (README記載のCreator First Principleに反しないよう、オンラインセッションの
    参加・セッション内生成にのみ適用する)。
    """
    content_policy = content_policy or {}
    allowed_sexual = _INVITE_RATING_ALLOWED_SEXUAL.get(session_rating, _INVITE_RATING_ALLOWED_SEXUAL["SFW"])
    allowed_violence = _INVITE_RATING_ALLOWED_VIOLENCE.get(session_rating, _INVITE_RATING_ALLOWED_VIOLENCE["SFW"])
    char_sexual = content_policy.get("rating_sexual") or "general"
    char_violence = content_policy.get("rating_violence") or "general"
    return char_sexual not in allowed_sexual or char_violence not in allowed_violence


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
