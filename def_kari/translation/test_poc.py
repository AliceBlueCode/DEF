"""翻訳プロバイダ抽象化 PoC検証スクリプト。

検証項目:
1. インターフェースが正しく動作するか
2. ライブラリアダプターが翻訳を実行できるか
3. ファクトリーによるプロバイダ切り替えが機能するか
4. 未登録プロバイダの指定時にエラーが出るか
5. DeepLプロバイダの初期化検証（APIキー不要のテスト）
6. LLMプロバイダの初期化・メッセージ構築検証（接続不要のテスト）
7. DeepLプロバイダの実翻訳テスト（APIキーがある場合のみ）
8. LLMプロバイダの実翻訳テスト（LLMが起動している場合のみ）
"""

import os
import sys


def test_interface():
    from translation_provider import TranslationProvider

    class DummyProvider(TranslationProvider):
        def translate(self, text, source, target, adapter_options=None):
            return f"[{target}] {text}"

        def translate_batch(self, texts, source, target, adapter_options=None):
            return [f"[{target}] {t}" for t in texts]

        @property
        def provider_name(self):
            return "dummy"

    p = DummyProvider()
    assert p.provider_name == "dummy"
    assert p.translate("hello", "en", "ja") == "[ja] hello"
    assert p.translate_batch(["a", "b"], "en", "ja") == ["[ja] a", "[ja] b"]
    print("PASS: interface")


def test_library_provider():
    from library_provider import LibraryTranslationProvider

    p = LibraryTranslationProvider()
    assert p.provider_name == "library"

    result = p.translate("Hello", "en", "ja")
    print(f"  'Hello' -> '{result}'")
    assert isinstance(result, str)
    assert len(result) > 0

    results = p.translate_batch(["Good morning", "Thank you"], "en", "ja")
    print(f"  batch -> {results}")
    assert len(results) == 2

    print("PASS: library_provider")


