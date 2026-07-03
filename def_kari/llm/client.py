"""F-14: LLMアダプター経由の呼び出し + フォールバックチェーン(4段構成)

基本設計5.4節に基づく実装。
"""

import json
import re

import requests

from def_kari.llm.backend import DEFAULT_LLM_BACKEND, LLM_BACKENDS
from def_kari.llm.prompts import build_system_prompt
from def_kari.llm.schema import EMOTIONS, VALIDATOR

MAX_CHAT_HISTORY_TURNS = 10
DEFAULT_OPTIONS = {"num_predict": 512}
LIGHTWEIGHT_OPTIONS = {"num_predict": 128, "num_ctx": 1024}

_THINK_CLOSED_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL)


def _strip_thinking(raw: str) -> str:
    result = _THINK_CLOSED_RE.sub("", raw)
    result = _THINK_OPEN_RE.sub("", result)
    return result.strip()


_FIELD_NAME_FIXES = {
    r'"di?a?logues?"': '"dialogue"',
    r'"emotions?"': '"emotion"',
    r'"image_prompts?"': '"image_prompt_en"',
    r'"image_prompt_en_?"': '"image_prompt_en"',
    r'"prompt"': '"image_prompt_en"',
    r'"safety_?tags?"': '"tags"',
    r'"tagss?"': '"tags"',
    r'"exicted"': '"excited"',
    r'"tenderss"': '"tender"',
    r'"tenderness"': '"tender"',
}


