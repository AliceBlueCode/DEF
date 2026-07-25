"""OpenAI Images API互換アダプター — 任意のベースURLで動作"""

import base64
import time
from pathlib import Path

import requests

ASSET_DIR = Path(__file__).parent.parent.parent.parent / "assets"


def _nearest_size(width: int, height: int) -> str:
    ratio = height / max(width, 1)
    if ratio > 1.3:
        return "1024x1536"
    if ratio < 0.77:
        return "1536x1024"
    return "1024x1024"


def make_generate_fn(base_url: str, api_key: str, default_model: str, name: str = "compatible", extra_headers: dict | None = None):
    def generate(
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        model: str | None = None,
        negative_prompt: str = "",
        seed: int = -1,
        **kwargs,
    ) -> str:
        model_id = model or default_model
        size = _nearest_size(width, height)

        body: dict = {"prompt": prompt, "n": 1, "size": size}
        if model_id:
            body["model"] = model_id

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)

        url = f"{base_url.rstrip('/')}/images/generations"
        print(f"[COMPATIBLE T2I:{name}] POST {url} model={model_id} size={size}")
        resp = requests.post(url, headers=headers, json=body, timeout=120)

        # size 非対応の API はパラメータを除いてリトライ
        if resp.status_code == 400 and "size" in resp.text:
            print(f"[COMPATIBLE T2I:{name}] size 非対応 → size なしでリトライ")
            body.pop("size", None)
            resp = requests.post(url, headers=headers, json=body, timeout=120)

        if not resp.ok:
            print(f"[COMPATIBLE T2I:{name}] {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()

        data = resp.json()["data"][0]
        ASSET_DIR.mkdir(parents=True, exist_ok=True)
        out_path = ASSET_DIR / f"{name}_{int(time.time() * 1000)}.png"

        if "b64_json" in data and data["b64_json"]:
            out_path.write_bytes(base64.b64decode(data["b64_json"]))
        elif "url" in data:
            img_resp = requests.get(data["url"], timeout=120)
            img_resp.raise_for_status()
            out_path.write_bytes(img_resp.content)
        else:
            raise RuntimeError(f"Compatible T2I: 画像データなし: {list(data.keys())}")

        print(f"[COMPATIBLE T2I:{name}] generated: {out_path}")
        return str(out_path)

    return generate
