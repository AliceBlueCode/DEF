"""CivitaiAdapter: Civitai Orchestration API v2"""

import os
import time
from pathlib import Path

import requests

URL = "https://orchestration.civitai.com/v2/consumer/workflows"
ASSET_DIR = Path(__file__).parent.parent.parent.parent / "assets"

DEFAULT_SCHEDULER = "EulerA"
DEFAULT_CLIP_SKIP = 2
DEFAULT_STEPS = 20
DEFAULT_CFG_SCALE = 7.0
DEFAULT_WIDTH = 512
DEFAULT_HEIGHT = 768


def _get_token() -> str:
    token = os.environ.get("CIVITAI_API_TOKEN", "")
    if not token:
        try:
            from def_kari.secrets_store import get_api_key
            token = get_api_key("civitai") or ""
        except Exception:
            pass
    if not token:
        raise RuntimeError("Civitai APIキーが設定されていません。APIキー管理から設定してください。")
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
    scheduler: str = DEFAULT_SCHEDULER,
    clip_skip: int = DEFAULT_CLIP_SKIP,
) -> str:
    token = _get_token()
    model_air = model or os.environ.get("CIVITAI_DEFAULT_MODEL_AIR", "")
    if not model_air:
        raise RuntimeError("Civitaiモデル(AIR形式)が指定されていません。設定タブで選択してください。")

    # Civitai v2 requires engine/ecosystem discriminators in input
    air_parts = model_air.split(":")
    ecosystem = air_parts[2] if len(air_parts) > 2 and air_parts[:2] == ["urn", "air"] else "sd1"
    engine = "flux" if "flux" in ecosystem.lower() else "sdcpp"

    # params are flat inside input (not nested under "params")
    image_input: dict = {
        "engine": engine,
        "ecosystem": ecosystem,
        "operation": "createImage",
        "model": model_air,
        "prompt": prompt,
        "negativePrompt": negative_prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "cfgScale": cfg_scale,
        "scheduler": scheduler,
        "clipSkip": clip_skip,
        "quantity": 1,
    }
    if seed >= 0:
        image_input["seed"] = seed

    # workflowTemplate is now required by v2 API (null = no template)
    payload = {
        "workflowTemplate": None,
        "steps": [{"$type": "imageGen", "input": image_input}],
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    print(f"[CIVITAI] POST {URL} model={model_air} engine={engine}")
    print(f"[CIVITAI] payload={payload}")
    resp = requests.post(f"{URL}?wait=60", json=payload, headers=headers, timeout=120)
    if not resp.ok:
        body = resp.text[:1000]
        print(f"[CIVITAI] {resp.status_code}: {body}")
        raise RuntimeError(f"Civitai {resp.status_code}: {body}")
    workflow = resp.json()
    print(f"[CIVITAI] response status={workflow.get('status')} id={workflow.get('id')}")

    elapsed = 0
    while workflow.get("status") not in ("succeeded", "failed", "canceled"):
        if elapsed >= 300:
            raise TimeoutError("Civitaiワークフローがタイムアウトしました。")
        time.sleep(5)
        elapsed += 5
        poll = requests.get(f"{URL}/{workflow['id']}", headers=headers, timeout=30)
        poll.raise_for_status()
        workflow = poll.json()

    if workflow.get("status") != "succeeded":
        raise RuntimeError(f"Civitaiワークフロー失敗: {workflow.get('status')}")

    image_url = None
    for step in workflow.get("steps", []):
        for img in (step.get("output") or {}).get("images", []):
            if img.get("url"):
                image_url = img["url"]
                break
        if image_url:
            break

    if not image_url:
        raise RuntimeError("Civitai応答に画像URLがありません。")

    image_resp = requests.get(image_url, timeout=120)
    image_resp.raise_for_status()

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ASSET_DIR / f"civitai_{int(time.time() * 1000)}.png"
    out_path.write_bytes(image_resp.content)
    return str(out_path)
