from def_kari.translation.translation_provider import TranslationProvider

_REGISTRY: dict[str, type[TranslationProvider]] = {}


def register_provider(name: str, cls: type[TranslationProvider]) -> None:
    _REGISTRY[name] = cls


def create_provider(name: str, **kwargs) -> TranslationProvider:
    if name not in _REGISTRY:
        raise ValueError(
            f"Unknown translation provider: '{name}'. "
            f"Available: {list(_REGISTRY.keys())}"
        )
    return _REGISTRY[name](**kwargs)


def _register_defaults() -> None:
    from def_kari.translation.library_provider import LibraryTranslationProvider
    from def_kari.translation.deepl_provider import DeepLTranslationProvider
    from def_kari.translation.llm_provider import LlmTranslationProvider
    from def_kari.translation.argos_provider import ArgosTranslationProvider
    register_provider("library", LibraryTranslationProvider)
    register_provider("deepl", DeepLTranslationProvider)
    register_provider("llm", LlmTranslationProvider)
    register_provider("argos", ArgosTranslationProvider)


_register_defaults()