def _autofix(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    s = re.sub(r"```[\s\S]*$", "", s)
    s = _extract_json_object(s)
    s = _escape_control_chars_in_strings(s)
    s = _fix_missing_commas(s)
    s = s.replace("‘", "'").replace("’", "'")
    # クォートなしのキー名にダブルクォートを付与 (dialogue: -> "dialogue":)
    s = re.sub(r'(?<=[{,\s])(\w+)\s*:', r'"\1":', s)
    # シングルクォートの値をダブルクォートに変換
    s = re.sub(r":\s*'([^']*)'", r': "\1"', s)
    for pattern, replacement in _FIELD_NAME_FIXES.items():
        s = re.sub(pattern, replacement, s, flags=re.IGNORECASE)
    s = re.sub(r",\s*}", "}", s)
    s = re.sub(r",\s*]", "]", s)
    return s


def _escape_control_chars_in_strings(text: str) -> str:
    """JSON文字列値内の生の改行・タブをエスケープする。"""
    result = []
    in_string = False
    esc = False
    dquote = chr(34)
    for c in text:
        if esc:
            result.append(c)
            esc = False
            continue
        if c == chr(92):
            result.append(c)
            esc = True
            continue
        if c == dquote:
            in_string = not in_string
            result.append(c)
            continue
        if in_string:
            if c == chr(10):
                result.append(chr(92) + "n")
                continue
            if c == chr(13):
                result.append(chr(92) + "r")
                continue
            if c == chr(9):
                result.append(chr(92) + "t")
                continue
        result.append(c)
    return "".join(result)


def _fix_missing_commas(text: str) -> str:
    """JSON内でカンマが欠落しているパターンを修復する。"""
    dq = chr(34)
    pattern = "(" + dq + ")\\s*\\n\\s*(" + dq + ")"
    replacement = "\\1,\\n  \\2"
    return re.sub(pattern, replacement, text)


def _extract_json_object(text: str) -> str:
    """テキストからJSON objectを抽出する。波括弧のネストを追跡し、
    最初の{から対応する}までを返す。JSON後の余計なテキストを除去する。"""
    start = text.find("{")
    if start < 0:
        return text
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == "\"":

            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


def _repair_types(parsed: dict) -> dict:
    """スキーマ検証前に既知の型不一致を修復する。"""
    img = parsed.get("image_prompt_en")
    if isinstance(img, list):
        parsed["image_prompt_en"] = ", ".join(str(x) for x in img) if img else ""
    elif img is None:
        parsed["image_prompt_en"] = ""

    tags = parsed.get("tags")
    if tags is None:
        parsed["tags"] = []
    elif isinstance(tags, str):
        parsed["tags"] = [t.strip() for t in tags.split(",") if t.strip()]

    dialogue = parsed.get("dialogue")
    if dialogue is None:
        parsed["dialogue"] = ""
    elif not isinstance(dialogue, str):
        parsed["dialogue"] = str(dialogue)

    emotion = parsed.get("emotion")
    if emotion not in EMOTIONS:
        parsed["emotion"] = "neutral"

    return parsed


def _try_parse_and_validate(text: str):
    errors = []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        return False, None, [f"JSONDecodeError: {e}"]

    if not isinstance(parsed, dict):
        return False, None, ["トップレベルがオブジェクト(dict)ではありません"]

    parsed = _repair_types(parsed)

    schema_errors = list(VALIDATOR.iter_errors(parsed))
    if schema_errors:
        return False, None, [str(e.message) for e in schema_errors]
    return True, parsed, []


def _ensure_appearance_tags(parsed: dict, appearance_tags: str) -> dict:
    if not appearance_tags:
        return parsed
    existing = [t.strip() for t in parsed.get("image_prompt_en", "").split(",") if t.strip()]
    for tag in appearance_tags.split(","):
        tag = tag.strip()
        if tag and tag not in existing:
            existing.append(tag)
    parsed["image_prompt_en"] = ", ".join(existing)
    return parsed


def _prepend_name_tags(parsed: dict, image_name_tags: str) -> dict:
    """モデルがキャラクターを知っている場合の名前トリガーワードをプロンプト先頭に挿入する。"""
    if not image_name_tags:
        return parsed
    name_tags = [t.strip() for t in image_name_tags.split(",") if t.strip()]
    existing = [t.strip() for t in parsed.get("image_prompt_en", "").split(",") if t.strip()]
    prepend = [t for t in name_tags if t not in existing]
    if prepend:
        parsed["image_prompt_en"] = ", ".join(prepend + existing)
    return parsed


def _call_llm(
    user_text: str,
    history: list[dict] | None = None,
    extra_instruction: str = "",
    lightweight: bool = False,
    model: str = "",
    character: dict | None = None,
    backend: str = DEFAULT_LLM_BACKEND,
    quirks: dict | None = None,
) -> str:
    character = character or {}
    persona = character.get("persona_description", "You are a helpful assistant.")
    appearance = character.get("appearance_tags", "")
    try:
        import streamlit as _st
        _user_lang = _st.session_state.get("user_language", "ja")
    except Exception:
        _user_lang = "ja"
    system_prompt = build_system_prompt(persona, appearance, quirks=quirks, user_language=_user_lang)

    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    if history:
        for turn in history[-MAX_CHAT_HISTORY_TURNS:]:
            messages.append({"role": "user", "content": turn.get("user_text", "")})
            messages.append({"role": "assistant", "content": turn.get("dialogue", "")})

    if extra_instruction:
        messages.append({"role": "system", "content": extra_instruction})

    messages.append({"role": "user", "content": user_text})

    if lightweight:
        options = LIGHTWEIGHT_OPTIONS
    else:
        from def_kari.models.registry import get_llm_profile
        _profile = get_llm_profile(model)
        _mt = _profile.get("max_tokens", 512)
        _gen_params = _profile.get("generation_params", {})
        print(f"[LLM] model={model!r}, profile_max_tokens={_mt}, gen_params={_gen_params}")
        options = {"num_predict": _mt}
        options.update(_gen_params)
    chat_fn = LLM_BACKENDS[backend]["chat"]
    return chat_fn(messages, model, json_mode=True, options=options)


def generate_structured_reply(
    user_text: str,
    history: list[dict] | None = None,
    lightweight: bool = False,
    model: str = "",
    character: dict | None = None,
    backend: str = DEFAULT_LLM_BACKEND,
    quirks: dict | None = None,
) -> dict:
    """F-14のフォールバックチェーン(4段構成)を実行し、最終結果と各段階のログを返す。"""
    character = character or {}
    appearance_tags = character.get("appearance_tags", "")
    image_name_tags = character.get("image_name_tags", "")
    quirks = quirks or {}
    attempts = []

    try:
        raw = _call_llm(
            user_text,
            history=history,
            lightweight=lightweight,
            model=model,
            character=character,
            backend=backend,
            quirks=quirks,
        )
    except (requests.RequestException, RuntimeError) as exc:
        attempts.append({"stage": "LLMリクエスト", "raw": "", "errors": [f"{type(exc).__name__}: {exc}"]})
        return {"success": False, "result": None, "attempts": attempts}
    raw_before_strip = raw
    raw = _strip_thinking(raw)
    if not raw and raw_before_strip:
        raw = raw_before_strip
    ok, parsed, errors = _try_parse_and_validate(raw)
    attempts.append({"stage": "LLMリクエスト", "raw": raw, "errors": errors})
    if ok:
        return {"success": True, "result": _prepend_name_tags(_ensure_appearance_tags(parsed, appearance_tags), image_name_tags), "attempts": attempts}

    # 段1: 自動補正後の再パース
    fixed = _autofix(raw)
    ok, parsed, errors = _try_parse_and_validate(fixed)
    attempts.append({"stage": "段1. 自動補正後の再パース", "raw": fixed, "errors": errors})
    if ok:
        return {"success": True, "result": _prepend_name_tags(_ensure_appearance_tags(parsed, appearance_tags), image_name_tags), "attempts": attempts}

    # 段2: 補正パターン変更による再パース
    fallback_extract = re.sub(r"^[^{]*", "", raw, count=1)
    fallback_extract = re.sub(r"[^}]*$", "", fallback_extract[::-1], count=1)[::-1]
    fallback_extract = _autofix(fallback_extract)
    ok, parsed, errors = _try_parse_and_validate(fallback_extract)
    attempts.append({"stage": "段2. 補正パターン変更による再パース", "raw": fallback_extract, "errors": errors})
    if ok:
        return {"success": True, "result": _prepend_name_tags(_ensure_appearance_tags(parsed, appearance_tags), image_name_tags), "attempts": attempts}

    # 段3: プレーンテキスト形式からの抽出
    plain_result = _try_parse_plain_format(raw)
    if plain_result:
        ok, parsed, errors = plain_result
        attempts.append({"stage": "段3. プレーンテキスト形式からの抽出", "raw": raw, "errors": errors})
        if ok:
            return {"success": True, "result": _prepend_name_tags(_ensure_appearance_tags(parsed, appearance_tags), image_name_tags), "attempts": attempts}
    else:
        attempts.append({"stage": "段3. プレーンテキスト形式からの抽出", "raw": raw, "errors": ["プレーンテキスト形式に該当せず"]})

    # 段4: 生テキストをdialogueとして使用(最終安全網)
    final_raw = raw.strip()
    if final_raw:
        dialogue = _extract_dialogue(final_raw)
        emotion = "neutral"
        if quirks.get("emotion_in_text"):
            emotion = _estimate_emotion(dialogue)
        parsed = {"dialogue": dialogue, "emotion": emotion, "image_prompt_en": "", "tags": []}
        attempts.append({"stage": "段4. 生テキストをdialogueとして使用(最終安全網)", "raw": final_raw, "errors": []})
        return {"success": True, "result": _prepend_name_tags(_ensure_appearance_tags(parsed, appearance_tags), image_name_tags), "attempts": attempts}

    return {"success": False, "result": None, "attempts": attempts}


_EMOTION_PATTERNS = {
    "happy": re.compile(r"嬉し|楽し|♪|えへ|わくわく|にこ|笑|ふふ|やった|幸せ|喜", re.IGNORECASE),
    "angry": re.compile(r"怒|むか|ふざけ|許さ|うるさ|黙れ|馬鹿|くそ|腹が立", re.IGNORECASE),
    "sad": re.compile(r"悲し|寂し|泣|つら|切な|ごめん|残念|しくしく|うう", re.IGNORECASE),
    "surprised": re.compile(r"驚|えっ|まさか|びっくり|うそ|ええ|信じられ", re.IGNORECASE),
    "scared": re.compile(r"怖|恐|こわ|ひぃ|震え|おびえ|不安|やめて", re.IGNORECASE),
    "disgusted": re.compile(r"気持ち悪|嫌[だい]|ゲッ|うげ|最悪|汚|不快", re.IGNORECASE),
    "excited": re.compile(r"すごい|最高|やばい|テンション|燃え|熱い|興奮|いける", re.IGNORECASE),
    "tender": re.compile(r"愛し|大切|好き[だよ]|守り|優し|ぎゅ|抱き|温か", re.IGNORECASE),
    "thoughtful": re.compile(r"考え|思う|なるほど|そうか|むむ|確かに|興味深", re.IGNORECASE),
    "embarrassed": re.compile(r"恥ずかし|照れ|赤面|もう|やだ|見ないで|ばか", re.IGNORECASE),
    "tired": re.compile(r"疲れ|眠い|だるい|ふぁ|くたくた|もう無理|休み", re.IGNORECASE),
}


def _estimate_emotion(text: str) -> str:
    """テキストから感情を推定する。複数マッチ時は最初にマッチしたものを採用。"""
    for emotion, pattern in _EMOTION_PATTERNS.items():
        if pattern.search(text):
            return emotion
    return "neutral"


_DIALOGUE_FIELD_RE = re.compile(
    r'["\']?dialogues?["\']?\s*:\s*["\']?((?:[^"\'\\}]|\\.)*)(?:["\']|$)',
    re.DOTALL,
)

_META_START_RE = re.compile(
    r"^[\s]*(?:emotion|image_prompt|tags|description|dialogue\s*\||"
    r"character'?s?\s*emotion|response:|safety|nsfw|violence|"
    r"image_url|translation|instruction|note|context|system|"
    r"warning|disclaimer|"
    r"self[- ]?correct|check(?:ed|list)?\.?|✅|→\s*Checked|"
    r"output\s*(?:generation|format)|JSON\s*(?:structure|keys?)|"
    r"http[s]?://|```|---|#{2,})",
    re.IGNORECASE | re.MULTILINE,
)


def _extract_dialogue(raw: str) -> str:
    """生テキストからセリフ部分のみを抽出する。

    1. JSON風テキストに"dialogue"フィールドがあれば正規表現で値を抽出
    2. 「」で囲まれたセリフがあればそれを連結
    3. メタ情報の開始位置でカットし、最初の段落を使う
    """
    dialogue_match = _DIALOGUE_FIELD_RE.search(raw)
    if dialogue_match:
        val = dialogue_match.group(1)
        val = val.replace("\\n", "\n").replace('\\"', '"')
        return val.strip()

    clean = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    clean = re.sub(r"```[\s\S]*$", "", clean)
    clean = re.sub(r"^\{[\s]*", "", clean)

    meta_match = _META_START_RE.search(clean)
    text = clean[:meta_match.start()].strip() if meta_match else clean.strip()

    from def_kari.config import MIN_QUOTED_DIALOGUE_LEN
    quoted = re.findall(r"「([^」]+)」", text)
    if quoted:
        joined = "".join(quoted)
        if len(joined) > MIN_QUOTED_DIALOGUE_LEN:
            return joined

    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        lines.append(stripped)

    return "\n".join(lines) if lines else raw.strip().split("\n")[0]


_PLAIN_IMAGE_PROMPT_RE = re.compile(r"image_prompt_en\s*[:=]\s*(.+)", re.IGNORECASE)
_PLAIN_TAGS_RE = re.compile(r"tags\s*[:=]\s*\[([^\]]*)\]", re.IGNORECASE)


def _try_parse_plain_format(raw: str):
    m_img = _PLAIN_IMAGE_PROMPT_RE.search(raw)
    if not m_img and "<|im_end|>" not in raw:
        return None

    dialogue = raw.split("<|im_end|>")[0].strip() if "<|im_end|>" in raw else raw.strip()
    image_prompt_en = m_img.group(1).strip().strip('"').strip("'") if m_img else ""

    tags = []
    m_tags = _PLAIN_TAGS_RE.search(raw)
    if m_tags:
        tags = [t.strip().strip('"').strip("'") for t in m_tags.group(1).split(",") if t.strip()]

    parsed = {
        "dialogue": dialogue,
        "emotion": "neutral",
        "image_prompt_en": image_prompt_en,
        "tags": tags,
    }
    return True, parsed, []
