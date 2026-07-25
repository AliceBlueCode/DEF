"""compatible_backends.json / compatible_backends.key.json の読み書き

data/compatible_backends.json     — 名前・Base URL・Model・Extra Headers・用途タグ（git管理対象）
data/compatible_backends.key.json — API Keyのみ（gitignore対象）
"""

import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_DEF_PATH = _DATA_DIR / "compatible_backends.json"
_KEY_PATH = _DATA_DIR / "compatible_backends.key.json"


def _load_defs() -> dict:
    if not _DEF_PATH.exists():
        return {}
    try:
        return json.loads(_DEF_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_defs(defs: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _DEF_PATH.write_text(json.dumps(defs, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_keys() -> dict:
    if not _KEY_PATH.exists():
        return {}
    try:
        return json.loads(_KEY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_keys(keys: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _KEY_PATH.write_text(json.dumps(keys, ensure_ascii=False, indent=2), encoding="utf-8")


def list_backends() -> list[dict]:
    """一覧を返す。APIキーはマスク済み。"""
    defs = _load_defs()
    keys = _load_keys()
    result = []
    for name, entry in defs.items():
        result.append({
            "name": name,
            "base_url": entry.get("base_url", ""),
            "model": entry.get("model", ""),
            "extra_headers": entry.get("extra_headers", {}),
            "capabilities": entry.get("capabilities", ["llm"]),
            "label": entry.get("label", name),
            "has_key": bool(keys.get(name)),
        })
    return result


def get_backend_for_runtime(name: str) -> dict | None:
    """アダプター生成用に APIキーを含む完全な情報を返す。"""
    defs = _load_defs()
    keys = _load_keys()
    if name not in defs:
        return None
    entry = dict(defs[name])
    entry["api_key"] = keys.get(name, "")
    entry["name"] = name
    return entry


def save_backend(name: str, base_url: str, model: str, extra_headers: dict,
                 capabilities: list[str], label: str, api_key: str | None) -> None:
    defs = _load_defs()
    defs[name] = {
        "base_url": base_url,
        "model": model,
        "extra_headers": extra_headers,
        "capabilities": capabilities,
        "label": label or name,
    }
    _save_defs(defs)
    if api_key is not None:
        keys = _load_keys()
        keys[name] = api_key
        _save_keys(keys)


def delete_backend(name: str) -> bool:
    defs = _load_defs()
    if name not in defs:
        return False
    del defs[name]
    _save_defs(defs)
    keys = _load_keys()
    keys.pop(name, None)
    _save_keys(keys)
    return True


def all_backends_with_keys() -> list[dict]:
    """backend.py の動的登録用。APIキーを含む全エントリを返す。"""
    defs = _load_defs()
    keys = _load_keys()
    result = []
    for name, entry in defs.items():
        result.append({
            "name": name,
            "base_url": entry.get("base_url", ""),
            "model": entry.get("model", ""),
            "extra_headers": entry.get("extra_headers", {}),
            "capabilities": entry.get("capabilities", ["llm"]),
            "label": entry.get("label", name),
            "api_key": keys.get(name, ""),
            "max_chars_per_request": entry.get("max_chars_per_request"),
            "response_format": entry.get("response_format"),
        })
    return result
