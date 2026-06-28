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
        '- "tags": セーフティタグの配列。該当するものを全て含める。該当なしは空配列[]\n'
        '  性的: "sfw"(恋愛・示唆), "nsfw"(性的描写), "hentai"(過激な性的描写)\n'
        '  暴力: "violence"(戦闘・アクション), "gore"(流血・負傷), "extreme"(残虐・拷問)\n'
        '  例: ["sfw"], ["nsfw", "violence"], ["hentai", "gore"], []\n'
        "\nJSONオブジェクト以外のテキストを出力してはならない。"
    ),
    "en": (
        "You MUST respond with a JSON object containing exactly these fields:\n"
        '- "dialogue": your in-character reply (in English)\n'
        '- "emotion": string or array. Single: "neutral", "happy", "sad", "angry", "surprised", "scared", "disgusted", "excited", "tender", "thoughtful", "embarrassed", "tired". Compound: ["happy", "embarrassed"]\n'
        '- "image_prompt_en": English image generation prompt (Danbooru tags)\n'
        '- "tags": array of safety tags. Include all that apply. Use empty array [] if none apply.\n'
        '  Sexual: "sfw"(suggestive), "nsfw"(sexual), "hentai"(explicit)\n'
        '  Violence: "violence"(action/fighting), "gore"(blood/injury), "extreme"(brutal/torture)\n'
        '  Examples: ["sfw"], ["nsfw", "violence"], ["hentai", "gore"], []\n'
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


def build_system_prompt(
    persona_description: str,
    appearance_tags: str = "",
    quirks: dict | None = None,
    user_language: str = "ja",
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

    if json_capable:
        _json_inst = _JSON_INSTRUCTIONS.get(user_language)
        if not _json_inst:
            _json_inst = _JSON_INSTRUCTIONS["en"].replace("in English", f"in {_lang_name}")
        parts.append(_json_inst)
    else:
        parts.append(_NO_JSON_INSTRUCTION.get(user_language, _NO_JSON_INSTRUCTION["en"]))

    return "\n\n".join(parts)
