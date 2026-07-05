"""ComfyUIAdapter: ComfyUI"""

import copy
import os
import time
from pathlib import Path

import requests

URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
ASSET_DIR = Path(__file__).parent.parent.parent.parent / "assets"
WORKFLOWS_DIR = Path(__file__).parent.parent.parent.parent / "data" / "comfyui_workflows"

DEFAULT_STEPS = 20
DEFAULT_CFG_SCALE = 7.0
DEFAULT_WIDTH = 512
DEFAULT_HEIGHT = 768


def _load_workflow(name: str = "default") -> dict:
    import json
    path = WORKFLOWS_DIR / f"{name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def generate(
    prompt: str,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    model: str | None = None,
    negative_prompt: str = "",
    seed: int = -1,
    steps: int = DEFAULT_STEPS,
    cfg_scale: float = DEFAULT_CFG_SCALE,
    workflow_name: str = "default",
) -> str:
    url = os.environ.get("COMFYUI_URL", URL)
    workflow = copy.deepcopy(_load_workflow(workflow_name))
    if not workflow:
        raise RuntimeError(f"ComfyUIワークフローが見つかりません: data/comfyui_workflows/{workflow_name}.json")

    current_ckpt = workflow.get("4", {}).get("inputs", {}).get("ckpt_name", "")
    if model:
        workflow["4"]["inputs"]["ckpt_name"] = model
    elif not current_ckpt:
        try:
            info = requests.get(f"{url}/object_info/CheckpointLoaderSimple", timeout=5).json()
            choices = info.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
            if choices:
                workflow["4"]["inputs"]["ckpt_name"] = choices[0]
        except Exception:
            pass
    workflow["5"]["inputs"]["width"] = width
    workflow["5"]["inputs"]["height"] = height
    workflow["6"]["inputs"]["text"] = prompt
    workflow["7"]["inputs"]["text"] = negative_prompt or ""
    workflow["3"]["inputs"]["seed"] = seed if seed >= 0 else int(time.time())
    workflow["3"]["inputs"]["steps"] = steps
    workflow["3"]["inputs"]["cfg"] = cfg_scale

    resp = requests.post(f"{url}/prompt", json={"prompt": workflow}, timeout=10)
    if not resp.ok:
        raise RuntimeError(f"ComfyUI {resp.status_code}: {resp.text[:500]}")
    prompt_id = resp.json().get("prompt_id")
    print(f"[COMFYUI] queued: prompt_id={prompt_id}")

    for _ in range(120):
        time.sleep(2)
        hist_resp = requests.get(f"{url}/history/{prompt_id}", timeout=10)
        if hist_resp.status_code != 200:
            continue
        history = hist_resp.json()
        if prompt_id not in history:
            continue
        outputs = history[prompt_id].get("outputs", {})
        for node_output in outputs.values():
            images = node_output.get("images", [])
            if images:
                img_info = images[0]
                img_resp = requests.get(
                    f"{url}/view",
                    params={"filename": img_info["filename"], "subfolder": img_info.get("subfolder", ""), "type": img_info.get("type", "output")},
                    timeout=30,
                )
                img_resp.raise_for_status()
                ASSET_DIR.mkdir(parents=True, exist_ok=True)
                out_path = ASSET_DIR / f"comfyui_{int(time.time() * 1000)}.png"
                out_path.write_bytes(img_resp.content)
                print(f"[COMFYUI] generated: {out_path}")
                return str(out_path)
        if history[prompt_id].get("status", {}).get("status_str") == "error":
            raise RuntimeError(f"ComfyUI生成エラー: {history[prompt_id].get('status', {}).get('messages', [])}")

    raise RuntimeError("ComfyUI: タイムアウト（240秒）")
