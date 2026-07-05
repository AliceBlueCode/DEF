"""T2Iバックエンド切替"""

from def_kari.t2i.adapters import a1111, civitai, huggingface, comfyui

T2I_BACKENDS = {
    "a1111":       a1111.generate,
    "civitai":     civitai.generate,
    "huggingface": huggingface.generate,
    "comfyui":     comfyui.generate,
}

T2I_BACKEND_LABELS = {
    "a1111":       "Automatic1111 (ローカル)",
    "civitai":     "Civitai API",
    "huggingface": "Hugging Face API",
    "comfyui":     "ComfyUI (ローカル)",
}


def generate_image(
    prompt: str,
    backend: str,
    width: int = 512,
    height: int = 768,
    model: str | None = None,
    negative_prompt: str = "",
    seed: int = -1,
    steps: int = 0,
    cfg_scale: float = 0.0,
    workflow_name: str = "",
) -> str:
    fn = T2I_BACKENDS.get(backend)
    if fn is None:
        raise ValueError(f"Unknown T2I backend: {backend}")

    kwargs: dict = dict(
        prompt=prompt,
        width=width,
        height=height,
        model=model,
        negative_prompt=negative_prompt,
        seed=seed,
    )
    if steps > 0:
        kwargs["steps"] = steps
    if cfg_scale > 0:
        kwargs["cfg_scale"] = cfg_scale
    if backend == "comfyui" and workflow_name:
        kwargs["workflow_name"] = workflow_name

    return fn(**kwargs)
