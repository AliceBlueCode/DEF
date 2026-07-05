"""A1111Adapter: Automatic1111 SD WebUI"""

import base64
import os
import time
from pathlib import Path

import requests

URL = os.environ.get("A1111_URL", "http://localhost:7860")
ASSET_DIR = Path(__file__).parent.parent.parent.parent / "assets"

DEFAULT_STEPS = 20
DEFAULT_CFG_SCALE = 7.0
DEFAULT_WIDTH = 512
DEFAULT_HEIGHT = 768
DEFAULT_SAMPLER = "Euler a"


def generate(
    prompt: str,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    model: str | None = None,
    negative_prompt: str = "",
    seed: int = -1,
    steps: int = DEFAULT_STEPS,
    cfg_scale: float = DEFAULT_CFG_SCALE,
    sampler: str = DEFAULT_SAMPLER,
) -> str:
    url = os.environ.get("A1111_URL", URL)
    payload: dict = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "seed": seed,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg_scale": cfg_scale,
        "sampler_name": sampler,
    }
    if model:
        payload["override_settings"] = {"sd_model_checkpoint": model}

    resp = requests.post(f"{url}/sdapi/v1/txt2img", json=payload, timeout=300)
    resp.raise_for_status()
    image_b64 = resp.json()["images"][0]

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ASSET_DIR / f"a1111_{int(time.time() * 1000)}.png"
    out_path.write_bytes(base64.b64decode(image_b64))
    return str(out_path)
