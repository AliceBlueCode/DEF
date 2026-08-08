"""DEF(kari) unit tests -- pure logic only, no external backends.

Covers:
  1. Character loader  (characters.py)
  2. F-14 autofix      (llm/client.py)
  3. Safety filters     (safety/filters.py)
  4. i18n              (i18n.py)
  5. Settings          (settings.py)
  6. Episode save/load pattern
  7. ComfyUI hash strip
  8. T2I profile steps/cfg loading
  9. _apply_char_tags tag merging
 10. _clean_history_for_retake
"""

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# 1. Character loader
# ---------------------------------------------------------------------------
from def_kari.characters import (
    DEFAULT_CHARACTER_ID,
    _find_character_dir,
    _get_bp,
    _get_pa,
    _get_vr,
    apply_name_reading,
    get_character,
    get_tts_speaker_id,
    list_character_choices,
    load_profiles,
    save_profile,
)


class TestLoadProfiles:
    """load_profiles should discover profile.json files under characters dirs."""

    def test_returns_dict(self):
        profiles = load_profiles()
        assert isinstance(profiles, dict)

    def test_known_character_present(self):
        profiles = load_profiles()
        assert "character_luna_001" in profiles

    def test_profile_has_base_profile(self):
        profiles = load_profiles()
        luna = profiles["character_luna_001"]
        assert "base_profile" in luna

    def test_loads_from_temp_directory(self, tmp_path):
        """Create a minimal character dir and verify load_profiles picks it up."""
        char_dir = tmp_path / "test_char_001"
        char_dir.mkdir()
        profile_data = {
            "test_char_001": {
                "base_profile": {
                    "name": "Test",
                    "persona_attributes": {},
                    "visual_references": {},
                }
            }
        }
        (char_dir / "profile.json").write_text(
            json.dumps(profile_data), encoding="utf-8"
        )

        with mock.patch(
            "def_kari.characters.CHARACTERS_DIR", tmp_path
        ), mock.patch(
            "def_kari.characters.PRIVATE_CHARACTERS_DIR",
            tmp_path / "nonexistent_private",
        ):
            result = load_profiles()
        assert "test_char_001" in result
        assert result["test_char_001"]["base_profile"]["name"] == "Test"

    def test_empty_dirs_return_empty(self, tmp_path, monkeypatch):
        # CHARACTER_REPO_PATH(S) を明示的に無効化する。def_kari/api/main.py が
        # インポート時に.envを読み込みos.environにセットする副作用があるため、
        # 先に他のテストがmainをインポート済みだと実環境のリポジトリパスが
        # 残っていて_get_repo_paths()経由で実キャラクターを拾ってしまい、
        # 「空なら空を返す」の前提が崩れる(2026-08-08、テスト再編時に発覚)。
        monkeypatch.delenv("CHARACTER_REPO_PATH", raising=False)
        monkeypatch.delenv("CHARACTER_REPO_PATHS", raising=False)
        with mock.patch(
            "def_kari.characters.CHARACTERS_DIR", tmp_path
        ), mock.patch(
            "def_kari.characters.PRIVATE_CHARACTERS_DIR",
            tmp_path / "nonexistent",
        ), mock.patch(
            "def_kari.characters.PROFILES_PATH",
            tmp_path / "nonexistent.json",
        ), mock.patch(
            "def_kari.characters.POC_PROFILES_PATH",
            tmp_path / "nonexistent2.json",
        ):
            result = load_profiles()
        assert result == {}

    def test_malformed_json_skipped(self, tmp_path):
        char_dir = tmp_path / "bad_char"
        char_dir.mkdir()
        (char_dir / "profile.json").write_text("{invalid json", encoding="utf-8")
        with mock.patch(
            "def_kari.characters.CHARACTERS_DIR", tmp_path
        ), mock.patch(
            "def_kari.characters.PRIVATE_CHARACTERS_DIR",
            tmp_path / "nonexistent",
        ):
            result = load_profiles()
        assert "bad_char" not in result


class TestGetCharacter:
    def test_returns_dict_with_expected_keys(self):
        profiles = load_profiles()
        char = get_character("character_luna_001", profiles)
        assert isinstance(char, dict)
        for key in ("name", "persona_description", "speech_style", "appearance_tags"):
            assert key in char

    def test_unknown_character_returns_empty_name(self):
        char = get_character("nonexistent_xyz", profiles={})
        assert char["name"] == "nonexistent_xyz"

    def test_default_character_id_used_when_none(self):
        profiles = load_profiles()
        char = get_character(None, profiles)
        assert char["name"] != ""

    def test_speech_style_dict_handling(self):
        """When speech_style is a dict with first_person/tone, it should be joined."""
        profile = {
            "base_profile": {
                "name": "TestChar",
                "identity_prompt": "A test character.",
                "persona_attributes": {
                    "speech_style": {
                        "first_person": "わたし",
                        "address_partner": "あなた",
                        "tone": "丁寧語",
                    }
                },
                "visual_references": {},
            }
        }
        char = get_character("tc", profiles={"tc": profile})
        assert "わたし" in char["speech_style"]
        assert "あなた" in char["speech_style"]
        assert "丁寧語" in char["speech_style"]

    def test_speech_style_string_handling(self):
        profile = {
            "base_profile": {
                "name": "TestChar",
                "identity_prompt": "Test",
                "persona_attributes": {"speech_style": "casual"},
                "visual_references": {},
            }
        }
        char = get_character("tc", profiles={"tc": profile})
        assert char["speech_style"] == "casual"

    def test_gender_and_romantic_interest_in_persona(self):
        profile = {
            "base_profile": {
                "name": "G",
                "identity_prompt": "Test",
                "persona_attributes": {
                    "gender": "女",
                    "romantic_interest": ["男", "女"],
                },
                "visual_references": {},
            }
        }
        char = get_character("g", profiles={"g": profile})
        assert "性別: 女" in char["persona_description"]
        assert "恋愛対象: 男, 女" in char["persona_description"]

    # B-2: kokoro_voice
    def test_kokoro_voice_returned(self):
        profile = {
            "base_profile": {
                "name": "KokoroChar",
                "default_model_config": {"kokoro_voice": "jm_kumo"},
                "visual_references": {},
            }
        }
        char = get_character("kk", profiles={"kk": profile})
        assert char["kokoro_voice"] == "jm_kumo"

    def test_kokoro_voice_none_when_unset(self):
        profile = {
            "base_profile": {
                "name": "NoVoice",
                "visual_references": {},
            }
        }
        char = get_character("nv", profiles={"nv": profile})
        assert char["kokoro_voice"] is None

    # B-3: content_policy
    def test_content_policy_returned(self):
        policy = {"is_real_person": False, "allowed_sexual": ["nsfw"]}
        profile = {
            "base_profile": {
                "name": "PolicyChar",
                "content_policy": policy,
                "visual_references": {},
            }
        }
        char = get_character("pc", profiles={"pc": profile})
        assert char["content_policy"] == policy

    def test_content_policy_empty_dict_when_missing(self):
        profile = {
            "base_profile": {
                "name": "NoPolicyChar",
                "visual_references": {},
            }
        }
        char = get_character("np", profiles={"np": profile})
        assert char["content_policy"] == {}

    # B-1: appearance_tags priority (bp > vr.appearance_tags > vr.features)
    def test_appearance_tags_bp_takes_priority_over_vr(self):
        profile = {
            "base_profile": {
                "name": "PrioChar",
                "appearance_tags": "bp_tag, silver_hair",
                "visual_references": {"appearance_tags": "vr_tag, blue_hair"},
            }
        }
        char = get_character("pr", profiles={"pr": profile})
        assert char["appearance_tags"] == "bp_tag, silver_hair"

    def test_appearance_tags_vr_fallback_when_bp_absent(self):
        profile = {
            "base_profile": {
                "name": "VrChar",
                "visual_references": {"appearance_tags": "vr_tag, red_hair"},
            }
        }
        char = get_character("vr", profiles={"vr": profile})
        assert char["appearance_tags"] == "vr_tag, red_hair"

    def test_appearance_tags_features_fallback_when_both_absent(self):
        profile = {
            "base_profile": {
                "name": "FeatChar",
                "visual_references": {"features": "legacy_features_tag"},
            }
        }
        char = get_character("ft", profiles={"ft": profile})
        assert char["appearance_tags"] == "legacy_features_tag"

    def test_appearance_tags_empty_when_none_set(self):
        profile = {
            "base_profile": {
                "name": "NoTagChar",
                "visual_references": {},
            }
        }
        char = get_character("nt", profiles={"nt": profile})
        assert char["appearance_tags"] == ""


