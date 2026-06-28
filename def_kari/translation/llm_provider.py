import os

import requests

from translation_provider import TranslationProvider

_DEFAULT_SYSTEM_PROMPT = (
    "You are a professional translator. "
    "Translate the given text accurately while preserving the original tone and nuance. "
    "Output ONLY the translated text, nothing else."
)


class LlmTranslationProvider(TranslationProvider):
    """LLMバックエンド（OpenAI互換API）による翻訳アダプター。

    DEFが既に持つLLMインフラ（TGW / Ollama / OpenAI / Gemini）を
    翻訳に再利用する。文脈考慮・用語最適化・ブランドトーン統一に強い。

    adapter_options で以下を指定可能:
        system_prompt: カスタムシステムプロンプト
        glossary: 用語集（dict[str, str]）を翻訳に反映
        temperature: 生成温度（デフォルト: 0.1）
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._base_url = (
            base_url
            or os.environ.get("LLM_TRANSLATION_URL", "http://127.0.0.1:5000/v1")
        )
        self._api_key = (
            api_key
            or os.environ.get("LLM_TRANSLATION_API_KEY", "not-needed")
        )
        self._model = (
            model
            or os.environ.get("LLM_TRANSLATION_MODEL", "")
        )

    def _build_messages(
        self,
        text: str,
        source: str,
        target: str,
        adapter_options: dict | None = None,
    ) -> list[dict]:
        opts = adapter_options or {}
        system_prompt = opts.get("system_prompt", _DEFAULT_SYSTEM_PROMPT)

        glossary = opts.get("glossary")
        if glossary:
            glossary_lines = "\n".join(
                f"- {k} → {v}" for k, v in glossary.items()
            )
            system_prompt += (
                f"\n\nUse the following glossary for translation:\n{glossary_lines}"
            )

        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Translate the following text from {source} to {target}:\n\n{text}",
            },
        ]

    def _call_llm(
        self,
        messages: list[dict],
        adapter_options: dict | None = None,
    ) -> str:
        opts = adapter_options or {}
        body: dict = {
            "messages": messages,
            "temperature": opts.get("temperature", 0.1),
        }
        if self._model:
            body["model"] = self._model

        resp = requests.post(
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()

    def translate(
        self,
        text: str,
        source: str,
        target: str,
        adapter_options: dict | None = None,
    ) -> str:
        messages = self._build_messages(text, source, target, adapter_options)
        return self._call_llm(messages, adapter_options)

    def translate_batch(
        self,
        texts: list[str],
        source: str,
        target: str,
        adapter_options: dict | None = None,
    ) -> list[str]:
        return [
            self.translate(t, source, target, adapter_options)
            for t in texts
        ]

    @property
    def provider_name(self) -> str:
        return "llm"
