"""Phase 4 CLIテスト: 今日追加した機能のユニットテスト。

使用方法:
  cd e:\tools\DEF
  python -m def_kari.test_phase4
"""

import os
import json
import tempfile


def test_characters():
    from def_kari.characters import get_character, apply_name_reading, get_tts_speaker_id, list_character_choices

    choices = list_character_choices()
    assert len(choices) > 0
    print(f"  {len(choices)} characters found")

    luna = get_character("character_luna_001")
    assert luna["name"]
    assert luna["appearance_tags"]
    assert luna["persona_description"]
    print(f"  luna: name={luna['name']}")

    unknown = get_character("nonexistent_character_xyz")
    assert unknown["name"]

    char_with_reading = {"name": "燈佳", "name_reading": {"family_name": "", "given_name": "トウカ"}}
    result = apply_name_reading("燈佳が笑った", char_with_reading)
    assert "トウカ" in result
    assert "燈佳" not in result

    no_reading = apply_name_reading("テスト", {"name": "テスト"})
    assert no_reading == "テスト"

    speaker = get_tts_speaker_id({"voicevox_speaker_id": 5}, "voicevox")
    assert speaker == 5

    speaker_default = get_tts_speaker_id({}, "voicevox")
    assert speaker_default == 2

    print("PASS: characters")


def test_secrets_store():
    from def_kari import secrets_store

    original_path = secrets_store.STORE_PATH
    original_key_path = secrets_store.KEY_PATH
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            from pathlib import Path
            secrets_store.DATA_DIR = Path(tmpdir)
            secrets_store.KEY_PATH = Path(tmpdir) / "test.key"
            secrets_store.STORE_PATH = Path(tmpdir) / "test.enc.json"

            assert not secrets_store.has_api_key("test_service")
            assert secrets_store.get_api_key("test_service") is None

            secrets_store.set_api_key("test_service", "my-secret-key-123")
            assert secrets_store.has_api_key("test_service")
            assert secrets_store.get_api_key("test_service") == "my-secret-key-123"

            secrets_store.delete_api_key("test_service")
            assert not secrets_store.has_api_key("test_service")
            assert secrets_store.get_api_key("test_service") is None

            secrets_store.set_api_key("svc_a", "key_a")
            secrets_store.set_api_key("svc_b", "key_b")
            assert secrets_store.get_api_key("svc_a") == "key_a"
            assert secrets_store.get_api_key("svc_b") == "key_b"

            print("PASS: secrets_store")
    finally:
        secrets_store.STORE_PATH = original_path
        secrets_store.KEY_PATH = original_key_path


def test_t2i_profiles():
    from def_kari.models.t2i_profiles import get_quality_settings, save_quality_settings, DEFAULT_QUALITY_TAGS, DEFAULT_NEGATIVE_PROMPT

    qt, neg = get_quality_settings(None)
    assert qt == DEFAULT_QUALITY_TAGS
    assert neg == DEFAULT_NEGATIVE_PROMPT

    qt2, neg2 = get_quality_settings("nonexistent_model")
    assert qt2 == DEFAULT_QUALITY_TAGS

    from def_kari.models import t2i_profiles
    original_path = t2i_profiles.PROFILES_PATH
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            from pathlib import Path
            t2i_profiles.PROFILES_PATH = Path(tmpdir) / "test_t2i.json"
            t2i_profiles.POC_PROFILES_PATH = Path(tmpdir) / "nonexistent.json"

            save_quality_settings("test_model", "best quality, ultra", "worst quality, ugly")
            qt3, neg3 = get_quality_settings("test_model")
            assert qt3 == "best quality, ultra"
            assert neg3 == "worst quality, ugly"

            print("PASS: t2i_profiles")
    finally:
        t2i_profiles.PROFILES_PATH = original_path


def test_extract_dialogue():
    from def_kari.llm.client import _extract_dialogue

    raw_json = '{"dialogue": "こんにちは", "emotion": "happy"}\n\nSome extra text'
    assert _extract_dialogue(raw_json) == "こんにちは"

    raw_meta = "セリフです\n\n### Instruction: 次の質問\n答え"
    assert "Instruction" not in _extract_dialogue(raw_meta)

    raw_warning = "セリフです\nWARNING: これは注意です"
    assert "WARNING" not in _extract_dialogue(raw_warning)

    raw_short_quote = "text 「あ」 more text here and more"
    result = _extract_dialogue(raw_short_quote)
    assert len(result) > 2

    raw_long_quote = "前置き「こんにちは、お元気ですか？とても良い天気ですね」後ろ"
    result2 = _extract_dialogue(raw_long_quote)
    assert "こんにちは" in result2

    print("PASS: extract_dialogue")


def test_estimate_emotion():
    from def_kari.llm.client import _estimate_emotion

    assert _estimate_emotion("嬉しいです♪") == "happy"
    assert _estimate_emotion("怒っています") == "angry"
    assert _estimate_emotion("悲しいです") == "sad"
    assert _estimate_emotion("普通の会話です") == "neutral"

    print("PASS: estimate_emotion")


