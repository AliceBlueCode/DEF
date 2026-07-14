"""Player Agent: Character が所有するエージェント層。

設計哲学:
  Character（永続） → PlayerAgent（役割） → Runtime: LLM | Human | Rule（差し替え可能）

Phase 3 実装:
  - Planner は静的（profile.json の goals を読む）
  - Runtime は LLM のみ
  - Goal を session_context に注入して「目的ある発言」を実現する

Phase 4 追加:
  - Memory（episodic）を読み込んで session_context に注入
  - Planner が LLM を使って即座の行動意図を生成
  - settings: trpg_planner_enabled=True のときのみ Planner LLM を実行
"""

from def_kari.llm.client import generate_structured_reply
from def_kari.llm.backend import DEFAULT_LLM_BACKEND, LLM_BACKENDS
from def_kari.settings import load_settings


class PlayerAgent:
    """Character を所有するエージェント。

    Goal（長期/中期/直近）と episodic memory をシステムプロンプトに注入し、
    ただ「会話する」ではなく「目的と記憶を持って発言する」キャラクターを実現する。
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
        char_id: str = "",
    ) -> dict:
        """episodic memory・Goal・Planner を注入した上で generate_structured_reply を呼び出す。

        Args:
            character: get_character() の返値（goals / knowledge フィールドを含む）
            user_text: ターン指示テキスト
            history: セッション履歴（LLM 向けに変換済み）
            model: LLM モデル名
            backend: バックエンドID
            session_context: セッション情報コンテキスト（Context Builder から渡される）
            allowed_sexual / allowed_violence: コンテンツフィルタ
            current_emotion: 直前の感情状態
            char_id: キャラクターID（episodic memory 読み込みに使用）

        Returns:
            generate_structured_reply() と同形式の dict
        """
        try:
            settings = load_settings()
        except Exception:
            settings = {}
        user_lang = settings.get("user_language", "ja") or "ja"

        # ① episodic memory 注入
        _resolved_char_id = char_id or character.get("id", "")
        if _resolved_char_id:
            from def_kari.gm.memory import load_episodic
            episodes = load_episodic(_resolved_char_id, limit=3)
            if episodes:
                mem_ctx = self._build_memory_context(episodes, user_lang)
                if mem_ctx:
                    session_context = session_context + "\n\n" + mem_ctx

        # ② Goal 注入（静的）
        goal_ctx = self._build_goal_context(character.get("goals", {}), user_lang)
        if goal_ctx:
            session_context = session_context + "\n\n" + goal_ctx

        # ③ Planner（LLM）: settings で有効化されているときのみ実行
        if settings.get("trpg_planner_enabled") and history:
            goals = character.get("goals", {})
            if goals and any(goals.values()):
                situation = "\n".join(h.get("content", "") for h in history[-3:])
                plan = self._plan_action(character, situation, goals, user_lang, backend, model)
                if plan:
                    label = "【あなたの行動意図】" if user_lang == "ja" else "[Your intended action]"
                    session_context = session_context + f"\n\n{label}{plan}"

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

    # ── 内部メソッド ──────────────────────────────────────────────

    def _build_goal_context(self, goals: dict, user_language: str) -> str:
        """Goals dict → システムプロンプト注入用テキスト。"""
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

    def _build_memory_context(self, episodes: list[dict], user_language: str) -> str:
        """episodic memories → システムプロンプト注入用テキスト。"""
        if not episodes:
            return ""
        _is_ja = user_language == "ja"
        lines = ["【過去のセッションの記憶】" if _is_ja else "[Past Session Memories]"]
        for ep in episodes:
            date = ep.get("date", "")[:10]
            topic = ep.get("topic", "")
            moments = ep.get("key_moments", [])
            if _is_ja:
                line = f"・({date}) 「{topic}」"
                if moments:
                    snippet = "、".join(m[:30] for m in moments[-2:])
                    line += f" — {snippet}"
            else:
                line = f'- ({date}) "{topic}"'
                if moments:
                    line += f" — {moments[-1][:60]}"
            lines.append(line)
        return "\n".join(lines)

    def _plan_action(
        self,
        character: dict,
        situation: str,
        goals: dict,
        user_lang: str,
        backend_id: str,
        model: str,
    ) -> str:
        """行動意図を1文で生成する（Planner LLM呼び出し）。

        Goals と直近の状況から「この場面でキャラが何をしようとするか」を
        1文（30字以内）で生成する。失敗時は "" を返す（silent fallback）。
        """
        if not goals or not any(goals.values()):
            return ""
        if backend_id not in LLM_BACKENDS:
            backend_id = DEFAULT_LLM_BACKEND
        chat_fn = LLM_BACKENDS[backend_id].get("chat")
        if not chat_fn:
            return ""

        name = character.get("name", "キャラクター")
        goal_lines = []
        if goals.get("long_term"):
            goal_lines.append(("長期目標" if user_lang == "ja" else "Long-term") + f": {goals['long_term']}")
        if goals.get("mid_term"):
            goal_lines.append(("中期目標" if user_lang == "ja" else "Mid-term") + f": {goals['mid_term']}")
        if goals.get("immediate"):
            goal_lines.append(("直近の目標" if user_lang == "ja" else "Immediate") + f": {goals['immediate']}")

        if user_lang == "ja":
            system = (
                f"あなたは{name}の行動意図を生成するプランナーです。\n"
                "【目標】\n" + "\n".join(goal_lines) + "\n\n"
                "以下の状況を踏まえ、このキャラクターが「今この場面で何をしようとするか」を"
                "30字以内の1文で答えてください。動詞で終わること。余分な説明は不要。"
            )
        else:
            system = (
                f"You are a planner generating the action intention for {name}.\n"
                "Goals:\n" + "\n".join(goal_lines) + "\n\n"
                "Given the situation below, describe in one sentence (max 15 words) "
                "what this character intends to do right now. End with a verb. No explanation."
            )

        try:
            result = chat_fn(
                [{"role": "system", "content": system}, {"role": "user", "content": situation}],
                "",
                json_mode=False,
                options={"num_predict": 60},
            )
            return (result or "").strip()
        except Exception:
            return ""


# モジュールレベルのシングルトン（session.py から参照）
_player_agent = PlayerAgent()
