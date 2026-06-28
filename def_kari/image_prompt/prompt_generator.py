"""ステップ2: 構造化タグからT2I画像プロンプトを生成する。

ルールベース・テンプレートによる高速・安定な生成。
"""

from __future__ import annotations

TAG_ORDER = [
    "character",
    "hair_color",
    "emotion",
    "clothing",
    "action",
    "location",
    "time",
    "weather",
    "mood",
]


def generate_prompt(structured_tags: dict[str, list[str]]) -> str:
    """構造化タグ辞書からカンマ区切りのプロンプト文字列を生成する。

    TAG_ORDERに従い、キャラクター→髪色→感情→服装→動作→場所→時間→天候→雰囲気の順。
    """
    tags: list[str] = []
    for category in TAG_ORDER:
        for tag in structured_tags.get(category, []):
            if tag not in tags:
                tags.append(tag)
    return ", ".join(tags)


def generate_prompt_from_text(text: str) -> str:
    """英語テキストからタグ抽出→プロンプト生成をワンステップで実行する。"""
    from tag_extractor import extract_visual_tags
    return generate_prompt(extract_visual_tags(text))
