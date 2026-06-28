from translation_provider import TranslationProvider


class ArgosTranslationProvider(TranslationProvider):
    """Argos Translate（オフラインNMT）によるアダプター。

    APIコスト不要・完全オフライン動作。
    言語ペアごとの翻訳パッケージが必要（CC0-1.0ライセンス）。
    パッケージ未導入時は空文字を返す（呼び出し側でフォールバック可能）。
    """

    def __init__(self, auto_install: bool = False, **kwargs) -> None:
        self._auto_install = auto_install

    def _translate_one(self, text: str, source: str, target: str) -> str:
        if source == target:
            return text
        try:
            import argostranslate.translate

            if self._auto_install:
                import argostranslate.package
                argostranslate.package.update_package_index()
                available = argostranslate.package.get_available_packages()
                pkg = next(
                    (p for p in available if p.from_code == source and p.to_code == target),
                    None,
                )
                if pkg:
                    argostranslate.package.install_from_path(pkg.download())

            return argostranslate.translate.translate(text, source, target)
        except Exception:
            return ""

    def translate(
        self,
        text: str,
        source: str,
        target: str,
        adapter_options: dict | None = None,
    ) -> str:
        return self._translate_one(text, source, target)

    def translate_batch(
        self,
        texts: list[str],
        source: str,
        target: str,
        adapter_options: dict | None = None,
    ) -> list[str]:
        return [self._translate_one(t, source, target) for t in texts]

    @property
    def provider_name(self) -> str:
        return "argos"
