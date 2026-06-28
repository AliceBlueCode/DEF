"""F-9: UIロケール管理"""

import json
from pathlib import Path

_LOCALES_DIR = Path(__file__).parent.parent / "locales"
_cache: dict[str, dict] = {}


def load_locale(lang: str = "ja") -> dict:
    if lang in _cache:
        return _cache[lang]
    path = _LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        path = _LOCALES_DIR / "ja.json"
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {}
    _cache[lang] = data
    return data


def t(key: str, lang: str = "ja", **kwargs) -> str:
    locale = load_locale(lang)
    text = locale.get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text