def test_factory():
    from translation_factory import create_provider

    p = create_provider("library")
    assert p.provider_name == "library"

    result = p.translate("Good night", "en", "ja")
    print(f"  factory('library'): 'Good night' -> '{result}'")

    try:
        create_provider("nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        print(f"  factory('nonexistent'): {e}")

    print("PASS: factory")


def test_custom_registration():
    from translation_factory import register_provider, create_provider
    from translation_provider import TranslationProvider

    class UpperCaseProvider(TranslationProvider):
        def translate(self, text, source, target, adapter_options=None):
            return text.upper()

        def translate_batch(self, texts, source, target, adapter_options=None):
            return [t.upper() for t in texts]

        @property
        def provider_name(self):
            return "uppercase"

    register_provider("uppercase", UpperCaseProvider)
    p = create_provider("uppercase")
    assert p.translate("hello", "en", "en") == "HELLO"
    print("PASS: custom_registration")


def test_deepl_init():
    from unittest import mock
    from deepl_provider import DeepLTranslationProvider

    # secrets_store にキーがある場合でも空キー渡しは ValueError になること
    with mock.patch("def_kari.secrets_store.get_api_key", return_value=None), \
         mock.patch.dict("os.environ", {}, clear=False):
        import os
        saved = os.environ.pop("DEEPL_API_KEY", None)
        try:
            DeepLTranslationProvider(api_key="")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        finally:
            if saved is not None:
                os.environ["DEEPL_API_KEY"] = saved

    p = DeepLTranslationProvider(api_key="test-key:fx")
    assert p.provider_name == "deepl"
    assert p._base_url == "https://api-free.deepl.com/v2"

    p2 = DeepLTranslationProvider(api_key="test-key-pro")
    assert p2._base_url == "https://api.deepl.com/v2"

    print("PASS: deepl_init")


def test_llm_init():
    from llm_provider import LlmTranslationProvider

    p = LlmTranslationProvider(
        base_url="http://localhost:5000/v1",
        model="test-model",
    )
    assert p.provider_name == "llm"

    messages = p._build_messages("こんにちは", "ja", "en")
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "ja" in messages[1]["content"]
    assert "en" in messages[1]["content"]
    assert "こんにちは" in messages[1]["content"]

    messages_with_glossary = p._build_messages(
        "DEFは創作プラットフォームです", "ja", "en",
        adapter_options={"glossary": {"DEF": "DEF(kari)", "創作": "creative work"}},
    )
    assert "glossary" in messages_with_glossary[0]["content"].lower()
    assert "DEF(kari)" in messages_with_glossary[0]["content"]

    print("PASS: llm_init")


def test_deepl_live():
    api_key = os.environ.get("DEEPL_API_KEY", "")
    if not api_key:
        print("SKIP: deepl_live (DEEPL_API_KEY not set)")
        return

    from deepl_provider import DeepLTranslationProvider

    p = DeepLTranslationProvider(api_key=api_key)
    result = p.translate("Hello, world!", "en", "ja")
    print(f"  DeepL: 'Hello, world!' -> '{result}'")
    assert isinstance(result, str)
    assert len(result) > 0

    results = p.translate_batch(
        ["Good morning", "Character Persistence"], "en", "ja"
    )
    print(f"  DeepL batch: {results}")
    assert len(results) == 2

    print("PASS: deepl_live")


def test_llm_live():
    import requests

    base_url = os.environ.get(
        "LLM_TRANSLATION_URL", "http://127.0.0.1:5000/v1"
    )
    try:
        requests.get(f"{base_url}/models", timeout=3)
    except (requests.ConnectionError, requests.Timeout):
        print(f"SKIP: llm_live (LLM not reachable at {base_url})")
        return

    from llm_provider import LlmTranslationProvider

    p = LlmTranslationProvider(base_url=base_url)
    result = p.translate("Hello, world!", "en", "ja")
    print(f"  LLM: 'Hello, world!' -> '{result}'")
    assert isinstance(result, str)
    assert len(result) > 0

    result_glossary = p.translate(
        "DEF ensures Character Persistence.",
        "en", "ja",
        adapter_options={
            "glossary": {
                "DEF": "DEF(kari)",
                "Character Persistence": "キャラクターの継続的存在感",
            }
        },
    )
    print(f"  LLM (glossary): '{result_glossary}'")

    print("PASS: llm_live")


def test_config_default():
    from config_loader import create_provider_from_config

    p = create_provider_from_config(config={"translation": {"provider": "library"}})
    assert p.provider_name == "library"

    result = p.translate("Thank you", "en", "ja")
    print(f"  config(library): 'Thank you' -> '{result}'")

    print("PASS: config_default")


def test_config_switch():
    from config_loader import create_provider_from_config

    config_deepl = {
        "translation": {
            "provider": "deepl",
            "deepl": {"api_key": "test-key:fx"},
        }
    }
    p = create_provider_from_config(config=config_deepl)
    assert p.provider_name == "deepl"

    config_llm = {
        "translation": {
            "provider": "llm",
            "llm": {"base_url": "http://localhost:5000/v1"},
        }
    }
    p2 = create_provider_from_config(config=config_llm)
    assert p2.provider_name == "llm"

    print("PASS: config_switch")


def test_config_file():
    from config_loader import load_config, create_provider_from_config

    config = load_config()
    expected = config.get("translation", {}).get("provider", "library")

    p = create_provider_from_config()
    assert p.provider_name == expected
    print(f"  config.yaml provider: {p.provider_name}")

    print("PASS: config_file")


def test_argos_init():
    from argos_provider import ArgosTranslationProvider

    p = ArgosTranslationProvider()
    assert p.provider_name == "argos"

    result = p.translate("Hello", "en", "en")
    assert result == "Hello"

    print("PASS: argos_init")


def test_argos_in_factory():
    from translation_factory import create_provider

    p = create_provider("argos")
    assert p.provider_name == "argos"
    print("PASS: argos_in_factory")


if __name__ == "__main__":
    test_interface()
    test_library_provider()
    test_factory()
    test_custom_registration()
    test_deepl_init()
    test_llm_init()
    test_argos_init()
    test_argos_in_factory()
    test_config_default()
    test_config_switch()
    test_config_file()
    test_deepl_live()
    test_llm_live()
    print("\nAll PoC tests completed.")