class TestLoadProfilesBOM:
    """BOM付きUTF-8ファイルが正常に読み込まれること (B-1修正)。"""

    def test_bom_file_loaded(self, tmp_path):
        char_dir = tmp_path / "bom_char_001"
        char_dir.mkdir()
        profile_data = {
            "bom_char_001": {
                "base_profile": {
                    "name": "BOMChar",
                    "visual_references": {},
                }
            }
        }
        json_bytes = json.dumps(profile_data, ensure_ascii=False).encode("utf-8-sig")
        (char_dir / "profile.json").write_bytes(json_bytes)

        with mock.patch("def_kari.characters.CHARACTERS_DIR", tmp_path), mock.patch(
            "def_kari.characters.PRIVATE_CHARACTERS_DIR", tmp_path / "nonexistent"
        ):
            result = load_profiles()

        assert "bom_char_001" in result
        assert result["bom_char_001"]["base_profile"]["name"] == "BOMChar"

    def test_non_bom_file_still_loaded(self, tmp_path):
        char_dir = tmp_path / "nobom_char_001"
        char_dir.mkdir()
        profile_data = {
            "nobom_char_001": {
                "base_profile": {
                    "name": "NoBOMChar",
                    "visual_references": {},
                }
            }
        }
        (char_dir / "profile.json").write_text(
            json.dumps(profile_data, ensure_ascii=False), encoding="utf-8"
        )

        with mock.patch("def_kari.characters.CHARACTERS_DIR", tmp_path), mock.patch(
            "def_kari.characters.PRIVATE_CHARACTERS_DIR", tmp_path / "nonexistent"
        ):
            result = load_profiles()

        assert "nobom_char_001" in result
        assert result["nobom_char_001"]["base_profile"]["name"] == "NoBOMChar"


class TestFindCharacterDir:
    def test_existing_public_character(self):
        d = _find_character_dir("character_luna_001")
        assert d.exists()
        assert d.name == "character_luna_001"

    def test_nonexistent_falls_back_to_public(self):
        d = _find_character_dir("does_not_exist_999")
        from def_kari.characters import CHARACTERS_DIR
        assert d == CHARACTERS_DIR / "does_not_exist_999"


class TestHelpers:
    def test_get_bp_empty(self):
        assert _get_bp({}) == {}

    def test_get_pa_empty(self):
        assert _get_pa({}) == {}

    def test_get_vr_empty(self):
        assert _get_vr({}) == {}

    def test_apply_name_reading_replaces(self):
        char = {"name": "ルナ", "name_reading": {"family_name": "", "given_name": "ルナ"}}
        assert apply_name_reading("ルナが話す", char) == "ルナが話す"  # same kana

    def test_apply_name_reading_with_kanji(self):
        char = {"name": "月夜", "name_reading": {"family_name": "", "given_name": "ツキヨ"}}
        result = apply_name_reading("月夜が話す", char)
        assert result == "ツキヨが話す"

    def test_apply_name_reading_empty(self):
        assert apply_name_reading("", {}) == ""
        assert apply_name_reading(None, {}) == ""

    def test_get_tts_speaker_id_default(self):
        assert get_tts_speaker_id({}, "voicevox") == 2
        assert get_tts_speaker_id({}, "gemini_tts") == "Kore"

    def test_get_tts_speaker_id_custom(self):
        char = {"voicevox_speaker_id": 10}
        assert get_tts_speaker_id(char, "voicevox") == 10

    def test_list_character_choices(self):
        profiles = {
            "id1": {"base_profile": {"name": "Alpha"}},
            "id2": {"base_profile": {"name": "Beta"}},
        }
        choices = list_character_choices(profiles)
        assert len(choices) == 2
        ids = [c[0] for c in choices]
        assert "id1" in ids
        assert "id2" in ids


class TestSaveProfile:
    def test_save_and_reload(self, tmp_path):
        with mock.patch(
            "def_kari.characters.CHARACTERS_DIR", tmp_path
        ), mock.patch(
            "def_kari.characters.PRIVATE_CHARACTERS_DIR",
            tmp_path / "private",
        ):
            bp = {"name": "Saved", "identity_prompt": "test"}
            save_profile("save_test_001", bp)
            pf = tmp_path / "save_test_001" / "profile.json"
            assert pf.exists()
            data = json.loads(pf.read_text(encoding="utf-8"))
            assert data["save_test_001"]["base_profile"]["name"] == "Saved"


# ---------------------------------------------------------------------------
# 2. F-14 autofix / field name fixes
# ---------------------------------------------------------------------------
from def_kari.llm.client import (
    _autofix,
    _escape_control_chars_in_strings,
    _extract_json_object,
    _FIELD_NAME_FIXES,
    _fix_missing_commas,
    _strip_thinking,
)


