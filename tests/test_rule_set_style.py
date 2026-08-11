"""ルールセットのstyle（discussion/performative）による発言指示の切り替えテスト。

build_turn_instruction()は従来rule_setを一切見ておらず、全セッション共通で
「自分の立場から意見を述べてください」という議論調の指示を注入していた。これが
manzai/rakugo/roleplay等performative系ルールセットの指示（文字数制限・役割演技等）
と正面から食い違い、ルール自体は正しく注入されていても議論寄りの長文へ引っ張られる
原因になっていた（2026-08-10発覚）。session["style"]で discussion/performative を
判定し、performative系では議論を促さない軽い指示に切り替える。
"""

from def_kari.gm.context_builder import build_turn_instruction


def test_discussion_style_first_turn_asks_for_opinion():
    session = {"style": "discussion"}
    text = build_turn_instruction(0, "A", ["B"], "topic", [], "a", session, {}, "ja")
    assert "立場" in text or "考え" in text


def test_performative_style_first_turn_does_not_ask_for_opinion():
    session = {"style": "performative"}
    text = build_turn_instruction(0, "A", ["B"], "topic", [], "a", session, {}, "ja")
    assert "立場" not in text
    assert "考え" not in text
    assert "ルール" in text


def test_discussion_style_mid_session_asks_for_opinion():
    session = {"style": "discussion", "round": 1, "turn": 0}
    history = [{"role": "assistant", "character_id": "b", "content": "B: hello"}]
    text = build_turn_instruction(0, "A", ["B"], "topic", history, "a", session, {}, "ja")
    assert "意見を述べて" in text


def test_performative_style_mid_session_does_not_ask_for_opinion():
    session = {"style": "performative", "round": 1, "turn": 0}
    history = [{"role": "assistant", "character_id": "b", "content": "B: hello"}]
    text = build_turn_instruction(0, "A", ["B"], "topic", history, "a", session, {}, "ja")
    assert "意見を述べて" not in text
    assert "ルール" in text


def test_default_style_is_discussion_when_unset():
    """styleキーが無いセッション（旧autosave等）はdiscussion扱いで従来通りの挙動を維持すること。"""
    session = {}
    text = build_turn_instruction(0, "A", ["B"], "topic", [], "a", session, {}, "ja")
    assert "立場" in text or "考え" in text


def test_trpg_mode_ignores_style():
    """TRPGモードはstyleに関わらず専用の探索者向け指示を使うこと。"""
    session = {"style": "performative", "trpg_mode": True}
    text = build_turn_instruction(0, "A", ["B"], "topic", [], "a", session, {}, "ja")
    assert "探索者" in text


def test_performative_style_reminds_max_chars_first_turn():
    session = {"style": "performative", "max_chars": 150}
    text = build_turn_instruction(0, "A", ["B"], "topic", [], "a", session, {}, "ja")
    assert "150字" in text


def test_performative_style_reminds_max_chars_mid_session():
    session = {"style": "performative", "max_chars": 150, "round": 1, "turn": 0}
    history = [{"role": "assistant", "character_id": "b", "content": "B: hello"}]
    text = build_turn_instruction(0, "A", ["B"], "topic", history, "a", session, {}, "ja")
    assert "150字" in text


def test_performative_style_without_max_chars_has_no_reminder():
    """max_charsが設定されていない（roleplay等）performativeルールセットでは、
    存在しない上限を捏造して提示しないこと。"""
    session = {"style": "performative"}
    text = build_turn_instruction(0, "A", ["B"], "topic", [], "a", session, {}, "ja")
    assert "字以内" not in text


def test_performative_style_within_max_rounds_continues_normally():
    session = {"style": "performative", "max_rounds": 6, "round": 3, "turn": 0}
    history = [{"role": "assistant", "character_id": "b", "content": "B: hello"}]
    text = build_turn_instruction(0, "A", ["B"], "topic", history, "a", session, {}, "ja")
    assert "畳んで" not in text
    assert "続けてください" in text


def test_performative_style_over_max_rounds_forces_wrap_up():
    session = {"style": "performative", "max_rounds": 6, "round": 13, "turn": 0}
    history = [{"role": "assistant", "character_id": "b", "content": "B: hello"}]
    text = build_turn_instruction(0, "A", ["B"], "topic", history, "a", session, {}, "ja")
    assert "畳んで" in text
    assert "13" in text
    assert "大落ち" in text


