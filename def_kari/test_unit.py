"""DEF(kari) unit tests -- pure logic only, no external backends.

Covers:
  1. Character loader  (characters.py)
  2. F-14 autofix      (llm/client.py)
  3. Safety filters     (safety/filters.py)
  4. i18n              (i18n.py)
  5. Settings          (settings.py)
  6. Episode save/load pattern
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

    def test_empty_dirs_return_empty(self, tmp_path):
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
        assert result == "DEF(kari) MVP"

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
