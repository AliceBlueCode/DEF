from abc import ABC, abstractmethod


class TranslationProvider(ABC):
    """DEF翻訳プロバイダ抽象インターフェース。

    LLM(2.3節)/T2I(2.4節)/TTS(2.5節)と同じアダプターパターンに従う。
    DEFコアエンジンはこのインターフェースを通じてのみ翻訳を要求する。
    """

    @abstractmethod
    def translate(
        self,
        text: str,
        source: str,
        target: str,
        adapter_options: dict | None = None,
    ) -> str:
        """テキストを翻訳する。

        Args:
            text: 翻訳対象テキスト。
            source: ソース言語コード（例: "ja", "en"）。
            target: ターゲット言語コード（例: "en", "ja"）。
            adapter_options: 各バックエンド固有の追加パラメータ。

        Returns:
            翻訳されたテキスト。
        """

    @abstractmethod
    def translate_batch(
        self,
        texts: list[str],
        source: str,
        target: str,
        adapter_options: dict | None = None,
    ) -> list[str]:
        """複数テキストを一括翻訳する。

        Args:
            texts: 翻訳対象テキストのリスト。
            source: ソース言語コード。
            target: ターゲット言語コード。
            adapter_options: 各バックエンド固有の追加パラメータ。

        Returns:
            翻訳されたテキストのリスト（入力と同じ順序）。
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """プロバイダの識別名を返す。"""
