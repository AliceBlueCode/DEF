"""ステップ1: 自然言語テキストから画像構成要素を構造化JSONとして抽出する。

ルールベース（辞書マッチング）による高速・安定な抽出。
LLM不要・オフライン動作可能。
"""

from __future__ import annotations

import re

VISUAL_CATEGORIES: dict[str, list[tuple[str, str]]] = {
    "character": [
        (r"\b(?:girl|woman|female|lady)\b", "1girl"),
        (r"\b(?:boy|man|male|guy)\b", "1boy"),
        (r"\bchild(?:ren)?\b", "child"),
        (r"\b(?:old man|elder|elderly)\b", "old man"),
        (r"\b(?:couple|pair|two people)\b", "2people"),
    ],
    "hair_color": [
        (r"\bblack hair\b", "black hair"),
        (r"\bblonde?\b(?:\s*hair)?", "blonde hair"),
        (r"\b(?:brown|brunette)\b(?:\s*hair)?", "brown hair"),
        (r"\bred hair\b", "red hair"),
        (r"\bwhite hair\b", "white hair"),
        (r"\bsilver hair\b", "silver hair"),
        (r"\bpink hair\b", "pink hair"),
        (r"\bblue hair\b", "blue hair"),
    ],
    "emotion": [
        (r"\b(?:happy|smile|smiling|laughing|cheerful|joy)\b", "smile"),
        (r"\b(?:sad|crying|tears|sorrowful|melancholic)\b", "sad"),
        (r"\b(?:angry|furious|rage|mad)\b", "angry"),
        (r"\b(?:surprised|shocked|astonished)\b", "surprised"),
        (r"\b(?:embarrassed|blushing|shy)\b", "blush"),
        (r"\b(?:scared|afraid|frightened|terrified)\b", "scared"),
        (r"\b(?:lonely|alone|solitary)\b", "lonely"),
    ],
    "clothing": [
        (r"\b(?:dress|one-?piece)\b", "dress"),
        (r"\bschool uniform\b", "school uniform"),
        (r"\bsailor\b(?:\s*uniform)?", "sailor uniform"),
        (r"\b(?:kimono|yukata)\b", "japanese clothes"),
        (r"\b(?:suit|formal|tuxedo)\b", "formal"),
        (r"\b(?:armor|armour)\b", "armor"),
        (r"\b(?:naked|nude)\b", "nude"),
        (r"\bswim(?:suit|wear)\b", "swimsuit"),
        (r"\b(?:gothic|goth)\b", "gothic"),
        (r"\blolita\b", "lolita fashion"),
        (r"\b(?:maid)\b", "maid"),
        (r"\b(?:hoodie)\b", "hoodie"),
        (r"\b(?:jacket|coat)\b", "jacket"),
    ],
    "action": [
        (r"\b(?:standing|stand)\b", "standing"),
        (r"\b(?:sitting|sit|seated)\b", "sitting"),
        (r"\b(?:running|run)\b", "running"),
        (r"\b(?:walking|walk)\b", "walking"),
        (r"\b(?:sleeping|sleep|asleep)\b", "sleeping"),
        (r"\b(?:fighting|fight|battle)\b", "fighting"),
        (r"\b(?:eating|eat)\b", "eating"),
        (r"\b(?:reading|read)\b", "reading"),
        (r"\b(?:crying|cry|weeping)\b", "crying"),
        (r"\b(?:looking|look|gazing|gaze)\b", "looking at viewer"),
        (r"\b(?:hugging|hug|embrace)\b", "hug"),
    ],
    "location": [
        (r"\b(?:beach|seaside|seashore|shore)\b", "beach"),
        (r"\b(?:forest|woods)\b", "forest"),
        (r"\b(?:school|classroom)\b", "school"),
        (r"\b(?:city|town|urban|street)\b", "city"),
        (r"\b(?:castle|palace)\b", "castle"),
        (r"\b(?:mountain|hill)\b", "mountain"),
        (r"\b(?:garden|park)\b", "garden"),
        (r"\b(?:room|bedroom|indoor)\b", "indoors"),
        (r"\b(?:outdoor|outside)\b", "outdoors"),
        (r"\b(?:sky|clouds?)\b", "sky"),
        (r"\b(?:ocean|sea)\b", "ocean"),
        (r"\b(?:river|lake)\b", "water"),
    ],
    "time": [
        (r"\b(?:sunset|dusk|evening|twilight)\b", "sunset"),
        (r"\b(?:sunrise|dawn|morning)\b", "sunrise"),
        (r"\b(?:night|midnight|dark)\b", "night"),
        (r"\b(?:noon|midday|daytime)\b", "day"),
    ],
    "weather": [
        (r"\b(?:rain|rainy|raining)\b", "rain"),
        (r"\b(?:snow|snowy|snowing)\b", "snow"),
        (r"\b(?:wind|windy)\b", "wind"),
        (r"\b(?:storm|thunder)\b", "storm"),
        (r"\b(?:sunny|clear)\b", "sunny"),
        (r"\b(?:fog|foggy|mist|misty)\b", "fog"),
    ],
    "mood": [
        (r"\b(?:dramatic|intense)\b", "dramatic lighting"),
        (r"\b(?:peaceful|calm|serene|tranquil)\b", "peaceful"),
        (r"\b(?:mysterious|eerie|creepy)\b", "dark atmosphere"),
        (r"\b(?:romantic|love)\b", "romantic"),
        (r"\b(?:nostalgic|memory|memories)\b", "nostalgic"),
    ],
}

_COMPILED: dict[str, list[tuple[re.Pattern, str]]] = {
    cat: [(re.compile(pat, re.IGNORECASE), tag) for pat, tag in rules]
    for cat, rules in VISUAL_CATEGORIES.items()
}


def extract_visual_tags(text: str) -> dict[str, list[str]]:
    """英語テキストから画像構成要素を抽出し、カテゴリ別の辞書で返す。

    Args:
        text: 英語テキスト（翻訳済み）。

    Returns:
        {"character": ["1girl"], "emotion": ["smile"], "location": ["beach"], ...}
        マッチしなかったカテゴリは空リスト。
    """
    result: dict[str, list[str]] = {}
    for category, rules in _COMPILED.items():
        tags = []
        for pattern, tag in rules:
            if pattern.search(text) and tag not in tags:
                tags.append(tag)
        result[category] = tags
    return result


def extract_flat_tags(text: str) -> list[str]:
    """extract_visual_tagsの結果をフラットなタグリストで返す。重複なし。"""
    structured = extract_visual_tags(text)
    tags: list[str] = []
    for category_tags in structured.values():
        for tag in category_tags:
            if tag not in tags:
                tags.append(tag)
    return tags
