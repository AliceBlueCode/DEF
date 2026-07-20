"""HuggingFaceAdapter: HuggingFace Inference API"""

import os
import time
from pathlib import Path

import requests

INFERENCE_URL = "https://router.huggingface.co"
INFERENCE_PROVIDER = "hf-inference"
DEFAULT_MODEL = os.environ.get("HF_DEFAULT_MODEL", "black-forest-labs/FLUX.1-schnell")
ASSET_DIR = Path(__file__).parent.parent.parent.parent / "assets"

DEFAULT_WIDTH = 512
DEFAULT_HEIGHT = 768
DEFAULT_STEPS = 4
DEFAULT_CFG_SCALE = 0.0


def _get_token() -> str:
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY")
    if not token:
        try:
            from def_kari.secrets_store import get_api_key
            token = get_api_key("huggingface")
        except Exception:
            pass
    if not token:
        raise RuntimeError("Hugging Face APIトークンが設定されていません。")
    return token


def generate(
    prompt: str,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    model: str | None = None,
    negative_prompt: str = "",
    seed: int = -1,
    steps: int = DEFAULT_STEPS,
    cfg_scale: float = DEFAULT_CFG_SCALE,
) -> str:
    token = _get_token()
    model_id = model or DEFAULT_MODEL
    body: dict = {"inputs": prompt}
    params: dict = {}
    if width:
        params["width"] = width
    if height:
        params["height"] = height
    if negative_prompt:
        params["negative_prompt"] = negative_prompt
    if seed >= 0:
        params["seed"] = seed
    if steps > 0:
        params["num_inference_steps"] = steps
    if cfg_scale > 0:
        params["guidance_scale"] = cfg_scale
    if params:
        body["parameters"] = params

    url = f"{INFERENCE_URL}/{INFERENCE_PROVIDER}/models/{model_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    print(f"[HF T2I] POST {url}")
    resp = requests.post(url, headers=headers, json=body, timeout=120)
    if not resp.ok:
        print(f"[HF T2I] {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ASSET_DIR / f"hf_{int(time.time() * 1000)}.png"
    out_path.write_bytes(resp.content)
    print(f"[HF T2I] generated: {out_path}")
    return str(out_path)
