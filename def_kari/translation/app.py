"""翻訳プロバイダ抽象化 PoC — 設定・テスト画面"""

import sys
from pathlib import Path

import streamlit as st
import yaml

CONFIG_PATH = Path(__file__).parent / "config.yaml"

sys.path.insert(0, str(Path(__file__).parent))

from config_loader import load_config, create_provider_from_config
from translation_factory import create_provider


def _load_config() -> dict:
    return load_config(CONFIG_PATH)


def _save_config(config: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)


st.set_page_config(page_title="DEF Translation PoC", layout="wide")
st.title("DEF 翻訳プロバイダ抽象化 PoC")

config = _load_config()
t_config = config.setdefault("translation", {})

st.sidebar.header("プロバイダ設定")

provider_options = ["library", "deepl", "llm"]
current_provider = t_config.get("provider", "library")
selected_provider = st.sidebar.selectbox(
    "翻訳プロバイダ",
    provider_options,
    index=provider_options.index(current_provider),
)

if selected_provider == "deepl":
    st.sidebar.subheader("DeepL 設定")
    deepl_config = t_config.setdefault("deepl", {})

    api_key = st.sidebar.text_input(
        "DeepL API Key",
        value=deepl_config.get("api_key", ""),
        type="password",
        help="無料プランのキーは末尾が :fx",
    )
    deepl_config["api_key"] = api_key

    formality = st.sidebar.selectbox(
        "Formality",
        ["default", "more", "less", "prefer_more", "prefer_less"],
        index=0,
        help="翻訳の丁寧さ（日本語等の対応言語のみ有効）",
    )
    deepl_config["formality"] = formality

elif selected_provider == "llm":
    st.sidebar.subheader("LLM 設定")
    llm_config = t_config.setdefault("llm", {})

    base_url = st.sidebar.text_input(
        "Base URL",
        value=llm_config.get("base_url", "http://127.0.0.1:5000/v1"),
    )
    llm_config["base_url"] = base_url

    model = st.sidebar.text_input(
        "Model",
        value=llm_config.get("model", ""),
        help="空欄の場合、バックエンドのデフォルトモデルを使用",
    )
    llm_config["model"] = model

    llm_api_key = st.sidebar.text_input(
        "API Key",
        value=llm_config.get("api_key", "not-needed"),
        type="password",
        help="ローカルLLMの場合は不要",
    )
    llm_config["api_key"] = llm_api_key

t_config["provider"] = selected_provider

if st.sidebar.button("設定を保存"):
    _save_config(config)
    st.sidebar.success("保存しました")

st.divider()

col1, col2 = st.columns(2)

with col1:
    st.subheader("翻訳テスト")

    source_lang = st.selectbox("ソース言語", ["ja", "en", "zh", "ko", "de", "fr"])
    target_lang = st.selectbox("ターゲット言語", ["en", "ja", "zh", "ko", "de", "fr"], index=1)
    input_text = st.text_area("翻訳するテキスト", height=150)

    if st.button("翻訳", type="primary"):
        if not input_text.strip():
            st.warning("テキストを入力してください")
        else:
            try:
                provider = create_provider_from_config(config=config)
                st.info(f"プロバイダ: **{provider.provider_name}**")

                with st.spinner("翻訳中..."):
                    result = provider.translate(
                        input_text, source_lang, target_lang
                    )
                st.success("翻訳完了")
                st.text_area("翻訳結果", value=result, height=150)

            except Exception as e:
                st.error(f"エラー: {e}")

with col2:
    st.subheader("プロバイダ比較")
    compare_text = st.text_area("比較用テキスト", height=150, key="compare_input")
    compare_source = st.selectbox("ソース", ["ja", "en"], key="cmp_src")
    compare_target = st.selectbox("ターゲット", ["en", "ja"], index=1, key="cmp_tgt")

    if st.button("全プロバイダで翻訳"):
        if not compare_text.strip():
            st.warning("テキストを入力してください")
        else:
            providers_to_test = [("library", {})]

            deepl_key = t_config.get("deepl", {}).get("api_key", "")
            if deepl_key:
                providers_to_test.append(
                    ("deepl", {"api_key": deepl_key})
                )

            for name, kwargs in providers_to_test:
                try:
                    p = create_provider(name, **kwargs)
                    with st.spinner(f"{name} で翻訳中..."):
                        r = p.translate(compare_text, compare_source, compare_target)
                    st.markdown(f"**{name}:** {r}")
                except Exception as e:
                    st.markdown(f"**{name}:** エラー — {e}")