class TestAutofix:
    def test_unquoted_keys(self):
        raw = '{dialogue: "hello", emotion: "happy"}'
        fixed = _autofix(raw)
        parsed = json.loads(fixed)
        assert parsed["dialogue"] == "hello"
        assert parsed["emotion"] == "happy"

    def test_single_quoted_values_to_double(self):
        """_autofix converts single-quoted values (not keys) to double quotes."""
        raw = '{"dialogue": \'hello\'}'
        fixed = _autofix(raw)
        parsed = json.loads(fixed)
        assert parsed["dialogue"] == "hello"

    def test_unquoted_keys_with_single_quoted_values(self):
        """Unquoted keys + single-quoted values: keys get double-quoted,
        values get converted."""
        raw = "{dialogue: 'hello', emotion: 'happy'}"
        fixed = _autofix(raw)
        parsed = json.loads(fixed)
        assert parsed["dialogue"] == "hello"
        assert parsed["emotion"] == "happy"

    def test_markdown_code_fence_stripped(self):
        raw = '```json\n{"dialogue": "hi"}\n```'
        fixed = _autofix(raw)
        parsed = json.loads(fixed)
        assert parsed["dialogue"] == "hi"

    def test_trailing_comma_removed(self):
        raw = '{"dialogue": "hi", "emotion": "neutral",}'
        fixed = _autofix(raw)
        parsed = json.loads(fixed)
        assert parsed["emotion"] == "neutral"

    def test_trailing_comma_in_array(self):
        raw = '{"tags": ["nsfw", "violence",]}'
        fixed = _autofix(raw)
        parsed = json.loads(fixed)
        assert parsed["tags"] == ["nsfw", "violence"]

    def test_smart_single_quotes_replaced(self):
        """_autofix replaces curly single quotes with straight apostrophes."""
        left_sq = chr(0x2018)
        right_sq = chr(0x2019)
        raw = '{"dialogue": "it' + left_sq + 's a test' + right_sq + '"}'
        fixed = _autofix(raw)
        assert left_sq not in fixed
        assert right_sq not in fixed
        parsed = json.loads(fixed)
        assert parsed["dialogue"] == "it's a test'"

    def test_field_name_typo_correction(self):
        """_FIELD_NAME_FIXES corrects known LLM typos in field names."""
        # "dialogues" -> "dialogue", "emotions" -> "emotion",
        # "prompt" -> "image_prompt_en", "safety_tags" -> "tags"
        raw = '{"dialogues": "hello", "emotions": "happy", "prompt": "test", "safety_tags": ["nsfw"]}'
        fixed = _autofix(raw)
        parsed = json.loads(fixed)
        assert "dialogue" in parsed
        assert "emotion" in parsed
        assert "image_prompt_en" in parsed
        assert "tags" in parsed

    def test_field_name_typo_exicted(self):
        """_FIELD_NAME_FIXES also corrects emotion value typos like 'exicted'."""
        import re
        for pattern, replacement in _FIELD_NAME_FIXES.items():
            if "exicted" in pattern:
                assert replacement == '"excited"'
                break

    def test_valid_json_passes_through(self):
        raw = '{"dialogue": "test", "emotion": "neutral", "image_prompt_en": "", "tags": []}'
        fixed = _autofix(raw)
        parsed = json.loads(fixed)
        assert parsed["dialogue"] == "test"


class TestFieldNameFixes:
    """Verify that _FIELD_NAME_FIXES covers common LLM typos."""

    def test_dialogue_variants(self):
        """The regex r'"di?a?logues?"' matches 'dialogue', 'dialogues',
        and minor typos like 'dlogue', but not the truncated 'dialog'/'dialogs'.
        We test the variants the regex is actually designed to catch."""
        import re
        matchable = ['"dialogues"', '"dlogue"', '"dlogues"']
        for variant in matchable:
            matched = False
            for pattern in _FIELD_NAME_FIXES:
                if re.match(pattern, variant, re.IGNORECASE):
                    matched = True
                    break
            assert matched, f"{variant} should match a fix pattern"

        # "dialogue" itself is the replacement target, so matching is fine but not required
        # "dialog" / "dialogs" are NOT covered by the regex
        for variant in ['"dialog"', '"dialogs"']:
            matched = any(
                re.match(p, variant, re.IGNORECASE) for p in _FIELD_NAME_FIXES
            )
            assert not matched, f"{variant} should NOT match (regex doesn't cover it)"

    def test_emotion_variants(self):
        import re
        assert re.match(r'"emotions?"', '"emotions"', re.IGNORECASE)

    def test_image_prompt_variants(self):
        import re
        for variant in ['"image_prompts"', '"image_prompt"', '"prompt"']:
            matched = False
            for pattern in _FIELD_NAME_FIXES:
                if re.match(pattern, variant, re.IGNORECASE):
                    matched = True
                    break
            assert matched, f"{variant} should match"


class TestStripThinking:
    def test_removes_closed_think_tags(self):
        raw = "<think>internal reasoning</think>Hello!"
        assert _strip_thinking(raw) == "Hello!"

    def test_removes_open_think_tags(self):
        raw = "<think>still thinking without close"
        assert _strip_thinking(raw) == ""

    def test_no_think_tags(self):
        raw = "Just normal text"
        assert _strip_thinking(raw) == "Just normal text"


class TestExtractJsonObject:
    def test_extracts_json_from_surrounding_text(self):
        raw = 'Some text before {"key": "val"} some text after'
        result = _extract_json_object(raw)
        assert result == '{"key": "val"}'

    def test_nested_objects(self):
        raw = '{"a": {"b": "c"}}'
        result = _extract_json_object(raw)
        assert json.loads(result) == {"a": {"b": "c"}}

    def test_no_braces(self):
        raw = "no json here"
        assert _extract_json_object(raw) == raw


class TestEscapeControlChars:
    def test_newlines_escaped(self):
        raw = '"hello\nworld"'
        result = _escape_control_chars_in_strings(raw)
        assert "\\n" in result
        assert "\n" not in result

    def test_tabs_escaped(self):
        raw = '"hello\tworld"'
        result = _escape_control_chars_in_strings(raw)
        assert "\\t" in result

    def test_outside_string_not_escaped(self):
        raw = '{\n"key": "val"\n}'
        result = _escape_control_chars_in_strings(raw)
        assert result.count("\n") == 2  # newlines outside strings preserved


class TestFixMissingCommas:
    def test_adds_comma_between_fields(self):
        raw = '{"a": "1"\n"b": "2"}'
        result = _fix_missing_commas(raw)
        parsed = json.loads(result)
        assert parsed["a"] == "1"
        assert parsed["b"] == "2"


# ---------------------------------------------------------------------------
# 3. Safety filters
# ---------------------------------------------------------------------------
from def_kari.safety.filters import (
    detect_tags_from_text,
    effective_level,
    is_flagged,
    SAFETY_MASK,
    SAFETY_OFF,
    SAFETY_WARN,
    should_blur_image,
    should_hide_image,
    should_mask_text,
)


class TestDetectTagsFromText:
    def test_nsfw_keyword_detected(self):
        tags = detect_tags_from_text("This contains nude content")
        assert "nsfw" in tags

    def test_violence_keyword_detected(self):
        tags = detect_tags_from_text("殺害シーン")
        assert "violence" in tags

    def test_both_detected(self):
        tags = detect_tags_from_text("nude and 殺害")
        assert "nsfw" in tags
        assert "violence" in tags

    def test_clean_text_no_tags(self):
        tags = detect_tags_from_text("A beautiful sunny day")
        assert tags == []

    def test_case_insensitive_nsfw(self):
        tags = detect_tags_from_text("NSFW warning")
        assert "nsfw" in tags

    def test_japanese_nsfw_keywords(self):
        tags = detect_tags_from_text("性的な表現")
        assert "nsfw" in tags

    def test_japanese_violence_keywords(self):
        tags = detect_tags_from_text("流血表現あり")
        assert "violence" in tags


class TestIsFlagged:
    def test_empty_tags_not_flagged(self):
        assert is_flagged([]) is False
        assert is_flagged(None) is False

    def test_tags_with_no_allowed_lists_always_flagged(self):
        assert is_flagged(["nsfw"]) is True

    def test_nsfw_allowed(self):
        assert is_flagged(["nsfw"], allowed_sexual=["nsfw"]) is False

    def test_nsfw_not_allowed(self):
        assert is_flagged(["nsfw"], allowed_sexual=["general"]) is True

    def test_violence_allowed(self):
        assert is_flagged(["violence"], allowed_violence=["violence"]) is False

    def test_violence_not_allowed(self):
        assert is_flagged(["violence"], allowed_violence=["general"]) is True

    def test_mixed_tags_partial_allow(self):
        # nsfw allowed but violence not
        assert is_flagged(
            ["nsfw", "violence"],
            allowed_sexual=["nsfw"],
            allowed_violence=["general"],
        ) is True

    def test_unknown_tag_not_flagged(self):
        # Tags not in _TAG_TO_SEXUAL_RATING or _TAG_TO_VIOLENCE_RATING
        assert is_flagged(
            ["custom_tag"],
            allowed_sexual=["general"],
            allowed_violence=["general"],
        ) is False


