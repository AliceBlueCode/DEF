"""ルールシステムの失敗で、卓を止めて知らせる（B-027）・ダメージ表の決まり・本体の拡張の引き方。

実装レビュー2（2026-11-14）の🟡3と🟢の分。GM の語り・AI の手番・ダイスの、どの道から失敗しても、
黙って先へ進めず、卓を止めて理由を返す。
"""

from unittest.mock import patch

import pytest

from def_kari.trpg import registry


class _Broken:
    id = "_broken"

    def build_rule_context(self, rulebook, scenario, lang):
        raise RuntimeError("broken plugin")

    def allowed_skills(self, rulebook):
        raise RuntimeError("broken plugin")


def test_rule_context_failure_reaches_the_caller():
    """C-002: 以前はルールの説明を空にして続けていた。今は RuleSystemError のまま呼ぶ側へ。"""
    from def_kari.gm import context_builder
    with patch.object(registry, "for_rulebook", return_value=_Broken()):
        with pytest.raises(registry.RuleSystemError):
            context_builder.build_trpg_context({"rule_system": "_broken"}, None, "ja")


def test_gm_narrate_returns_a_rule_system_error():
    from def_kari.gm.gm_agent import GMAgent
    session = {"id": "_gm_rs", "trpg_mode": True, "trpg_rulebook": "", "history": [], "name_map": {},
               "initiative": [], "characters": []}
    with patch("def_kari.gm.gm_agent.build_for_gm", side_effect=registry.RuleSystemError("broken plugin")):
        out = GMAgent().narrate(session=session, backend_id="textgen_webui", inject_history=False)
    assert out["rule_system_error"] is True and "broken plugin" in out["error"]


def test_keeper_pauses_the_table_on_a_rule_system_error():
    from def_kari.api.routes import session_gameplay as g
    from def_kari.api.routes.session_state import _sessions
    sid = "_keeper_rs"
    _sessions[sid] = {"id": sid, "trpg_mode": True, "history": [], "name_map": {}, "ai_paused": False}
    try:
        with patch.object(g._gm_agent, "narrate",
                          return_value={"text": "", "judgments": [], "error": "broken plugin", "rule_system_error": True}), \
                patch("def_kari.api.routes.session_turn_engine._game_event_bus", create=True):
            out = g.ai_keeper_narrate(sid, g.AIKeeperRequest(), _auth={"jti": "h", "role": "host"})
        assert out == {"error": "broken plugin"}
        assert _sessions[sid]["ai_paused"] is True
        assert _sessions[sid]["plugin_error"]["method"] == "gm"
    finally:
        _sessions.pop(sid, None)


def test_ai_turn_pauses_the_table_on_a_rule_system_error():
    from def_kari.api.routes import session_turn_engine as te
    from def_kari.api.routes.session_state import _sessions
    sid = "_turn_rs"
    _sessions[sid] = {"id": sid, "initiative": ["a"], "name_map": {"a": "A"}, "round": 1, "history": [],
                      "ai_paused": False}
    ctx = {"current_char_id": "a", "turn": 0, "counters": {}, "profiles": {}, "char": {},
           "backend_id": "textgen_webui", "model": "", "_skip_gen_before": False}
    try:
        with patch.object(te, "_resolve_turn_start", return_value=(None, ctx)), \
                patch.object(te, "_build_recent_history", return_value=[]), \
                patch.object(te, "_resolve_ai_action", return_value=(None, None, None)), \
                patch.object(te, "_build_turn_prompt_context", side_effect=registry.RuleSystemError("broken plugin")), \
                patch.object(te, "_generate_ai_turn_reply") as gen:
            out = te.next_turn(te.SessionNextRequest(session_id=sid))
        gen.assert_not_called()  # LLM には送らない
        assert out["error"] == "broken plugin"
        assert _sessions[sid]["ai_paused"] is True
    finally:
        _sessions.pop(sid, None)


def test_dice_with_an_unreadable_rulebook_pauses_instead_of_rolling_1d100(monkeypatch):
    """C-002: 卓のルールブックが読めないなら、既定の 1d100 で黙って振らない（実装レビュー2の🔴1）。"""
    from def_kari.api.routes.session_gameplay import SessionDiceRollRequest, session_dice_roll
    from def_kari.api.routes.session_state import _sessions
    sid = "_dice_gone"
    _sessions[sid] = {"id": sid, "trpg_rulebook": "vanished_book", "trpg_rule_system": "def_original",
                      "trpg_plugin_version": "", "history": [], "name_map": {}, "human_char_ids": [], "players": {}}
    rolled = []
    monkeypatch.setattr("def_kari.trpg.rule_engine.secrets.randbelow", lambda n: rolled.append(n) or 0)
    try:
        with patch("def_kari.api.routes.session_gameplay._game_event_bus"):
            out = session_dice_roll(sid, SessionDiceRollRequest(skill_value=5), _auth={"jti": "h", "role": "host"})
        assert "cannot be read" in out["error"]
        assert rolled == [] and _sessions[sid]["ai_paused"] is True
    finally:
        _sessions.pop(sid, None)


# ── ダメージ表: 致命の結果は「result があり stat の無い項目」 ─────────────────────

@pytest.mark.parametrize("entry,expected", [
    ({"roll": 1, "result": "即死"}, "fatal"),
    ({"roll": 1, "result": "骨折", "stat": "STR", "delta": -1}, "damage"),
    ({"roll": 1, "stat": "STR", "delta": -1}, "damage"),
])
def test_damage_fatal_only_without_stat(monkeypatch, entry, expected):
    system = registry.get("def_original")
    monkeypatch.setattr("def_kari.trpg.rule_engine.roll_dice", lambda n: {"total": 1})
    book = {"damage_mechanics": {"damage_table": {"entries": [entry]}}}
    assert system.damage_roll(book)["result"] == expected


# ── 名前で探す関数は、本体の拡張の一覧に書いたものだけ ─────────────────────────

def test_judgment_functions_are_rule_extensions():
    system = registry.get("def_original")
    assert {"judgment_system_prompt", "skill_corrections"} <= registry.RULE_EXTENSIONS
    assert callable(registry.extension(system, "judgment_system_prompt"))
    assert isinstance(registry.extension(system, "skill_corrections"), dict)
    assert registry.extension(_Broken(), "skill_corrections") is None
