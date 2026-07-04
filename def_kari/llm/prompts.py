"""システムプロンプト構築(基本設計F-9)

quirksに基づいてJSON指示の有無・プロンプト構成を自動切替する。
"""

from def_kari.llm.schema import RESPONSE_SCHEMA

_LANG_LABELS = {
    "ja": "日本語",
    "en": "English",
    "zh": "中文",
    "ko": "한국어",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
}

_JSON_INSTRUCTIONS = {
    "ja": (
        "【出力形式】以下のフィールドを含むJSONオブジェクトで応答すること:\n"
        '- "dialogue": キャラクターとしての返答（日本語）\n'
        '- "emotion": 感情を表す文字列または配列。単体: "neutral", "happy", "sad", "angry", "surprised", "scared", "disgusted", "excited", "tender", "thoughtful", "embarrassed", "tired"。複合可: ["happy", "embarrassed"]\n'
        '- "image_prompt_en": 画像生成用の英語プロンプト（Danbooruタグ形式）\n'
        '- "tags": 該当するコンテンツ要素のみを含む配列。要素がなければ必ず空配列[]にすること。\n'
        '  ※性的・暴力的な要素が一切ない通常の会話は必ず[]\n'
        '  性的要素がある場合のみ: "sfw"(恋愛的・示唆的な性的要素あり), "nsfw"(性的描写あり), "hentai"(過激な性的描写あり)\n'
        '  暴力要素がある場合のみ: "violence"(戦闘・アクション), "gore"(流血・負傷), "extreme"(残虐・拷問)\n'
        '  例: 通常会話→[], 恋愛的→["sfw"], 性的→["nsfw"], 戦闘→["violence"]\n'
        "\nJSONオブジェクト以外のテキストを出力してはならない。"
    ),
    "en": (
        "You MUST respond with a JSON object containing exactly these fields:\n"
        '- "dialogue": your in-character reply (in English)\n'
        '- "emotion": string or array. Single: "neutral", "happy", "sad", "angry", "surprised", "scared", "disgusted", "excited", "tender", "thoughtful", "embarrassed", "tired". Compound: ["happy", "embarrassed"]\n'
        '- "image_prompt_en": English image generation prompt (Danbooru tags)\n'
        '- "tags": array containing ONLY content elements that are actually present. Use [] for normal conversation with no such elements.\n'
        '  NOTE: ordinary conversation with no sexual or violent content MUST use []\n'
        '  Only if sexual content is present: "sfw"(romantic/suggestive), "nsfw"(sexual content), "hentai"(explicit)\n'
        '  Only if violent content is present: "violence"(action/fighting), "gore"(blood/injury), "extreme"(brutal/torture)\n'
        '  Examples: normal chat→[], romantic→["sfw"], sexual→["nsfw"], action→["violence"]\n'
        "\nDo NOT include any text outside the JSON object."
    ),
}

_APPEARANCE_LABEL = {
    "ja": "外見タグ（image_prompt_enに必ず含めること）",
    "en": "Your visual appearance tags (always include in image_prompt_en)",
}

_NO_JSON_INSTRUCTION = {
    "ja": "キャラクターとして応答すること。JSON、メタデータ、説明文を出力してはならない。",
    "en": "Reply in character. Do not output JSON, metadata, or any explanation.",
}

_SEXUAL_HIERARCHY = ["general", "sfw", "nsfw", "hentai"]
_VIOLENCE_HIERARCHY = ["general", "violence", "gore", "extreme"]


def _max_level(hierarchy: list[str], allowed: list[str]) -> str:
    for level in reversed(hierarchy):
        if level in allowed:
            return level
    return hierarchy[0]


def _build_rating_instruction(
    allowed_sexual: list[str] | None,
    allowed_violence: list[str] | None,
    lang: str,
) -> str:
    if not allowed_sexual and not allowed_violence:
        return ""
    max_s = _max_level(_SEXUAL_HIERARCHY, allowed_sexual or ["general"])
    max_v = _max_level(_VIOLENCE_HIERARCHY, allowed_violence or ["general"])

    _sexual_desc_ja = {
        "general": "性的な内容は一切禁止",
        "sfw": "恋愛・示唆的な表現（sfw）まで生成可",
        "nsfw": "性的な描写（nsfw）まで生成可",
        "hentai": "過激な性的描写（hentai）まで生成可",
    }
    _violence_desc_ja = {
        "general": "暴力描写は一切禁止",
        "violence": "戦闘・アクション描写（violence）まで生成可",
        "gore": "流血・負傷描写（gore）まで生成可",
        "extreme": "残虐描写（extreme）まで生成可",
    }
    _sexual_desc_en = {
        "general": "No sexual content allowed",
        "sfw": "Suggestive/romantic content (sfw) allowed",
        "nsfw": "Sexual content (nsfw) allowed",
        "hentai": "Explicit sexual content (hentai) allowed",
    }
    _violence_desc_en = {
        "general": "No violent content allowed",
        "violence": "Action/fighting content (violence) allowed",
        "gore": "Blood/injury content (gore) allowed",
        "extreme": "Brutal/torture content (extreme) allowed",
    }
    if lang == "ja":
        return (
            "【コンテンツ制限】\n"
            f"性的: {_sexual_desc_ja.get(max_s, max_s)}\n"
            f"暴力: {_violence_desc_ja.get(max_v, max_v)}\n"
            "この制限に従って応答すること。"
        )
    return (
        "[Content Restrictions]\n"
        f"Sexual: {_sexual_desc_en.get(max_s, max_s)}\n"
        f"Violence: {_violence_desc_en.get(max_v, max_v)}\n"
        "Respond within these restrictions."
    )


def build_system_prompt(
    persona_description: str,
    appearance_tags: str = "",
    quirks: dict | None = None,
    user_language: str = "ja",
    allowed_sexual: list[str] | None = None,
    allowed_violence: list[str] | None = None,
) -> str:
    quirks = quirks or {}
    json_capable = quirks.get("json_capable", True)
    _lang_name = _LANG_LABELS.get(user_language, user_language)
    _is_ja = user_language == "ja"

    parts = [persona_description]

    if appearance_tags:
        _app_label = _APPEARANCE_LABEL.get(user_language, _APPEARANCE_LABEL["en"])
        parts.append(f"{_app_label}: {appearance_tags}")

    parts.append(
        f"【言語ルール】応答は必ず{_lang_name}で行うこと。他の言語に切り替えてはならない。"
        if _is_ja else
        f"[Language Rule] You MUST respond in {_lang_name}. Do NOT switch to any other language."
    )

    rating_inst = _build_rating_instruction(allowed_sexual, allowed_violence, user_language)
    if rating_inst:
        parts.append(rating_inst)

    if json_capable:
        _json_inst = _JSON_INSTRUCTIONS.get(user_language)
        if not _json_inst:
            _json_inst = _JSON_INSTRUCTIONS["en"].replace("in English", f"in {_lang_name}")
        parts.append(_json_inst)
    else:
        parts.append(_NO_JSON_INSTRUCTION.get(user_language, _NO_JSON_INSTRUCTION["en"]))

    return "\n\n".join(parts)