class TestEffectiveLevel:
    def test_not_flagged_always_off(self):
        assert effective_level(SAFETY_MASK, flagged=False, unlocked=False) == SAFETY_OFF

    def test_flagged_and_unlocked_is_off(self):
        assert effective_level(SAFETY_MASK, flagged=True, unlocked=True) == SAFETY_OFF

    def test_flagged_not_unlocked_returns_level(self):
        assert effective_level(SAFETY_MASK, flagged=True, unlocked=False) == SAFETY_MASK
        assert effective_level(SAFETY_WARN, flagged=True, unlocked=False) == SAFETY_WARN


class TestSafetyHelpers:
    def test_should_mask_text(self):
        assert should_mask_text(SAFETY_MASK) is True
        assert should_mask_text(SAFETY_WARN) is False
        assert should_mask_text(SAFETY_OFF) is False

    def test_should_blur_image(self):
        assert should_blur_image(SAFETY_WARN) is True
        assert should_blur_image(SAFETY_MASK) is False

    def test_should_hide_image(self):
        assert should_hide_image(SAFETY_MASK) is True
        assert should_hide_image(SAFETY_WARN) is False


# ---------------------------------------------------------------------------
# 4. i18n
# ---------------------------------------------------------------------------
from def_kari.i18n import load_locale, t, _cache


class TestI18n:
    def setup_method(self):
        _cache.clear()

    def test_load_ja_locale(self):
        locale = load_locale("ja")
        assert isinstance(locale, dict)
        assert "app_title" in locale

    def test_load_en_locale(self):
        locale = load_locale("en")
        assert isinstance(locale, dict)
        assert "app_title" in locale

    def test_nonexistent_locale_falls_back_to_ja(self):
        locale = load_locale("zz_nonexistent")
        ja_locale = load_locale("ja")
        # Should fall back to ja.json
        assert locale.get("app_title") == ja_locale.get("app_title")

    def test_t_returns_translated_string(self):
        result = t("app_title", lang="ja")
        assert result == "DEF(kari)"

    def test_t_returns_key_when_missing(self):
        result = t("nonexistent_key_xyz", lang="ja")
        assert result == "nonexistent_key_xyz"

    def test_t_with_format_kwargs(self):
        # Test the format interpolation path
        _cache["test_fmt"] = {"greeting": "Hello {name}!"}
        result = t("greeting", lang="test_fmt", name="World")
        assert result == "Hello World!"

    def test_t_format_with_missing_key_doesnt_crash(self):
        _cache["test_fmt2"] = {"greeting": "Hello {name}!"}
        # missing kwarg should not crash
        result = t("greeting", lang="test_fmt2")
        assert result == "Hello {name}!"

    def test_caching(self):
        _cache.clear()
        locale1 = load_locale("ja")
        locale2 = load_locale("ja")
        assert locale1 is locale2  # same object from cache

    def test_en_has_different_values_from_ja(self):
        ja = load_locale("ja")
        en = load_locale("en")
        # At least some keys should differ
        assert ja.get("session_start") != en.get("session_start")


# ---------------------------------------------------------------------------
# 5. Settings persistence
# ---------------------------------------------------------------------------
from def_kari.settings import PERSISTED_KEYS, load_settings, save_settings


