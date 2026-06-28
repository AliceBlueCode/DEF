"""F-14: 構造化出力JSON Schema(基本設計5.4節)"""

from jsonschema import Draft7Validator

EMOTIONS = ["neutral", "happy", "angry", "sad"]

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "dialogue": {"type": "string", "description": "セリフ(母国語)"},
        "emotion": {"type": "string", "enum": EMOTIONS, "description": "感情"},
        "image_prompt_en": {
            "type": "string",
            "description": "英語の画像生成プロンプト(Danbooruタグ等)",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "セーフティタグ(該当なしの場合は空配列)",
        },
    },
    "required": ["dialogue", "emotion", "image_prompt_en", "tags"],
    "additionalProperties": False,
}

VALIDATOR = Draft7Validator(RESPONSE_SCHEMA)

IMAGE_PROMPT_SCHEMA = {
    "type": "object",
    "properties": {
        "image_prompt_en": {
            "type": "string",
            "description": "英語の画像生成プロンプト(Danbooruタグ等)",
        },
    },
    "required": ["image_prompt_en"],
    "additionalProperties": False,
}

IMAGE_PROMPT_VALIDATOR = Draft7Validator(IMAGE_PROMPT_SCHEMA)
