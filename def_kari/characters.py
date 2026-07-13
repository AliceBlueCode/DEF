"""キャラクタープロフィール管理（基本設計12章②準拠のbase_profile型のみ）"""

import json
import os
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
CHARACTERS_DIR = DATA_DIR / "public" / "characters"
PRIVATE_CHARACTERS_DIR = DATA_DIR / "private" / "characters"
PROFILES_PATH = DATA_DIR / "character_profiles.json"
POC_PROFILES_PATH = Path(__file__).parent.parent / "poc" / "data" / "character_profiles.json"

DEFAULT_CHARACTER_ID = "character_luna_001"


def _load_from_flat_dir(char_dir: Path, profiles: dict) -> None:
    """旧形式: char_dir/{character_id}/profile.json"""
    if not char_dir.exists():
        return
    for entry in sorted(char_dir.iterdir()):
        if not entry.is_dir():
            continue
        pf = entry / "profile.json"
        if not pf.exists():
            continue
        try:
            with open(pf, encoding="utf-8-sig") as f:
                data = json.load(f)
            if data:
                profiles[entry.name] = next(iter(data.values()))
        except (json.JSONDecodeError, OSError):
            pass


def _load_char_dir(char_dir: Path, profiles: dict) -> None:
    """profile.json を持つ1キャラクターディレクトリを読み込む。先勝ち。"""
    if char_dir.name in profiles:
        return
    pf = char_dir / "profile.json"
    if not pf.exists():
        return
    try:
        with open(pf, encoding="utf-8-sig") as f:
            data = json.load(f)
        if data:
            profiles[char_dir.name] = next(iter(data.values()))
    except (json.JSONDecodeError, OSError):
        pass


def _load_from_character_repo(repo_path: Path, profiles: dict) -> None:
    """新形式: repo/public/ 以下を再帰的に走査し profile.json を持つディレクトリをキャラクターとして読み込む。
    階層数不問。先勝ち（既登録IDは上書きしない）。"""
    public_dir = repo_path / "public"
    if not public_dir.exists():
        return
    for pf in sorted(public_dir.rglob("profile.json")):
        _load_char_dir(pf.parent, profiles)


def _get_repo_paths() -> list[Path]:
    """CHARACTER_REPO_PATH / CHARACTER_REPO_PATHS をセミコロン区切りで複数パス返す。"""
    raw = os.environ.get("CHARACTER_REPO_PATHS") or os.environ.get("CHARACTER_REPO_PATH", "")
    return [Path(p.strip()) for p in raw.split(";") if p.strip()]


def load_profiles() -> dict[str, dict]:
    profiles = {}
    # 新形式優先: CHARACTER_REPO_PATHS (セミコロン区切り複数対応)
    for _repo in _get_repo_paths():
        _load_from_character_repo(_repo, profiles)
    # 旧形式: data/public/characters, data/private/characters
    for _cdir in (CHARACTERS_DIR, PRIVATE_CHARACTERS_DIR):
        _load_from_flat_dir(_cdir, profiles)
    # フォールバック: 旧一括ファイル
    if not profiles:
        for path in (PROFILES_PATH, POC_PROFILES_PATH):
            if path.exists():
                try:
                    with open(path, encoding="utf-8-sig") as f:
                        profiles.update(json.load(f))
                except (json.JSONDecodeError, OSError):
                    pass
    return profiles


def _get_bp(profile: dict) -> dict:
    return profile.get("base_profile", {})


def _get_pa(profile: dict) -> dict:
    return _get_bp(profile).get("persona_attributes", {})


def _get_vr(profile: dict) -> dict:
    return _get_bp(profile).get("visual_references", {})


def get_character(character_id: str | None, profiles: dict | None = None) -> dict:
    """正規化されたキャラクター辞書を返す。"""
    profiles = profiles or load_profiles()
    raw = profiles.get(character_id or DEFAULT_CHARACTER_ID, {})
    bp = _get_bp(raw)
    pa = _get_pa(raw)
    vr = _get_vr(raw)

    speech_style_raw = pa.get("speech_style", "")
    if isinstance(speech_style_raw, dict):
        parts = []
        if speech_style_raw.get("first_person"):
            parts.append(f"一人称: {speech_style_raw['first_person']}")
        if speech_style_raw.get("address_partner"):
            parts.append(f"相手の呼び方: {speech_style_raw['address_partner']}")
        if speech_style_raw.get("tone"):
            parts.append(speech_style_raw["tone"])
        speech_style = "。".join(parts)
    else:
        speech_style = speech_style_raw or ""

    persona = bp.get("identity_prompt", "")
    identity_detail = bp.get("identity_detail", "")
    if identity_detail:
        persona = f"{persona}\n{identity_detail}"

    # persona_attributesからキャラクター属性を追加
    _gender = pa.get("gender")
    _gender_identity = pa.get("gender_identity")
    _romantic_interest = pa.get("romantic_interest")
    _attr_parts = []
    if _gender:
        _attr_parts.append(f"性別: {_gender}")
    if _gender_identity and _gender_identity != _gender:
        _attr_parts.append(f"性自認: {_gender_identity}")
    if _romantic_interest:
        _attr_parts.append(f"恋愛対象: {', '.join(_romantic_interest)}")
    elif _romantic_interest is not None and isinstance(_romantic_interest, list) and len(_romantic_interest) == 0:
        _attr_parts.append("恋愛対象: なし")
    if _attr_parts:
        persona = f"{persona}\n{'。'.join(_attr_parts)}"

    if speech_style and speech_style not in persona:
        persona = f"{persona}\n口調: {speech_style}"

    appearance_tags = bp.get("appearance_tags") or vr.get("appearance_tags") or vr.get("features") or ""
    image_name_tags = bp.get("image_name_tags") or vr.get("image_name_tags", "")

    dmc = bp.get("default_model_config", {})
    lora = dmc.get("lora", [])

    _rels_raw = raw.get("relationships", {})
    relationships = {
        (profiles.get(cid, {}).get("base_profile", {}).get("name") or cid): desc
        for cid, desc in _rels_raw.items()
    } if isinstance(_rels_raw, dict) else {}

    return {
        "name": bp.get("name", character_id or ""),
        "name_reading": bp.get("name_reading", {}),
        "player_type": bp.get("player_type", "ai"),
        "image_color": bp.get("image_color"),
        "appearance_tags": appearance_tags,
        "image_name_tags": image_name_tags,
        "persona_description": persona,
        "speech_style": speech_style,
        "voicevox_speaker_id": dmc.get("voicevox_speaker_id"),
        "irodori_speaker_id": dmc.get("irodori_speaker_id"),
        "gemini_tts_voice": dmc.get("gemini_tts_voice"),
        "kokoro_voice": dmc.get("kokoro_voice"),
        "lora": lora,
        "content_policy": bp.get("content_policy", {}),
        "relationships": relationships,
        "goals": bp.get("goals", {}),
    }


