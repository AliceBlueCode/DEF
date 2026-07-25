"""T2Iバックエンド切替"""

from def_kari.t2i.adapters import a1111, civitai, huggingface, comfyui, openai_dalle

T2I_BACKENDS = {
    "a1111":       a1111.generate,
    "civitai":     civitai.generate,
    "huggingface": huggingface.generate,
    "comfyui":     comfyui.generate,
    "openai":      openai_dalle.generate,
}

T2I_BACKEND_LABELS = {
    "a1111":       "Automatic1111 (ローカル)",
    "civitai":     "Civitai API",
    "huggingface": "Hugging Face API",
    "comfyui":     "ComfyUI (ローカル)",
    "openai":      "OpenAI DALL-E (外部API)",
}

_COMPATIBLE_T2I_IDS: set[str] = set()


def _register_compatible_t2i_backends():
    try:
        from def_kari.compatible_backends_store import all_backends_with_keys
        from def_kari.t2i.adapters.compatible import make_generate_fn
        for entry in all_backends_with_keys():
            if "t2i" not in entry.get("capabilities", []):
                continue
            name = entry["name"]
            T2I_BACKENDS[name] = make_generate_fn(
                base_url=entry["base_url"],
                api_key=entry["api_key"],
                default_model=entry.get("model", ""),
                name=name,
                extra_headers=entry.get("extra_headers") or None,
            )
            T2I_BACKEND_LABELS[name] = entry.get("label", name)
            _COMPATIBLE_T2I_IDS.add(name)
    except Exception:
        pass


_register_compatible_t2i_backends()


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

    if model and (steps == 0 or cfg_scale == 0.0):
        try:
            from def_kari.models.t2i_profiles import get_profile
            _profile = get_profile(model)
            if steps == 0:
                steps = _profile["steps"]
            if cfg_scale == 0.0:
                cfg_scale = _profile["cfg_scale"]
        except Exception:
            pass

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
