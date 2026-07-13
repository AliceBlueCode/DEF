"""Player Agent: Character が所有するエージェント層。

設計哲学:
  Character（永続） → PlayerAgent（役割） → Runtime: LLM | Human | Rule（差し替え可能）

Phase 3 ミニマル実装:
  - Planner は静的（profile.jsonの goals を読む）
  - Runtime は LLM のみ
  - Goal を system prompt に注入して「目的ある発言」を実現する

Phase 4 で追加予定:
  - Memory（episodic/knowledge/relationship）との連携
  - Planner の LLM 化（状況に応じた immediate goal 生成）
"""

from def_kari.llm.client import generate_structured_reply
from def_kari.llm.backend import DEFAULT_LLM_BACKEND
from def_kari.settings import load_settings


class PlayerAgent:
    """Character を所有するエージェント。

    Goal（長期/中期/直近）をシステムプロンプトに注入し、
    ただ「会話する」ではなく「目的を持って発言する」キャラクターを実現する。
    """

    def narrate(
        self,
        character: dict,
        user_text: str,
        history: list[dict],
        model: str = "",
        backend: str = DEFAULT_LLM_BACKEND,
        session_context: str = "",
        allowed_sexual: list[str] | None = None,
        allowed_violence: list[str] | None = None,
        current_emotion: str = "",
    ) -> dict:
        """Goal コンテキストを注入した上で generate_structured_reply を呼び出す。

        Args:
            character: get_character() の返値（goals フィールドを含む）
            user_text: ターン指示テキスト
            history: セッション履歴（LLM 向けに変換済み）
            model: LLM モデル名
            backend: バックエンドID
            session_context: セッション情報コンテキスト
            allowed_sexual / allowed_violence: コンテンツフィルタ
            current_emotion: 直前の感情状態

        Returns:
            generate_structured_reply() と同形式の dict
        """
        try:
            settings = load_settings()
        except Exception:
            settings = {}
        user_lang = settings.get("user_language", "ja") or "ja"

        goal_ctx = self._build_goal_context(character.get("goals", {}), user_lang)
        if goal_ctx:
            session_context = session_context + "\n\n" + goal_ctx

        return generate_structured_reply(
            user_text=user_text,
            history=history,
            model=model,
            character=character,
            backend=backend,
            session_context=session_context,
            allowed_sexual=allowed_sexual,
            allowed_violence=allowed_violence,
            current_emotion=current_emotion,
        )

    def _build_goal_context(self, goals: dict, user_language: str) -> str:
        """Goals dict → システムプロンプト注入用テキスト。

        Phase 3 では静的に読むだけ。
        Phase 4 で Planner が immediate goal を LLM 生成する予定。
        """
        if not goals:
            return ""

        long_term = goals.get("long_term", "")
        mid_term = goals.get("mid_term", "")
        immediate = goals.get("immediate", "")

        if not any([long_term, mid_term, immediate]):
            return ""

        _is_ja = user_language == "ja"
        parts = ["【あなたの目標】" if _is_ja else "[Your Goals]"]

        if _is_ja:
            if long_term:
                parts.append(f"長期目標: {long_term}")
            if mid_term:
                parts.append(f"中期目標: {mid_term}")
            if immediate:
                parts.append(f"直近の目標: {immediate}")
            parts.append(
                "上記の目標を意識しながら、今この場面でどう立ち回るか考えて発言してください。"
            )
        else:
            if long_term:
                parts.append(f"Long-term: {long_term}")
            if mid_term:
                parts.append(f"Mid-term: {mid_term}")
            if immediate:
                parts.append(f"Immediate: {immediate}")
            parts.append(
                "Keep these goals in mind and think about how to act in this moment."
            )

        return "\n".join(parts)


# モジュールレベルのシングルトン（session.py から参照）
_player_agent = PlayerAgent()
