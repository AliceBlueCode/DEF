"""T2I生成バックエンド呼び出し — A1111 / Civitai"""

import base64
import os
import time
from pathlib import Path

import requests

A1111_URL = os.environ.get("A1111_URL", "http://localhost:7860")
_ECOSYSTEM_MAP_PATH = Path(__file__).parent.parent.parent / "data" / "civitai_ecosystem_map.json"


def _load_ecosystem_map() -> dict:
    if _ECOSYSTEM_MAP_PATH.exists():
        try:
            import json
            return json.loads(_ECOSYSTEM_MAP_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}
CIVITAI_URL = "https://orchestration.civitai.com/v2/consumer/workflows"
ASSET_DIR = Path(__file__).parent.parent.parent / "assets"


def generate_image(
    prompt: str,
    width: int = 512,
    height: int = 768,
    model_name: str | None = None,
    backend: str = "a1111",
    negative_prompt: str = "",
    seed: int = -1,
    steps: int = 20,
    cfg_scale: float = 7,
) -> str:
    if backend == "a1111":
        return _a1111_generate(prompt, width, height, model_name, negative_prompt, seed, steps, cfg_scale)
    elif backend == "civitai":
        return _civitai_generate(prompt, width, height, model_name, negative_prompt, seed, steps, cfg_scale)
    elif backend == "huggingface":
        return _huggingface_generate(prompt, width, height, model_name, negative_prompt, seed, steps, cfg_scale)
    elif backend == "comfyui":
        return _comfyui_generate(prompt, width, height, model_name, negative_prompt, seed, steps, cfg_scale)
    raise ValueError(f"Unknown T2I backend: {backend}")


def _a1111_generate(
    prompt: str, width: int, height: int, model_name: str | None,
    negative_prompt: str, seed: int, steps: int, cfg_scale: float,
) -> str:
    payload = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "seed": seed,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg_scale": cfg_scale,
    }
    if model_name:
        payload["override_settings"] = {"sd_model_checkpoint": model_name}

    resp = requests.post(f"{A1111_URL}/sdapi/v1/txt2img", json=payload, timeout=300)
    resp.raise_for_status()
    image_b64 = resp.json()["images"][0]

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"a1111_{int(time.time() * 1000)}.png"
    out_path = ASSET_DIR / filename
    out_path.write_bytes(base64.b64decode(image_b64))
    return str(out_path)


def _civitai_generate(
    prompt: str, width: int, height: int, model_name: str | None,
    negative_prompt: str, seed: int, steps: int, cfg_scale: float,
) -> str:
    api_token = os.environ.get("CIVITAI_API_TOKEN", "")
    if not api_token:
        try:
            from def_kari.secrets_store import get_api_key
            api_token = get_api_key("civitai") or ""
        except Exception:
            pass
    if not api_token:
        raise RuntimeError("Civitai APIキーが設定されていません。APIキー管理から設定してください。")

    if not model_name:
        try:
            from def_kari.settings import load_settings
            model_name = load_settings().get("t2i_model_civitai", "")
        except Exception:
            pass
    model_air = model_name or os.environ.get("CIVITAI_DEFAULT_MODEL_AIR", "")
    if not model_air:
        raise RuntimeError("Civitaiモデル(AIR形式)が指定されていません。")

    air_parts = model_air.split(":")
    ecosystem = air_parts[2] if len(air_parts) > 2 and air_parts[:2] == ["urn", "air"] else "sd1"
    is_flux = "flux" in ecosystem.lower()

    image_input: dict = {
        "engine": "flux" if is_flux else "sdcpp",
        "ecosystem": ecosystem,
        "operation": "createImage",
        "model": model_air,
        "prompt": prompt,
        "width": width,
        "height": height,
        "steps": steps,
        "quantity": 1,
    }
    if is_flux:
        image_input["guidance"] = cfg_scale
    else:
        image_input["negativePrompt"] = negative_prompt
        image_input["cfgScale"] = cfg_scale
        image_input["scheduler"] = "EulerA"
        image_input["clipSkip"] = 2
    if seed >= 0:
        image_input["seed"] = seed

    headers = {"Authorization": f"Bearer {api_token}", "Content-Type": "application/json"}
    payload = {"steps": [{"$type": "imageGen", "input": image_input}]}
    print(f"[CIVITAI] POST {CIVITAI_URL} model={model_air} ecosystem={image_input.get('ecosystem')} engine={image_input.get('engine')}")
    print(f"[CIVITAI] payload={payload}")
    resp = requests.post(f"{CIVITAI_URL}?wait=60", json=payload, headers=headers, timeout=120)
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
        poll = requests.get(f"{CIVITAI_URL}/{workflow['id']}", headers=headers, timeout=30)
        poll.raise_for_status()
        workflow = poll.json()

    if workflow.get("status") != "succeeded":
        raise RuntimeError(f"Civitaiワークフロー失敗: {workflow.get('status')}")

    image_url = None
    for step in workflow.get("steps", []):
        output = step.get("output") or {}
        for img in output.get("images", []):
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
    filename = f"civitai_{int(time.time() * 1000)}.png"
    out_path = ASSET_DIR / filename
    out_path.write_bytes(image_resp.content)
    return str(out_path)


