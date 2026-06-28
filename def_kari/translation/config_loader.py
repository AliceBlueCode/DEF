import os
from pathlib import Path

import yaml

from translation_provider import TranslationProvider
from translation_factory import create_provider

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config(path: str | Path | None = None) -> dict:
    config_path = Path(path) if path else _DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return {"translation": {"provider": "library"}}
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {"translation": {"provider": "library"}}


def create_provider_from_config(
    config: dict | None = None,
    config_path: str | Path | None = None,
) -> TranslationProvider:
    if config is None:
        config = load_config(config_path)

    t_config = config.get("translation", {})
    provider_name = t_config.get("provider", "library")
    provider_opts = t_config.get(provider_name, {})

    return create_provider(provider_name, **provider_opts)