_TTS_SPEAKER_FIELDS = {
    "voicevox": "voicevox_speaker_id",
    "irodori": "irodori_speaker_id",
    "gemini_tts": "gemini_tts_voice",
    "kokoro": "kokoro_voice",
    "openai_tts": "openai_tts_voice",
}

_TTS_DEFAULT_SPEAKERS = {
    "voicevox": 2,
    "irodori": "",
    "gemini_tts": "Kore",
    "kokoro": "jf_alpha",
    "openai_tts": "alloy",
}


def build_lora_prompt(lora: list) -> str:
    """LoRAリストからプロンプト用文字列を生成する。trigger_tags先頭、<lora:...>末尾。"""
    trigger_tags: list[str] = []
    lora_syntax: list[str] = []
    for item in lora:
        if not item.get("name"):
            continue
        for t in (item.get("trigger_tags") or "").split(","):
            t = t.strip()
            if t:
                trigger_tags.append(t)
        lora_syntax.append(f"<lora:{item['name']}:{item.get('weight', 0.8)}>")
    parts = []
    if trigger_tags:
        parts.append(", ".join(trigger_tags))
    if lora_syntax:
        parts.append(" ".join(lora_syntax))
    return " ".join(parts)


def get_tts_speaker_id(character: dict, tts_backend: str):
    """キャラクターのTTSバックエンド別話者IDを返す。未設定時はデフォルト。"""
    field = _TTS_SPEAKER_FIELDS.get(tts_backend)
    if field is None:
        return _TTS_DEFAULT_SPEAKERS.get(tts_backend)
    speaker = character.get(field)
    if speaker is not None:
        return speaker
    return _TTS_DEFAULT_SPEAKERS.get(tts_backend)


def apply_name_reading(text: str, character: dict) -> str:
    """TTS合成前にキャラクター名をカナ読みに置換する(VOICEVOX誤読対策)。
    フルネーム→名→姓の順で置換。family_name_kana/given_name_kanaがあれば新形式、
    なければfamily_name/given_nameをカナとして扱う（旧形式との後方互換）。"""
    if not text:
        return text or ""
    reading = character.get("name_reading")
    if not isinstance(reading, dict):
        return text
    family_kanji = reading.get("family_name") or ""
    given_kanji = reading.get("given_name") or ""
    family_kana = reading.get("family_name_kana") or family_kanji
    given_kana = reading.get("given_name_kana") or given_kanji
    # 1. フルネーム
    name = character.get("name", "")
    full_kana = family_kana + given_kana
    if full_kana and name and full_kana != name:
        text = text.replace(name, full_kana)
    # 2. 名のみ
    if given_kana and given_kanji and given_kana != given_kanji:
        text = text.replace(given_kanji, given_kana)
    # 3. 姓のみ
    if family_kana and family_kanji and family_kana != family_kanji:
        text = text.replace(family_kanji, family_kana)
    return text


def get_raw_profile(character_id: str, profiles: dict | None = None) -> dict:
    """base_profile全体をそのまま返す（編集UI用）。"""
    profiles = profiles or load_profiles()
    raw = profiles.get(character_id, {})
    return _get_bp(raw)


def list_character_choices(profiles: dict | None = None) -> list[tuple[str, str]]:
    profiles = profiles or load_profiles()
    choices = []
    for cid, profile in profiles.items():
        bp = _get_bp(profile)
        name = bp.get("name", cid)
        choices.append((cid, name))
    return choices


def _find_character_dir(character_id: str) -> Path:
    for _cdir in (CHARACTERS_DIR, PRIVATE_CHARACTERS_DIR):
        _d = _cdir / character_id
        if _d.exists():
            return _d
    return CHARACTERS_DIR / character_id


def save_profile(character_id: str, base_profile: dict) -> None:
    """base_profileを丸ごと保存する。ディレクトリ方式。"""
    char_dir = _find_character_dir(character_id)
    char_dir.mkdir(parents=True, exist_ok=True)
    char_path = char_dir / "profile.json"

    # 既存データを読み込み（relationships等を保持）
    existing = {}
    if char_path.exists():
        try:
            with open(char_path, encoding="utf-8-sig") as f:
                data = json.load(f)
                existing = data.get(character_id, {})
        except (json.JSONDecodeError, OSError):
            pass

    existing["base_profile"] = base_profile

    with open(char_path, "w", encoding="utf-8") as f:
        json.dump({character_id: existing}, f, ensure_ascii=False, indent=2)
