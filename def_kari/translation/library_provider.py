from translation_provider import TranslationProvider


class LibraryTranslationProvider(TranslationProvider):
    """Python翻訳ライブラリによるアダプター（デフォルト）。

    deep-translatorを使用。APIコスト不要・オフライン動作可能。
    """

    def __init__(self) -> None:
        from deep_translator import GoogleTranslator
        self._translator_class = GoogleTranslator

    def translate(
        self,
        text: str,
        source: str,
        target: str,
        adapter_options: dict | None = None,
    ) -> str:
        translator = self._translator_class(source=source, target=target)
        return translator.translate(text)

    def translate_batch(
        self,
        texts: list[str],
        source: str,
        target: str,
        adapter_options: dict | None = None,
    ) -> list[str]:
        translator = self._translator_class(source=source, target=target)
        return translator.translate_batch(texts)

    @property
    def provider_name(self) -> str:
        return "library"
