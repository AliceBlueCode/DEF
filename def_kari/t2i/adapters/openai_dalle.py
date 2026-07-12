"""OpenAI DALL-E Adapter: DALL-E 3 via OpenAI Images API"""

import os
import time
from pathlib import Path

import requests

API_URL = "https://api.openai.com/v1/images/generations"
DEFAULT_MODEL = "gpt-image-1"
ASSET_DIR = Path(__file__).parent.parent.parent.parent / "assets"


def _nearest_size(width: int, height: int) -> str:
    """指定サイズに最も近い対応サイズを返す"""
    ratio = height / max(width, 1)
    if ratio > 1.3:
        return "1024x1536"
    if ratio < 0.77:
        return "1536x1024"
    return "1024x1024"


def _get_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        try:
            from def_kari.secrets_store import get_api_key
            key = get_api_key("openai")
        except Exception:
            pass
    if not key:
        raise RuntimeError("OpenAI APIキーが設定されていません。APIキー管理から設定してください。")
    return key


def generate(
    prompt: str,
    width: int = 1024,
    height: int = 1024,
    model: str | None = None,
    negative_prompt: str = "",
    seed: int = -1,
    **kwargs,
) -> str:
    api_key = _get_api_key()
    if not model:
        try:
            from def_kari.settings import load_settings
            model = load_settings().get("t2i_model_openai", "") or ""
        except Exception:
            pass
    model_id = model or DEFAULT_MODEL
    size = _nearest_size(width, height)

    payload = {
        "model": model_id,
        "prompt": prompt,
        "size": size,
        "n": 1,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    print(f"[OPENAI T2I] POST {API_URL} model={model_id} size={size}")
    resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)
    if not resp.ok:
        print(f"[OPENAI T2I] {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()

    data = resp.json()["data"][0]
    if "b64_json" in data and data["b64_json"]:
        import base64
        image_bytes = base64.b64decode(data["b64_json"])
    else:
        img_resp = requests.get(data["url"], timeout=120)
        img_resp.raise_for_status()
        image_bytes = img_resp.content

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ASSET_DIR / f"openai_{int(time.time() * 1000)}.png"
    out_path.write_bytes(image_bytes)
    print(f"[OPENAI T2I] generated: {out_path}")
    return str(out_path)