def test_performative_style_without_max_rounds_never_forces_wrap_up():
    """max_roundsが設定されていない（roleplay等）performativeルールセットでは、
    ラウンド数に関わらず強制終了指示を出さないこと。"""
    session = {"style": "performative", "round": 999, "turn": 0}
    history = [{"role": "assistant", "character_id": "b", "content": "B: hello"}]
    text = build_turn_instruction(0, "A", ["B"], "topic", history, "a", session, {}, "ja")
    assert "畳んで" not in text


def test_discussion_style_reminds_conciseness_after_others_spoke():
    """discussionスタイルは1人目には「簡潔に」と指示するが、2人目以降
    （他の参加者の発言に触れる指示）にはこの指示が抜けており、ラウンドを
    追うごとに応答が長文化する原因になっていた（2026-08-11発覚）。
    毎ターン簡潔さを再掲することで抑止する。"""
    session = {"style": "discussion", "round": 1, "turn": 0}
    history = [{"role": "assistant", "character_id": "b", "content": "B: hello"}]
    text = build_turn_instruction(0, "A", ["B"], "topic", history, "a", session, {}, "ja")
    assert "簡潔" in text


def test_discussion_style_reminds_conciseness_first_turn():
    session = {"style": "discussion"}
    text = build_turn_instruction(0, "A", ["B"], "topic", [], "a", session, {}, "ja")
    assert "簡潔" in text


def test_discussion_style_reminds_conciseness_after_others_spoke_en():
    session = {"style": "discussion", "round": 1, "turn": 0}
    history = [{"role": "assistant", "character_id": "b", "content": "B: hello"}]
    text = build_turn_instruction(0, "A", ["B"], "topic", history, "a", session, {}, "en")
    assert "concisely" in text


def test_discussion_style_reminds_max_chars_first_turn():
    """8.32対策: max_charsの毎ターン再掲がperformativeスタイル限定になっており、
    discussion系（default.json等、rules文中に「発言は2〜200文字程度」と書いてあるだけ）
    では全く同じ理由（履歴の重みに埋もれる）で無視され続けていた（2026-08-11発覚）。"""
    session = {"style": "discussion", "max_chars": 200}
    text = build_turn_instruction(0, "A", ["B"], "topic", [], "a", session, {}, "ja")
    assert "200字" in text


def test_discussion_style_reminds_max_chars_mid_session():
    session = {"style": "discussion", "max_chars": 200, "round": 1, "turn": 0}
    history = [{"role": "assistant", "character_id": "b", "content": "B: hello"}]
    text = build_turn_instruction(0, "A", ["B"], "topic", history, "a", session, {}, "ja")
    assert "200字" in text


def test_discussion_style_reminds_max_chars_mid_session_others_not_spoken():
    """他の参加者がまだ発言していない1人目の分岐にも同じ再掲が入ること。"""
    session = {"style": "discussion", "max_chars": 200, "round": 1, "turn": 0}
    text = build_turn_instruction(0, "A", ["B"], "topic", [{"role": "user", "content": "hi"}], "a", session, {}, "ja")
    assert "200字" in text


def test_discussion_style_reminds_max_chars_en():
    session = {"style": "discussion", "max_chars": 200, "round": 1, "turn": 0}
    history = [{"role": "assistant", "character_id": "b", "content": "B: hello"}]
    text = build_turn_instruction(0, "A", ["B"], "topic", history, "a", session, {}, "en")
    assert "200 characters" in text


def test_discussion_style_without_max_chars_has_no_reminder():
    """max_charsが設定されていない（gentle.json等）discussionルールセットでは、
    存在しない上限を捏造して提示しないこと。"""
    session = {"style": "discussion"}
    text = build_turn_instruction(0, "A", ["B"], "topic", [], "a", session, {}, "ja")
    assert "字程度" not in text


def test_discussion_style_reminds_max_chars_on_additional_action():
    """同一ターン内でaction_count > 0（追加アクション）の分岐にも再掲されること。"""
    session = {"style": "discussion", "max_chars": 200, "round": 1, "turn": 0}
    history = [{
        "role": "assistant", "character_id": "a", "content": "A: hello",
        "round": 1, "turn": 0,
    }]
    text = build_turn_instruction(1, "A", ["B"], "topic", history, "a", session, {}, "ja")
    assert "200字" in text