def test_repair_types():
    from def_kari.llm.client import _repair_types

    parsed = {"dialogue": "hello", "emotion": "happy", "image_prompt_en": [], "tags": []}
    result = _repair_types(parsed)
    assert result["image_prompt_en"] == ""
    assert isinstance(result["image_prompt_en"], str)

    parsed2 = {"dialogue": "hello", "emotion": "happy", "image_prompt_en": ["tag1", "tag2"], "tags": []}
    result2 = _repair_types(parsed2)
    assert result2["image_prompt_en"] == "tag1, tag2"

    parsed3 = {"dialogue": "hello", "emotion": "invalid", "image_prompt_en": "ok", "tags": "nsfw"}
    result3 = _repair_types(parsed3)
    assert result3["emotion"] == "neutral"
    assert result3["tags"] == ["nsfw"]

    parsed4 = {"dialogue": None, "emotion": "happy", "image_prompt_en": None, "tags": None}
    result4 = _repair_types(parsed4)
    assert result4["dialogue"] == ""
    assert result4["image_prompt_en"] == ""
    assert result4["tags"] == []

    print("PASS: repair_types")


def test_autofix_trailing_text():
    from def_kari.llm.client import _autofix, _try_parse_and_validate

    raw = '{"dialogue": "hello", "emotion": "happy", "image_prompt_en": "1girl", "tags": []}\n\nExtra text here'
    fixed = _autofix(raw)
    ok, parsed, errors = _try_parse_and_validate(fixed)
    assert ok
    assert parsed["dialogue"] == "hello"

    print("PASS: autofix_trailing_text")


def test_autofix_control_chars():
    from def_kari.llm.client import _autofix, _try_parse_and_validate

    raw = '{"dialogue": "line1\nline2", "emotion": "happy", "image_prompt_en": "1girl", "tags": []}'
    fixed = _autofix(raw)
    ok, parsed, errors = _try_parse_and_validate(fixed)
    assert ok
    assert "line1" in parsed["dialogue"]

    print("PASS: autofix_control_chars")


def test_autofix_missing_commas():
    from def_kari.llm.client import _autofix, _try_parse_and_validate

    raw = '{\n"dialogue": "hello"\n"emotion": "happy"\n"image_prompt_en": "1girl"\n"tags": []\n}'
    fixed = _autofix(raw)
    ok, parsed, errors = _try_parse_and_validate(fixed)
    assert ok
    assert parsed["dialogue"] == "hello"

    print("PASS: autofix_missing_commas")


def test_safety_detect():
    from def_kari.safety.filters import detect_tags_from_text

    assert detect_tags_from_text("普通の会話です") == []
    assert "nsfw" in detect_tags_from_text("卑猥な内容です")
    assert "nsfw" in detect_tags_from_text("エロい話をしよう")
    assert detect_tags_from_text("暴力的な内容") == []

    print("PASS: safety_detect")


def test_ecosystem_map():
    from pathlib import Path

    map_path = Path(__file__).parent.parent / "data" / "civitai_ecosystem_map.json"
    if map_path.exists():
        with open(map_path, encoding="utf-8") as f:
            eco_map = json.load(f)
        assert eco_map.get("illustrious") == "sdxl"
        assert eco_map.get("pony") == "sdxl"
        assert eco_map.get("sd 1.5") == "sd1"
        print("PASS: ecosystem_map")
    else:
        print("SKIP: ecosystem_map (file not found)")


def test_llm_services():
    from pathlib import Path

    svc_path = Path(__file__).parent.parent / "data" / "llm_services.json"
    if svc_path.exists():
        with open(svc_path, encoding="utf-8") as f:
            services = json.load(f)
        assert isinstance(services, list)
        assert len(services) >= 2
        ids = [s["id"] for s in services]
        assert "gemini" in ids
        assert "openai" in ids
        for s in services:
            assert "id" in s
            assert "label" in s
            assert "type" in s
            assert "api_url" in s
        print("PASS: llm_services")
    else:
        print("SKIP: llm_services (file not found)")


def test_api_services():
    from pathlib import Path

    svc_path = Path(__file__).parent.parent / "data" / "api_services.json"
    if svc_path.exists():
        with open(svc_path, encoding="utf-8") as f:
            services = json.load(f)
        assert isinstance(services, list)
        ids = [s["id"] for s in services]
        assert "civitai" in ids
        assert "deepl" in ids
        for s in services:
            assert "id" in s
            assert "label" in s
        print("PASS: api_services")
    else:
        print("SKIP: api_services (file not found)")


if __name__ == "__main__":
    test_characters()
    test_secrets_store()
    test_t2i_profiles()
    test_extract_dialogue()
    test_estimate_emotion()
    test_repair_types()
    test_autofix_trailing_text()
    test_autofix_control_chars()
    test_autofix_missing_commas()
    test_safety_detect()
    test_ecosystem_map()
    test_llm_services()
    test_api_services()
    print("\nPhase 4 CLI tests: all passed.")
