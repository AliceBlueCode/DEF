"""APIキーの暗号化ローカル保存(サービス別管理)

Fernet(対称鍵暗号)で暗号化してdata/api_keys.enc.jsonに保存する。
暗号鍵はdata/secret.keyに自動生成・保存。
"""

import json
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

DATA_DIR = Path(__file__).parent.parent / "data"
KEY_PATH = DATA_DIR / "secret.key"
STORE_PATH = DATA_DIR / "api_keys.enc.json"


def _load_fernet() -> Fernet:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not KEY_PATH.exists():
        KEY_PATH.write_bytes(Fernet.generate_key())
        try:
            os.chmod(KEY_PATH, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    return Fernet(KEY_PATH.read_bytes())


def _load_store() -> dict:
    if not STORE_PATH.exists():
        return {}
    try:
        with open(STORE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_store(store: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def set_api_key(service: str, api_key: str) -> None:
    if not api_key:
        delete_api_key(service)
        return
    fernet = _load_fernet()
    store = _load_store()
    store[service] = fernet.encrypt(api_key.encode("utf-8")).decode("ascii")
    _save_store(store)


def get_api_key(service: str) -> str | None:
    store = _load_store()
    token = store.get(service)
    if not token:
        return None
    fernet = _load_fernet()
    try:
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None


def has_api_key(service: str) -> bool:
    return service in _load_store()


def delete_api_key(service: str) -> None:
    store = _load_store()
    if service in store:
        del store[service]
        _save_store(store)
