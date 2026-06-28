import os

import requests

from translation_provider import TranslationProvider

_LANG_MAP = {
    "en": "EN",
    "ja": "JA",
    "zh": "ZH",
    "ko": "KO",
    "de": "DE",
    "fr": "FR",
    "es": "ES",
    "pt": "PT-BR",
    "it": "IT",
    "ru": "RU",
}


class DeepLTranslationProvider(TranslationProvider):
    """DeepL API による翻訳アダプター。

    無料プラン: 月500,000文字。
    API キーは環境変数 DEEPL_API_KEY または adapter_options で指定。
    """

    def __init__(self, api_key: str | None = None, **kwargs) -> None:
        self._api_key = api_key or os.environ.get("DEEPL_API_KEY", "")
        if not self._api_key:
            try:
                from def_kari.secrets_store import get_api_key
                self._api_key = get_api_key("deepl") or ""
            except Exception:
                pass
        self._default_formality = kwargs.get("formality", "default")
        if not self._api_key:
            raise ValueError(
                "DeepL API key is required. "
                "Set DEEPL_API_KEY environment variable or pass api_key."
            )
        if self._api_key.endswith(":fx"):
            self._base_url = "https://api-free.deepl.com/v2"
        else:
            self._base_url = "https://api.deepl.com/v2"

    def _to_deepl_lang(self, lang: str) -> str:
        return _LANG_MAP.get(lang, lang.upper())

    def translate(
        self,
        text: str,
        source: str,
        target: str,
        adapter_options: dict | None = None,
    ) -> str:
        params = {
            "text": [text],
            "source_lang": self._to_deepl_lang(source),
            "target_lang": self._to_deepl_lang(target),
        }
        if adapter_options:
            if "formality" in adapter_options:
                params["formality"] = adapter_options["formality"]
            if "glossary_id" in adapter_options:
                params["glossary_id"] = adapter_options["glossary_id"]

        resp = requests.post(
            f"{self._base_url}/translate",
            headers={"Authorization": f"DeepL-Auth-Key {self._api_key}"},
            json=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["translations"][0]["text"]

    def translate_batch(
        self,
        texts: list[str],
        source: str,
        target: str,
        adapter_options: dict | None = None,
    ) -> list[str]:
        params = {
            "text": texts,
            "source_lang": self._to_deepl_lang(source),
            "target_lang": self._to_deepl_lang(target),
        }
        if adapter_options:
            if "formality" in adapter_options:
                params["formality"] = adapter_options["formality"]
            if "glossary_id" in adapter_options:
                params["glossary_id"] = adapter_options["glossary_id"]

        resp = requests.post(
            f"{self._base_url}/translate",
            headers={"Authorization": f"DeepL-Auth-Key {self._api_key}"},
            json=params,
            timeout=30,
        )
        resp.raise_for_status()
        return [t["text"] for t in resp.json()["translations"]]

    @property
    def provider_name(self) -> str:
        return "deepl"
