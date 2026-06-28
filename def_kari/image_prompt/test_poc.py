"""画像プロンプト生成パイプライン PoC検証スクリプト。

検証項目:
1. タグ抽出が視覚要素のみを正しく抽出するか
2. 会話テキストからノイズタグが生成されないか
3. テンプレート生成が正しい順序でプロンプトを組み立てるか
4. 翻訳プロバイダと組み合わせた日本語→プロンプト変換
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def test_extract_visual():
    from tag_extractor import extract_visual_tags

    result = extract_visual_tags(
        "A lonely young girl in a flowing white dress standing on a quiet beach "
        "at sunset, tears running down her face"
    )
    print(f"  structured: {result}")

    assert "1girl" in result["character"]
    assert "dress" in result["clothing"]
    assert "beach" in result["location"]
    assert "sunset" in result["time"]
    assert "sad" in result["emotion"] or "crying" in result["action"]
    assert "lonely" in result["mood"] or "lonely" in result["emotion"]

    print("PASS: extract_visual")


def test_no_noise_from_conversation():
    from tag_extractor import extract_flat_tags

    tags = extract_flat_tags(
        "Of course, I think tests are important. "
        "Let's properly make sure Luke is working right. "
        "Let's check and see if there's anything wrong."
    )
    print(f"  conversation tags: {tags}")

    noise = {"course", "think", "tests", "important", "properly", "make",
             "sure", "luke", "working", "right", "check", "see", "anything", "wrong"}
    found_noise = [t for t in tags if t in noise]
    assert not found_noise, f"Noise tags found: {found_noise}"

    print("PASS: no_noise_from_conversation")


def test_extract_flat():
    from tag_extractor import extract_flat_tags

    tags = extract_flat_tags(
        "A happy girl running in the rain at night in a forest"
    )
    print(f"  flat tags: {tags}")

    assert "1girl" in tags
    assert "smile" in tags
    assert "running" in tags
    assert "rain" in tags
    assert "night" in tags
    assert "forest" in tags

    print("PASS: extract_flat")


def test_prompt_generation():
    from prompt_generator import generate_prompt

    structured = {
        "character": ["1girl"],
        "hair_color": ["blonde hair"],
        "emotion": ["smile"],
        "clothing": ["dress"],
        "action": ["standing"],
        "location": ["garden"],
        "time": ["sunset"],
        "weather": [],
        "mood": ["peaceful"],
    }
    prompt = generate_prompt(structured)
    print(f"  prompt: {prompt}")

    assert prompt == "1girl, blonde hair, smile, dress, standing, garden, sunset, peaceful"

    print("PASS: prompt_generation")


def test_end_to_end():
    from prompt_generator import generate_prompt_from_text

    prompt = generate_prompt_from_text(
        "A sad girl with black hair wearing a kimono, "
        "sitting alone in a snowy garden at night"
    )
    print(f"  e2e prompt: {prompt}")

    assert "1girl" in prompt
    assert "sad" in prompt
    assert "black hair" in prompt
    assert "japanese clothes" in prompt
    assert "sitting" in prompt
    assert "garden" in prompt
    assert "night" in prompt
    assert "snow" in prompt

    print("PASS: end_to_end")


def test_japanese_with_translation():
    translation_dir = str(Path(__file__).parent.parent / "translation")
    if translation_dir not in sys.path:
        sys.path.insert(0, translation_dir)

    try:
        from translation_factory import create_provider
    except ImportError:
        print("SKIP: japanese_with_translation (translation module not found)")
        return

    provider = create_provider("library")
    japanese_text = "白いワンピースの少女が夕暮れの海辺で寂しそうに泣いている"
    translated = provider.translate(japanese_text, "ja", "en")
    print(f"  translated: {translated}")

    from prompt_generator import generate_prompt_from_text
    prompt = generate_prompt_from_text(translated)
    print(f"  prompt: {prompt}")

    assert len(prompt) > 0

    print("PASS: japanese_with_translation")


def test_compare_old_vs_new():
    """旧方式（単語分割）と新方式（視覚要素抽出）の比較。"""
    from tag_extractor import extract_flat_tags

    test_text = (
        "Of course, I think tests are important. "
        "We need to properly make sure everything is working right. "
        "Sorry about that, please ignore the previous message."
    )

    import re
    STOPWORDS = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                 "being", "have", "has", "had", "do", "does", "did", "will",
                 "would", "could", "should", "may", "might", "can", "shall",
                 "to", "of", "in", "for", "on", "with", "at", "by", "from",
                 "as", "into", "about", "that", "this", "it", "its", "i",
                 "you", "he", "she", "we", "they", "me", "him", "her", "us",
                 "them", "my", "your", "his", "our", "their", "and", "but",
                 "or", "not", "no", "if", "so", "up", "out", "just"}
    old_tags = [w for w in re.findall(r"[A-Za-z']+", test_text.lower())
                if w not in STOPWORDS and w not in []]
    old_tags = list(dict.fromkeys(old_tags))

    new_tags = extract_flat_tags(test_text)

    print(f"  old method ({len(old_tags)} tags): {old_tags}")
    print(f"  new method ({len(new_tags)} tags): {new_tags}")

    assert len(new_tags) < len(old_tags), "New method should produce fewer tags"

    print("PASS: compare_old_vs_new")


if __name__ == "__main__":
    test_extract_visual()
    test_no_noise_from_conversation()
    test_extract_flat()
    test_prompt_generation()
    test_end_to_end()
    test_japanese_with_translation()
    test_compare_old_vs_new()
    print("\nAll image_prompt PoC tests completed.")