HF_INFERENCE_URL = "https://router.huggingface.co"
HF_DEFAULT_MODEL = os.environ.get("HF_DEFAULT_MODEL", "black-forest-labs/FLUX.1-schnell")


def _get_hf_token() -> str:
    key = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_API_KEY")
    if not key:
        try:
            from def_kari.secrets_store import get_api_key
            key = get_api_key("huggingface")
        except Exception:
            pass
    if not key:
        raise RuntimeError("Hugging Face APIトークンが設定されていません。")
    return key


def _huggingface_generate(
    prompt: str, width: int, height: int, model_name: str | None,
    negative_prompt: str, seed: int, steps: int, cfg_scale: float,
) -> str:
    if not model_name:
        try:
            from def_kari.settings import load_settings
            model_name = load_settings().get("t2i_model_huggingface", "")
        except Exception:
            pass
    model = model_name or HF_DEFAULT_MODEL
    body = {"inputs": prompt}
    params = {}
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

    _headers = {
        "Authorization": f"Bearer {_get_hf_token()}",
        "Content-Type": "application/json",
    }
    # router.huggingface.co経由でプロバイダーに自動ルーティング
    _url = f"{HF_INFERENCE_URL}/hf-inference/models/{model}"
    print(f"[HF T2I] requesting: {_url}")
    resp = requests.post(_url, headers=_headers, json=body, timeout=120)
    if resp.status_code != 200:
        print(f"[HF T2I] error {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()

    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"hf_{int(time.time() * 1000)}.png"
    out_path = ASSET_DIR / filename
    out_path.write_bytes(resp.content)
    print(f"[HF T2I] generated: {out_path}")
    return str(out_path)


COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
_COMFYUI_WORKFLOWS_DIR = Path(__file__).parent.parent.parent / "data" / "comfyui_workflows"


def list_comfyui_workflows() -> list[str]:
    if not _COMFYUI_WORKFLOWS_DIR.exists():
        return []
    return [f.stem for f in sorted(_COMFYUI_WORKFLOWS_DIR.glob("*.json"))]


def _load_comfyui_workflow(name: str = "default") -> dict:
    import json as _jl
    path = _COMFYUI_WORKFLOWS_DIR / f"{name}.json"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return _jl.load(f)
        except Exception:
            pass
    return {}


def _comfyui_generate(
    prompt: str, width: int, height: int, model_name: str | None,
    negative_prompt: str, seed: int, steps: int, cfg_scale: float,
) -> str:
    import json as _json
    import copy

    try:
        import streamlit as _st
        _wf_name = _st.session_state.get("comfyui_workflow", "default")
    except Exception:
        _wf_name = "default"
    workflow = copy.deepcopy(_load_comfyui_workflow(_wf_name))
    if not workflow:
        raise RuntimeError(f"ComfyUIワークフローが見つかりません: data/comfyui_workflows/{_wf_name}.json")
    current_ckpt = workflow.get("4", {}).get("inputs", {}).get("ckpt_name", "")
    if model_name:
        workflow["4"]["inputs"]["ckpt_name"] = model_name
    elif not current_ckpt:
        try:
            info = requests.get(f"{COMFYUI_URL}/object_info/CheckpointLoaderSimple", timeout=5).json()
            choices = info.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
            if choices:
                workflow["4"]["inputs"]["ckpt_name"] = choices[0]
                print(f"[COMFYUI T2I] auto-selected model: {choices[0]}")
        except Exception as _e:
            print(f"[COMFYUI T2I] model auto-detect failed: {_e}")
    workflow["5"]["inputs"]["width"] = width or 512
    workflow["5"]["inputs"]["height"] = height or 768
    workflow["6"]["inputs"]["text"] = prompt
    workflow["7"]["inputs"]["text"] = negative_prompt or ""
    workflow["3"]["inputs"]["seed"] = seed if seed >= 0 else int(time.time())
    workflow["3"]["inputs"]["steps"] = steps if steps > 0 else 20
    workflow["3"]["inputs"]["cfg"] = cfg_scale if cfg_scale > 0 else 7.0

    resp = requests.post(
        f"{COMFYUI_URL}/prompt",
        json={"prompt": workflow},
        timeout=10,
    )
    if resp.status_code != 200:
        print(f"[COMFYUI T2I] prompt error {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    prompt_id = resp.json().get("prompt_id")
    print(f"[COMFYUI T2I] queued: prompt_id={prompt_id}")

    for _ in range(120):
        time.sleep(2)
        hist_resp = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
        if hist_resp.status_code != 200:
            continue
        history = hist_resp.json()
        if prompt_id not in history:
            continue
        outputs = history[prompt_id].get("outputs", {})
        for node_id, node_output in outputs.items():
            images = node_output.get("images", [])
            if images:
                img_info = images[0]
                img_resp = requests.get(
                    f"{COMFYUI_URL}/view",
                    params={"filename": img_info["filename"], "subfolder": img_info.get("subfolder", ""), "type": img_info.get("type", "output")},
                    timeout=30,
                )
                img_resp.raise_for_status()
                ASSET_DIR.mkdir(parents=True, exist_ok=True)
                filename = f"comfyui_{int(time.time() * 1000)}.png"
                out_path = ASSET_DIR / filename
                out_path.write_bytes(img_resp.content)
                print(f"[COMFYUI T2I] generated: {out_path}")
                return str(out_path)
        if history[prompt_id].get("status", {}).get("status_str") == "error":
            _msg = history[prompt_id].get("status", {}).get("messages", [])
            raise RuntimeError(f"ComfyUI生成エラー: {_msg}")

    raise RuntimeError("ComfyUI: タイムアウト（240秒）")


def list_comfyui_models() -> list[str]:
    try:
        resp = requests.get(f"{COMFYUI_URL}/object_info/CheckpointLoaderSimple", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return data.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
    except Exception:
        return []


def list_a1111_models() -> list[str]:
    try:
        resp = requests.get(f"{A1111_URL}/sdapi/v1/sd-models", timeout=10)
        resp.raise_for_status()
        return [m["title"] for m in resp.json()]
    except Exception:
        return []


def get_a1111_current_model() -> str | None:
    try:
        resp = requests.get(f"{A1111_URL}/sdapi/v1/options", timeout=5)
        resp.raise_for_status()
        return resp.json().get("sd_model_checkpoint")
    except Exception:
        return None