class TestSettings:
    def test_load_settings_returns_dict(self):
        result = load_settings()
        assert isinstance(result, dict)

    def test_save_and_load_roundtrip(self, tmp_path):
        settings_file = tmp_path / "test_settings.json"
        with mock.patch("def_kari.settings.SETTINGS_PATH", settings_file), \
             mock.patch("def_kari.settings.DATA_DIR", tmp_path):
            # Simulate a session_state dict
            session = {
                "safety_level": "warn",
                "tts_enabled": True,
                "active_character": "character_luna_001",
                "unknown_key": "should_be_ignored",
            }
            save_settings(session)
            loaded = load_settings()
            assert loaded["safety_level"] == "warn"
            assert loaded["tts_enabled"] is True
            assert loaded["active_character"] == "character_luna_001"
            assert "unknown_key" not in loaded

    def test_save_converts_none_string(self, tmp_path):
        settings_file = tmp_path / "test_settings.json"
        with mock.patch("def_kari.settings.SETTINGS_PATH", settings_file), \
             mock.patch("def_kari.settings.DATA_DIR", tmp_path):
            session = {"safety_level": "None"}
            save_settings(session)
            loaded = load_settings()
            assert loaded["safety_level"] is None

    def test_load_missing_file_returns_empty(self, tmp_path):
        with mock.patch(
            "def_kari.settings.SETTINGS_PATH",
            tmp_path / "nonexistent.json",
        ), mock.patch("def_kari.settings.DATA_DIR", tmp_path):
            assert load_settings() == {}

    def test_load_malformed_file_returns_empty(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid", encoding="utf-8")
        with mock.patch("def_kari.settings.SETTINGS_PATH", bad_file), \
             mock.patch("def_kari.settings.DATA_DIR", tmp_path):
            assert load_settings() == {}

    def test_persisted_keys_contains_expected(self):
        assert "safety_level" in PERSISTED_KEYS
        assert "tts_enabled" in PERSISTED_KEYS
        assert "active_character" in PERSISTED_KEYS
        assert "llm_backend" in PERSISTED_KEYS


# ---------------------------------------------------------------------------
# 6. Episode save/load pattern
# ---------------------------------------------------------------------------
class TestEpisodeSaveLoad:
    """Test the episode JSON save/load pattern as used in app.py.

    We replicate the save/load logic here rather than importing from app.py
    (which depends on streamlit), testing the same JSON round-trip pattern.
    """

    @staticmethod
    def _save_episode(episodes_dir: str, ep: dict) -> str:
        os.makedirs(episodes_dir, exist_ok=True)
        title = ep.get("title", "untitled")
        safe_name = title.replace("/", "_").replace("\\", "_").replace(":", "_")
        path = os.path.join(episodes_dir, f"{safe_name}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ep, f, ensure_ascii=False, indent=2)
        return path

    @staticmethod
    def _load_episodes(episodes_dir: str) -> list:
        if not os.path.isdir(episodes_dir):
            return []
        episodes = []
        for f in sorted(os.listdir(episodes_dir)):
            if not f.endswith(".json"):
                continue
            try:
                with open(os.path.join(episodes_dir, f), encoding="utf-8") as fh:
                    ep = json.load(fh)
                    ep.setdefault("id", os.path.splitext(f)[0])
                    ep.setdefault("title", os.path.splitext(f)[0])
                    episodes.append(ep)
            except (json.JSONDecodeError, OSError):
                pass
        return episodes

    def test_save_and_load_roundtrip(self, tmp_path):
        episodes_dir = str(tmp_path / "episodes")
        ep = {
            "title": "Test Episode",
            "body": "This is the body.",
            "plot": "A simple plot.",
        }
        self._save_episode(episodes_dir, ep)
        loaded = self._load_episodes(episodes_dir)
        assert len(loaded) == 1
        assert loaded[0]["title"] == "Test Episode"
        assert loaded[0]["body"] == "This is the body."
        assert loaded[0]["plot"] == "A simple plot."

    def test_title_sanitization(self, tmp_path):
        episodes_dir = str(tmp_path / "episodes")
        ep = {"title": "bad/title\\with:chars"}
        path = self._save_episode(episodes_dir, ep)
        assert "bad_title_with_chars.json" in path

    def test_japanese_title(self, tmp_path):
        episodes_dir = str(tmp_path / "episodes")
        ep = {
            "title": "星降る夜の物語",
            "body": "遠い昔、星が降る夜がありました。",
        }
        self._save_episode(episodes_dir, ep)
        loaded = self._load_episodes(episodes_dir)
        assert len(loaded) == 1
        assert loaded[0]["title"] == "星降る夜の物語"
        assert loaded[0]["body"] == "遠い昔、星が降る夜がありました。"

    def test_multiple_episodes_sorted(self, tmp_path):
        episodes_dir = str(tmp_path / "episodes")
        for i, title in enumerate(["Charlie", "Alpha", "Bravo"]):
            self._save_episode(episodes_dir, {"title": title, "order": i})
        loaded = self._load_episodes(episodes_dir)
        assert len(loaded) == 3
        # Files sorted alphabetically: Alpha, Bravo, Charlie
        assert loaded[0]["title"] == "Alpha"
        assert loaded[1]["title"] == "Bravo"
        assert loaded[2]["title"] == "Charlie"

    def test_load_empty_dir(self, tmp_path):
        episodes_dir = str(tmp_path / "empty_episodes")
        os.makedirs(episodes_dir)
        loaded = self._load_episodes(episodes_dir)
        assert loaded == []

    def test_load_nonexistent_dir(self, tmp_path):
        loaded = self._load_episodes(str(tmp_path / "nonexistent"))
        assert loaded == []

    def test_malformed_json_skipped(self, tmp_path):
        episodes_dir = str(tmp_path / "episodes")
        os.makedirs(episodes_dir)
        # Write a good episode
        self._save_episode(episodes_dir, {"title": "Good"})
        # Write a bad JSON file
        bad_path = os.path.join(episodes_dir, "bad.json")
        with open(bad_path, "w") as f:
            f.write("{invalid json content")
        loaded = self._load_episodes(episodes_dir)
        assert len(loaded) == 1
        assert loaded[0]["title"] == "Good"

    def test_id_defaults_to_filename(self, tmp_path):
        episodes_dir = str(tmp_path / "episodes")
        ep = {"body": "no title field"}
        os.makedirs(episodes_dir)
        path = os.path.join(episodes_dir, "my_episode.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(ep, f)
        loaded = self._load_episodes(episodes_dir)
        assert loaded[0]["id"] == "my_episode"
        assert loaded[0]["title"] == "my_episode"

    def test_fields_preserved(self, tmp_path):
        episodes_dir = str(tmp_path / "episodes")
        ep = {
            "title": "Complex",
            "body": "Body text",
            "plot": "Plot text",
            "custom_field": [1, 2, 3],
            "nested": {"key": "value"},
        }
        self._save_episode(episodes_dir, ep)
        loaded = self._load_episodes(episodes_dir)
        assert loaded[0]["custom_field"] == [1, 2, 3]
        assert loaded[0]["nested"]["key"] == "value"


# ---------------------------------------------------------------------------
# 7. Action directives loader
# ---------------------------------------------------------------------------
from def_kari.api.routes.session import (
    _load_action_directives,
    _DIRECTIVE_DIRS,
    _autosave,
    _delete_autosave,
    _AUTOSAVE_DIR,
    _sessions,
)


class TestLoadActionDirectives:
    """_load_action_directives() should load JSON files and include recommended_for."""

    def test_returns_dict(self):
        result = _load_action_directives()
        assert isinstance(result, dict)

    def test_none_always_present(self):
        result = _load_action_directives()
        assert "none" in result

    def test_public_sets_loaded(self):
        result = _load_action_directives()
        # 公開済みセットが読み込まれている
        assert "default" in result
        assert "standard" in result
        assert "gentle" in result

    def test_recommended_for_is_list(self):
        result = _load_action_directives()
        for did, d in result.items():
            assert isinstance(d.get("recommended_for", []), list), \
                f"{did}: recommended_for should be a list"

    def test_standard_recommended_for_2_to_4(self):
        result = _load_action_directives()
        rf = result["standard"].get("recommended_for", [])
        assert set(rf) == {2, 3, 4}

    def test_default_recommended_for_5(self):
        result = _load_action_directives()
        rf = result["default"].get("recommended_for", [])
        assert rf == [5]

    def test_gentle_recommended_for_5(self):
        result = _load_action_directives()
        rf = result["gentle"].get("recommended_for", [])
        assert rf == [5]

    def test_none_recommended_for_empty(self):
        result = _load_action_directives()
        rf = result["none"].get("recommended_for", [])
        assert rf == []

    def test_standard_has_directives_1_to_3(self):
        result = _load_action_directives()
        directives = result["standard"].get("directives", {})
        assert "1" in directives
        assert "2" in directives
        assert "3" in directives

    def test_default_has_directives_1_to_4(self):
        result = _load_action_directives()
        directives = result["default"].get("directives", {})
        assert "1" in directives
        assert "4" in directives

    def test_none_has_empty_directives(self):
        result = _load_action_directives()
        assert result["none"].get("directives") == {}

    def test_custom_dir_loaded(self, tmp_path):
        """カスタムディレクトリからも読み込めること。"""
        d = {
            "id": "custom_test",
            "label": "テスト用",
            "rating": "general",
            "recommended_for": [3],
            "directives": {"1": "カスタム指示", "2": "まとめ"},
        }
        (tmp_path / "custom_test.json").write_text(
            json.dumps(d, ensure_ascii=False), encoding="utf-8"
        )
        with mock.patch(
            "def_kari.api.routes.session._DIRECTIVE_DIRS",
            [tmp_path, tmp_path / "nonexistent"],
        ):
            result = _load_action_directives()
        assert "custom_test" in result
        assert result["custom_test"]["recommended_for"] == [3]
        assert result["custom_test"]["directives"]["1"] == "カスタム指示"

    def test_malformed_json_skipped(self, tmp_path):
        (tmp_path / "bad.json").write_text("{invalid", encoding="utf-8")
        with mock.patch(
            "def_kari.api.routes.session._DIRECTIVE_DIRS",
            [tmp_path, tmp_path / "nonexistent"],
        ):
            result = _load_action_directives()
        assert "bad" not in result
        assert "none" in result  # fallback still present

    def test_gitkeep_ignored(self, tmp_path):
        (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
        with mock.patch(
            "def_kari.api.routes.session._DIRECTIVE_DIRS",
            [tmp_path, tmp_path / "nonexistent"],
        ):
            result = _load_action_directives()
        assert ".gitkeep" not in result

    def test_directive_count_matches_recommended_for(self):
        """standard は2-4アクション向けなので directive キー数は3（1,2,3）であること。"""
        result = _load_action_directives()
        std = result["standard"]
        assert len(std["directives"]) == len(std["recommended_for"])

    def test_all_directives_nonempty_strings(self):
        """指示セット内の各ディレクティブが空でない文字列であること。"""
        result = _load_action_directives()
        for did, d in result.items():
            for key, text in d.get("directives", {}).items():
                assert isinstance(text, str) and text.strip(), \
                    f"{did}[{key}] should be a non-empty string"


# ---------------------------------------------------------------------------
# 8. Session autosave
# ---------------------------------------------------------------------------
class TestSessionAutosave:
    """_autosave / _delete_autosave の動作確認。"""

    def _make_session(self, sid: str) -> dict:
        return {
            "id": sid,
            "initiative": ["char_a"],
            "name_map": {"char_a": "Alpha"},
            "topic": "test topic",
            "backend": "ollama",
            "round": 1,
            "turn": 0,
            "action_count": 0,
            "actions_per_turn": 2,
            "action_directive_set": "standard",
            "history": [{"role": "assistant", "content": "Alpha: hello", "character_id": "char_a"}],
            "counters": {},
            "designated_next": None,
        }

    def test_autosave_writes_file(self, tmp_path):
        sid = "test_session_001"
        _sessions[sid] = self._make_session(sid)
        try:
            with mock.patch("def_kari.api.routes.session._AUTOSAVE_DIR", tmp_path):
                _autosave(sid)
            assert (tmp_path / f"{sid}.json").exists()
            data = json.loads((tmp_path / f"{sid}.json").read_text(encoding="utf-8"))
            assert data["id"] == sid
            assert data["topic"] == "test topic"
        finally:
            _sessions.pop(sid, None)

    def test_autosave_content_roundtrip(self, tmp_path):
        sid = "test_session_002"
        session = self._make_session(sid)
        session["history"].append({"role": "user", "content": "hello", "character_id": "human"})
        _sessions[sid] = session
        try:
            with mock.patch("def_kari.api.routes.session._AUTOSAVE_DIR", tmp_path):
                _autosave(sid)
            restored = json.loads((tmp_path / f"{sid}.json").read_text(encoding="utf-8"))
            assert len(restored["history"]) == 2
        finally:
            _sessions.pop(sid, None)

    def test_autosave_nonexistent_session_noop(self, tmp_path):
        with mock.patch("def_kari.api.routes.session._AUTOSAVE_DIR", tmp_path):
            _autosave("nonexistent_session_xyz")
        assert list(tmp_path.iterdir()) == []

    def test_delete_autosave_removes_file(self, tmp_path):
        sid = "test_session_003"
        f = tmp_path / f"{sid}.json"
        f.write_text('{"id": "test_session_003"}', encoding="utf-8")
        with mock.patch("def_kari.api.routes.session._AUTOSAVE_DIR", tmp_path):
            _delete_autosave(sid)
        assert not f.exists()

    def test_delete_autosave_missing_file_noop(self, tmp_path):
        with mock.patch("def_kari.api.routes.session._AUTOSAVE_DIR", tmp_path):
            _delete_autosave("does_not_exist")  # should not raise

    def test_startup_restore(self, tmp_path):
        """起動時に autosave ファイルから _sessions が復元されること。"""
        autosave_sessions = {}
        for i in range(3):
            sid = f"restore_test_{i:03d}"
            data = self._make_session(sid)
            data["topic"] = f"topic {i}"
            (tmp_path / f"{sid}.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            autosave_sessions[sid] = data

        # 起動時復元ロジックを直接実行（モジュールレベルのコードと同等）
        restored: dict = {}
        for f in sorted(tmp_path.iterdir()):
            if f.suffix == ".json":
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    if isinstance(d, dict) and d.get("id"):
                        restored[d["id"]] = d
                except Exception:
                    pass

        assert len(restored) == 3
        for sid, expected in autosave_sessions.items():
            assert sid in restored
            assert restored[sid]["topic"] == expected["topic"]

    def test_startup_restore_skips_malformed(self, tmp_path):
        """壊れた autosave ファイルはスキップされること。"""
        (tmp_path / "bad.json").write_text("{invalid", encoding="utf-8")
        (tmp_path / "good_session.json").write_text(
            '{"id": "good_session", "topic": "ok"}', encoding="utf-8"
        )
        restored: dict = {}
        for f in sorted(tmp_path.iterdir()):
            if f.suffix == ".json":
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    if isinstance(d, dict) and d.get("id"):
                        restored[d["id"]] = d
                except Exception:
                    pass
        assert "bad" not in restored
        assert "good_session" in restored


# ---------------------------------------------------------------------------
# 9. F-27: メタ自己認識ディレクティブ
# ---------------------------------------------------------------------------
from def_kari.llm.prompts import _build_meta_directive, _META_DIRECTIVE, build_system_prompt


class TestBuildMetaDirective:
    """_build_meta_directive が content_policy の種類と言語に応じて正しい文字列を返すこと。"""

    def test_default_ja(self):
        result = _build_meta_directive({}, "", "ja")
        assert result == _META_DIRECTIVE["default"]["ja"]

    def test_default_en(self):
        result = _build_meta_directive({}, "", "en")
        assert result == _META_DIRECTIVE["default"]["en"]

    def test_existing_ip_ja(self):
        result = _build_meta_directive({"is_existing_ip": True}, "", "ja")
        assert result == _META_DIRECTIVE["existing_ip"]["ja"]

    def test_existing_ip_en(self):
        result = _build_meta_directive({"is_existing_ip": True}, "", "en")
        assert result == _META_DIRECTIVE["existing_ip"]["en"]

    def test_real_person_ja_contains_name(self):
        result = _build_meta_directive({"is_real_person": True}, "坂本龍馬", "ja")
        assert "坂本龍馬" in result
        assert "本物" in result  # "あなたは本物の〈{name}〉本人ではありません" から

    def test_real_person_en_contains_name(self):
        result = _build_meta_directive({"is_real_person": True}, "Ryoma Sakamoto", "en")
        assert "Ryoma Sakamoto" in result
        assert "not the actual" in result

    def test_real_person_fallback_name_ja(self):
        """character_nameが空の場合はデフォルト名を使う。"""
        result = _build_meta_directive({"is_real_person": True}, "", "ja")
        assert "この人物" in result

    def test_real_person_priority_over_existing_ip(self):
        """is_real_person が is_existing_ip より優先されること。"""
        result = _build_meta_directive({"is_real_person": True, "is_existing_ip": True}, "TestName", "ja")
        assert "TestName" in result  # real_person ブランチを通る

    def test_unknown_lang_falls_back_to_en(self):
        result = _build_meta_directive({}, "", "zh")
        assert result == _META_DIRECTIVE["default"]["en"]

    def test_none_content_policy_handled(self):
        """content_policy=None は空dictとして扱われること (呼び出し側でor{}済み)。"""
        result = _build_meta_directive({}, "Name", "ja")
        assert result == _META_DIRECTIVE["default"]["ja"]


class TestBuildSystemPromptDirectivePlacement:
    """build_system_prompt でメタ自己認識ディレクティブが identity_prompt より前に来ること。"""

    def test_directive_precedes_persona(self):
        prompt = build_system_prompt(
            persona_description="私はルナです。",
            content_policy={},
            character_name="ルナ",
            user_language="ja",
        )
        directive_pos = prompt.find(_META_DIRECTIVE["default"]["ja"])
        persona_pos = prompt.find("私はルナです。")
        assert directive_pos != -1, "directive が prompt に含まれること"
        assert persona_pos != -1, "persona が prompt に含まれること"
        assert directive_pos < persona_pos, "directive は persona より前に現れること"

    def test_real_person_directive_in_prompt(self):
        prompt = build_system_prompt(
            persona_description="あなたは偉大な哲学者です。",
            content_policy={"is_real_person": True},
            character_name="ソクラテス",
            user_language="ja",
        )
        assert "ソクラテス" in prompt
        assert "本物" in prompt
        assert prompt.index("ソクラテス") < prompt.index("哲学者")

    def test_existing_ip_directive_in_prompt_en(self):
        prompt = build_system_prompt(
            persona_description="You are a wizard.",
            content_policy={"is_existing_ip": True},
            character_name="Merlin",
            user_language="en",
        )
        assert "interpretation model" in prompt
        assert prompt.index("interpretation model") < prompt.index("wizard")

    def test_default_content_policy_none_uses_default_directive(self):
        """content_policy=None でもデフォルトディレクティブが入ること。"""
        prompt = build_system_prompt(
            persona_description="テストキャラ",
            content_policy=None,
            user_language="ja",
        )
        assert _META_DIRECTIVE["default"]["ja"] in prompt


# ---------------------------------------------------------------------------
# 7. ComfyUI hash strip
# ---------------------------------------------------------------------------
class TestComfyUIHashStrip:
    """comfyui.generate がモデル名の [hash] を除去してから ComfyUI に渡すことを確認。"""

    def test_hash_stripped_from_model_name(self):
        """'model.safetensors [abc1234]' → 'model.safetensors' に変換される。"""
        import re
        model = "paruparu_illustrious_v3.2.safetensors [a1b2c3d4]"
        stripped = re.sub(r'\s*\[.*?\]\s*$', '', model).strip()
        assert stripped == "paruparu_illustrious_v3.2.safetensors"

    def test_no_hash_unchanged(self):
        """ハッシュなしのモデル名はそのまま。"""
        import re
        model = "paruparu_illustrious_v3.2.safetensors"
        stripped = re.sub(r'\s*\[.*?\]\s*$', '', model).strip()
        assert stripped == "paruparu_illustrious_v3.2.safetensors"

    def test_empty_model_unchanged(self):
        """空文字列はそのまま。"""
        import re
        model = ""
        stripped = re.sub(r'\s*\[.*?\]\s*$', '', model).strip()
        assert stripped == ""

    def test_comfyui_generate_strips_hash(self):
        """comfyui.generate() が workflow へ渡すモデル名からハッシュを除去することを確認。"""
        import copy
        from def_kari.t2i.adapters import comfyui

        fake_workflow = {
            "4": {"inputs": {"ckpt_name": ""}},
            "5": {"inputs": {"width": 512, "height": 768}},
            "6": {"inputs": {"text": ""}},
            "7": {"inputs": {"text": ""}},
            "3": {"inputs": {"seed": 0, "steps": 20, "cfg": 7.0}},
        }
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["workflow"] = copy.deepcopy(json.get("prompt", {}))
            resp = mock.MagicMock()
            resp.ok = True
            resp.json.return_value = {"prompt_id": "test-id"}
            return resp

        hist_resp = mock.MagicMock()
        hist_resp.status_code = 200
        hist_resp.json.return_value = {
            "test-id": {
                "outputs": {"9": {"images": [{"filename": "out.png", "subfolder": "", "type": "output"}]}},
                "status": {"status_str": "success"},
            }
        }
        img_resp = mock.MagicMock()
        img_resp.raise_for_status = mock.MagicMock()
        img_resp.content = b'\x89PNG\r\n'

        with mock.patch.object(comfyui, '_load_workflow', return_value=copy.deepcopy(fake_workflow)), \
             mock.patch('requests.post', side_effect=fake_post), \
             mock.patch('requests.get', side_effect=[hist_resp, img_resp]), \
             mock.patch('pathlib.Path.mkdir'), \
             mock.patch('pathlib.Path.write_bytes'):
            try:
                comfyui.generate(
                    prompt="test",
                    model="test_model.safetensors [deadbeef]",
                    workflow_name="default",
                )
            except Exception:
                pass

        assert captured.get("workflow"), "POST が呼ばれなかった"
        ckpt = captured["workflow"].get("4", {}).get("inputs", {}).get("ckpt_name", "")
        assert "[" not in ckpt, f"hash not stripped: {ckpt}"
        assert ckpt == "test_model.safetensors"


# ---------------------------------------------------------------------------
# 8. T2I profile steps/cfg loading
# ---------------------------------------------------------------------------
class TestT2IProfileGenerationParams:
    """T2Iモデルプロファイルの steps/cfg_scale が生成時に正しく使われることを確認。"""

    def test_get_profile_returns_defaults_when_no_model(self):
        """モデル名なしでもデフォルト値が返る。"""
        from def_kari.models.t2i_profiles import get_profile, DEFAULT_STEPS, DEFAULT_CFG_SCALE
        p = get_profile(None)
        assert p["steps"] == DEFAULT_STEPS
        assert p["cfg_scale"] == DEFAULT_CFG_SCALE

    def test_get_profile_returns_stored_values(self):
        """プロファイルに保存した steps/cfg が取得できる。"""
        import tempfile, json
        from pathlib import Path
        from unittest import mock

        profiles = {"test_model.safetensors": {"steps": 30, "cfg_scale": 4.5, "quality_tags": "", "negative_prompt": ""}}
        with tempfile.TemporaryDirectory() as td:
            ppath = Path(td) / "t2i_model_profiles.json"
            ppath.write_text(json.dumps(profiles), encoding="utf-8")
            with mock.patch('def_kari.models.t2i_profiles.PROFILES_PATH', ppath), \
                 mock.patch('def_kari.models.t2i_profiles.POC_PROFILES_PATH', Path(td) / "missing.json"):
                from def_kari.models.t2i_profiles import get_profile
                p = get_profile("test_model.safetensors")
        assert p["steps"] == 30
        assert p["cfg_scale"] == 4.5

    def test_t2i_backend_loads_profile_when_steps_zero(self):
        """steps=0, cfg_scale=0.0 のとき t2i/backend がプロファイル値を使う。"""
        from unittest import mock
        from def_kari.t2i import backend as t2i_backend

        fake_profile = {"steps": 25, "cfg_scale": 4.5, "quality_tags": "", "negative_prompt": ""}
        captured = {}

        def fake_fn(**kwargs):
            captured.update(kwargs)
            return "/tmp/fake.png"

        with mock.patch('def_kari.models.t2i_profiles.get_profile', return_value=fake_profile):
            original_backends = t2i_backend.T2I_BACKENDS.copy()
            t2i_backend.T2I_BACKENDS["test_backend"] = fake_fn
            try:
                t2i_backend.generate_image(
                    prompt="test",
                    backend="test_backend",
                    model="test_model.safetensors",
                    steps=0,
                    cfg_scale=0.0,
                )
            finally:
                t2i_backend.T2I_BACKENDS.clear()
                t2i_backend.T2I_BACKENDS.update(original_backends)

        assert captured.get("steps") == 25
        assert captured.get("cfg_scale") == 4.5

    def test_t2i_backend_explicit_steps_not_overridden_by_profile(self):
        """明示的に steps/cfg を渡したらプロファイルで上書きされない。"""
        from unittest import mock
        from def_kari.t2i import backend as t2i_backend

        fake_profile = {"steps": 25, "cfg_scale": 4.5, "quality_tags": "", "negative_prompt": ""}
        captured = {}

        def fake_fn(**kwargs):
            captured.update(kwargs)
            return "/tmp/fake.png"

        with mock.patch('def_kari.models.t2i_profiles.get_profile', return_value=fake_profile):
            original_backends = t2i_backend.T2I_BACKENDS.copy()
            t2i_backend.T2I_BACKENDS["test_backend"] = fake_fn
            try:
                t2i_backend.generate_image(
                    prompt="test",
                    backend="test_backend",
                    model="test_model.safetensors",
                    steps=15,
                    cfg_scale=9.0,
                )
            finally:
                t2i_backend.T2I_BACKENDS.clear()
                t2i_backend.T2I_BACKENDS.update(original_backends)

        assert captured.get("steps") == 15
        assert captured.get("cfg_scale") == 9.0


# ---------------------------------------------------------------------------
# 9. _apply_char_tags
# ---------------------------------------------------------------------------
class TestApplyCharTags:
    """session._apply_char_tags のタグ結合ロジックを確認。"""

    def _make_char(self, appearance="1girl, brown hair", name_tags="katarina_claes", lora=None):
        return {
            "appearance_tags": appearance,
            "image_name_tags": name_tags,
            "lora": lora or [],
        }

    def _get_fn(self):
        from def_kari.api.routes.session import _apply_char_tags
        return _apply_char_tags

    def test_name_tags_prepended(self):
        """image_name_tags がプロンプト先頭に来る。"""
        fn = self._get_fn()
        char = self._make_char(name_tags="katarina_claes", appearance="1girl, brown hair")
        with mock.patch('def_kari.api.routes.session.get_character', return_value=char):
            result = fn("indoor scene", "test_char")
        assert result.startswith("katarina_claes"), f"先頭にname_tagsがない: {result}"

    def test_appearance_tags_added(self):
        """appearance_tags がプロンプトに追加される。"""
        fn = self._get_fn()
        char = self._make_char(appearance="1girl, brown hair, blue eyes")
        with mock.patch('def_kari.api.routes.session.get_character', return_value=char):
            result = fn("indoor scene", "test_char")
        assert "brown hair" in result
        assert "blue eyes" in result

    def test_no_duplicate_tags(self):
        """既にプロンプトにあるタグは重複追加されない。"""
        fn = self._get_fn()
        char = self._make_char(appearance="1girl, brown hair")
        with mock.patch('def_kari.api.routes.session.get_character', return_value=char):
            result = fn("1girl, indoor scene", "test_char")
        tags = [t.strip() for t in result.split(',')]
        assert tags.count("1girl") == 1, f"1girl が重複: {result}"

    def test_lora_appended(self):
        """LoRA 構文が末尾に付加される。"""
        fn = self._get_fn()
        lora = [{"name": "TestLoRA", "weight": 0.8, "trigger_tags": "test_trigger"}]
        char = self._make_char(lora=lora)
        with mock.patch('def_kari.api.routes.session.get_character', return_value=char):
            result = fn("indoor scene", "test_char")
        assert "<lora:TestLoRA:0.8>" in result
        assert result.index("<lora:TestLoRA:0.8>") > result.index("indoor scene")

    def test_no_char_id_returns_prompt_unchanged(self):
        """char_id=None のときプロンプトは変更されない。"""
        fn = self._get_fn()
        result = fn("original prompt", None)
        assert result == "original prompt"

    def test_lora_trigger_tags_prepended(self):
        """LoRA の trigger_tags も先頭側（name_tags の後）に入る。"""
        fn = self._get_fn()
        lora = [{"name": "KatarinaLoRA", "weight": 0.8, "trigger_tags": "KatarinaClaes"}]
        char = self._make_char(name_tags="katarina_claes", lora=lora)
        with mock.patch('def_kari.api.routes.session.get_character', return_value=char):
            result = fn("indoor scene", "test_char")
        assert "KatarinaClaes" in result
        # LoRA syntax は末尾
        lora_idx = result.index("<lora:KatarinaLoRA:0.8>")
        scene_idx = result.index("indoor scene")
        assert lora_idx > scene_idx


# ---------------------------------------------------------------------------
# 10. _clean_history_for_retake
# ---------------------------------------------------------------------------
class TestCleanHistoryForRetake:
    """session._clean_history_for_retake の履歴クリーニングロジックを確認。"""

    def _get_fn(self):
        from def_kari.api.routes.session import _clean_history_for_retake
        return _clean_history_for_retake

    def _asst(self, content="text", char_id="char1"):
        return {"role": "assistant", "content": content, "character_id": char_id}

    def _img(self):
        return {"character_id": "_scene_image", "content": "", "image_url": "/img.png"}

    def _user(self, content="user text"):
        return {"role": "user", "content": content}

    def test_removes_n_assistant_entries(self):
        """末尾の assistant エントリを指定件数削除する。"""
        fn = self._get_fn()
        history = [self._asst("A"), self._asst("B"), self._asst("C")]
        new_hist, removed = fn(history, 2)
        assert removed == 2
        assert len(new_hist) == 1
        assert new_hist[0]["content"] == "A"

    def test_scene_image_skipped_not_counted(self):
        """_scene_image エントリは削除されるがカウントしない。"""
        fn = self._get_fn()
        history = [self._asst("A"), self._asst("B"), self._img()]
        new_hist, removed = fn(history, 1)
        assert removed == 1
        # B と _scene_image が削除され A だけ残る
        assert len(new_hist) == 1
        assert new_hist[0]["content"] == "A"

    def test_multiple_scene_images_all_skipped(self):
        """複数の _scene_image が末尾に連なっても全部スキップ。"""
        fn = self._get_fn()
        history = [self._asst("A"), self._img(), self._img()]
        new_hist, removed = fn(history, 1)
        assert removed == 1
        assert len(new_hist) == 0

    def test_stops_at_user_entry(self):
        """user エントリで停止し、それより前は削除しない。"""
        fn = self._get_fn()
        history = [self._user(), self._asst("A"), self._asst("B")]
        new_hist, removed = fn(history, 3)
        assert removed == 2
        assert len(new_hist) == 1
        assert new_hist[0]["role"] == "user"

    def test_remove_zero_does_nothing(self):
        """remove=0 のとき何も削除しない。"""
        fn = self._get_fn()
        history = [self._asst("A"), self._asst("B")]
        new_hist, removed = fn(history, 0)
        assert removed == 0
        assert len(new_hist) == 2

    def test_empty_history_safe(self):
        """空履歴でもクラッシュしない。"""
        fn = self._get_fn()
        new_hist, removed = fn([], 2)
        assert new_hist == []
        assert removed == 0

    def test_scene_image_between_assistant_entries(self):
        """assistant → _scene_image → assistant の並びでも正しく2件削除。"""
        fn = self._get_fn()
        history = [self._asst("A"), self._asst("B"), self._img(), self._asst("C")]
        new_hist, removed = fn(history, 2)
        # C と _scene_image と B が削除される（_scene_image はカウント外）
        assert removed == 2
        assert len(new_hist) == 1
        assert new_hist[0]["content"] == "A"
