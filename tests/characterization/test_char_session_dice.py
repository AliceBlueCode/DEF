"""C-001: `session_gameplay.session_dice_roll()` の今の挙動を固定する（履歴に書く文言、出すイベント、
使うルールブック）。

B-060〜B-062（判定の待ち合わせ、判定値をキャラシートから引く）でわざと変える部分には、C-002 の印を付けた。
"""

from unittest.mock import patch

import pytest

from def_kari.api.routes.session_gameplay import SessionDiceRollRequest, session_dice_roll
from def_kari.api.routes.session_state import _sessions
from def_kari.gm.events import JUDGMENT_RESOLVED

_SID = "_char_session_dice"
_PLAYER_A = {"jti": "j", "role": "player", "char_id": "char_a"}
_HOST = {"jti": "h", "role": "host"}


@pytest.fixture
def sess(use_fixture_rulebooks):
    s = {
        "id": _SID,
        "initiative": ["char_a", "char_b"],
        "human_char_ids": ["char_a"],
        "guest_chars": {},
        "players": {"tok_a": "char_a"},
        "ws_connections": {},
        "name_map": {"char_a": "Alice", "char_b": "Bob"},
        "counters": {},
        "history": [],
        "turn": 0,
        "round": 1,
        "trpg_mode": True,
        "trpg_rulebook": "def_original",
    }
    _sessions[_SID] = s
    yield s
    _sessions.pop(_SID, None)


def _roll(fixed_dice, face, auth=_PLAYER_A, **kwargs):
    req = SessionDiceRollRequest(notation="1d100", **kwargs)
    with fixed_dice(face), \
            patch("def_kari.api.routes.session_gameplay._game_event_bus") as bus, \
            patch("def_kari.api.routes.session_gameplay._autosave"):
        out = session_dice_roll(_SID, req, _auth=auth)
    return out, bus


@pytest.mark.parametrize("face,outcome", [
    (5, "クリティカル！"),
    (30, "成功"),
    (70, "失敗"),
    (100, "ファンブル…"),
])
def test_history_message(sess, fixed_dice, face, outcome):
    _roll(fixed_dice, face, character_id="char_a", stat_name="察知", skill_value=50)
    assert sess["history"][-1] == {
        "role": "user",
        "content": f"🎲 Alice【察知】 {face} / 50 → {outcome}",
        "character_id": "char_a",
    }


def test_history_without_stat_name(sess, fixed_dice):
    _roll(fixed_dice, 30, character_id="char_a", skill_value=50)
    assert sess["history"][-1]["content"] == "🎲 Alice 30 / 50 → 成功"


def test_no_skill_value_no_judgment(sess, fixed_dice):
    out, bus = _roll(fixed_dice, 30, character_id="char_a", stat_name="察知")
    assert out["judgment"] is None
    assert sess["history"][-1]["content"] == "🎲 Alice【察知】 30 / 0"
    bus.emit.assert_not_called()


def test_no_character_no_history(sess, fixed_dice):
    _roll(fixed_dice, 30, auth=_HOST, skill_value=50)
    assert sess["history"] == []


def test_stat_roll_shows_x5_value(sess, fixed_dice):
    _roll(fixed_dice, 30, character_id="char_a", stat_name="思考", skill_value=8, is_stat=True)
    assert sess["history"][-1]["content"] == "🎲 Alice【思考】 30 / 40 → 成功"


def test_event_payload(sess, fixed_dice):
    _, bus = _roll(fixed_dice, 30, character_id="char_a", stat_name="察知", skill_value=50, request_id="r1")
    bus.emit.assert_called_once_with(_SID, JUDGMENT_RESOLVED, {
        "character_id": "char_a",
        "stat_name": "察知",
        "notation": "1d100",
        "roll": 30,
        "judgment_value": 50,
        "success": True,
        "critical": False,
        "fumble": False,
        "request_id": "r1",
    })


def test_response_shape(sess, fixed_dice):
    out, _ = _roll(fixed_dice, 30, character_id="char_a", skill_value=50)
    assert set(out) == {"notation", "rolls", "total", "modifier", "judgment"}
    assert out["rolls"] == [30]


def test_session_rulebook_wins_over_request(sess, fixed_dice, rulebook_dirs):
    """セッションにルールブックがあれば、要求の rulebook_id は使わない。

    要求には「出目が値以上で成功」の別のルールブックを渡し、結果で区別する。
    """
    import json
    import shutil
    from char_helpers import FIXTURE_ROOT
    public, _ = rulebook_dirs
    shutil.copy(FIXTURE_ROOT / "public" / "trpg_rules" / "def_original.json", public / "trpg_rules")
    (public / "trpg_rules" / "other.json").write_text(json.dumps(
        {"id": "other", "dice_system": "1d100", "judgment": {"success_condition": "roll_gte_skill"}}),
        encoding="utf-8")
    out, _ = _roll(fixed_dice, 30, character_id="char_a", skill_value=50, rulebook_id="other")
    assert (out["judgment"]["judgment_type"], out["judgment"]["success"]) == ("roll_lte_skill", True)


def test_request_rulebook_used_when_session_has_none(sess, fixed_dice):
    sess["trpg_rulebook"] = ""
    out, _ = _roll(fixed_dice, 30, character_id="char_a", skill_value=50, rulebook_id="def_original")
    assert out["judgment"]["success"] is True


def test_skill_value_comes_from_request(sess, fixed_dice):
    """C-002: A章でわざと変える挙動（B-062 で判定値をサーバー側のキャラシートから引く）。"""
    out, _ = _roll(fixed_dice, 30, character_id="char_a", stat_name="察知", skill_value=99)
    assert out["judgment"]["judgment_value"] == 99


def test_player_cannot_roll_as_other_character(sess, fixed_dice):
    from fastapi import HTTPException
    sess["human_char_ids"] = ["char_a", "char_b"]
    with pytest.raises(HTTPException) as exc:
        _roll(fixed_dice, 30, character_id="char_b", skill_value=50)
    assert exc.value.status_code == 409
