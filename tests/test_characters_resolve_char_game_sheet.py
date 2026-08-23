"""def_kari.characters.resolve_char_game_sheet(s) のテスト。

ホストのローカルキャラ库（load_profiles()の結果、profilesパラメータ）にキャラが
登録されていれば従来通りそこから解決し、登録が無い場合（guest_xxxxのような
セッション限定の持ち込みキャラ）はsession["guest_chars"]の生JSONへフォールバックする
ことを確認する（2026-08-23、TRPGモードのゲスト参加時にキャラクターシートを
選べない問題の根本原因の修正）。
"""

from def_kari.characters import resolve_char_game_sheet, resolve_char_game_sheets


def test_resolve_char_game_sheet_falls_back_to_guest_chars():
    """profilesに無いキャラは、session["guest_chars"]（flat形式）から解決される。"""
    profiles = {}
    session = {
        "guest_chars": {
            "guest_1": {
                "name": "G",
                "game_rules_sheets": {"s1": {"rulebook_id": "def_original", "skills": {"察知": 40}, "stats": {}}},
            },
        },
    }
    sheet = resolve_char_game_sheet("guest_1", "s1", profiles, session)
    assert sheet == {"rulebook_id": "def_original", "skills": {"察知": 40}, "stats": {}}


def test_resolve_char_game_sheet_versioned_guest_json():
    """session["guest_chars"]がversioned形式（base_profileの兄弟キー）でも解決される。"""
    profiles = {}
    session = {
        "guest_chars": {
            "guest_2": {
                "v1": {
                    "base_profile": {"name": "G2"},
                    "game_rules_sheets": {"s1": {"rulebook_id": "coc", "skills": {}, "stats": {}}},
                },
            },
        },
    }
    sheet = resolve_char_game_sheet("guest_2", "s1", profiles, session)
    assert sheet == {"rulebook_id": "coc", "skills": {}, "stats": {}}


def test_resolve_char_game_sheet_prefers_profiles_over_guest_chars():
    """同じidがprofilesとguest_charsの両方にあれば、ホストのローカルキャラ库
    （profiles）が優先される（既存のホスト所有キャラの挙動は不変）。"""
    profiles = {"char_x": {"game_rules_sheets": {"s1": {"rulebook_id": "from_profiles", "skills": {}, "stats": {}}}}}
    session = {
        "guest_chars": {
            "char_x": {"game_rules_sheets": {"s1": {"rulebook_id": "from_guest_chars", "skills": {}, "stats": {}}}},
        },
    }
    sheet = resolve_char_game_sheet("char_x", "s1", profiles, session)
    assert sheet["rulebook_id"] == "from_profiles"


def test_resolve_char_game_sheet_no_session_no_match_returns_empty():
    """profilesにもsessionにも無ければ空辞書を返す（例外を投げない）。"""
    assert resolve_char_game_sheet("unknown", "s1", {}, None) == {}
    assert resolve_char_game_sheet("unknown", "s1", {}, {"guest_chars": {}}) == {}


def test_resolve_char_game_sheet_empty_sheet_id_returns_empty():
    """sheet_idが空文字なら（未割当キャラ）解決を試みず空辞書を返す。"""
    assert resolve_char_game_sheet("guest_1", "", {}, {"guest_chars": {"guest_1": {}}}) == {}


def test_resolve_char_game_sheets_returns_all_sheets_for_guest():
    """resolve_char_game_sheets（複数形）はcharacters.pyのgame_sheetsエンドポイントが
    使う、キャラの全シートを返す関数。guest_charsフォールバックも同様に効くこと。"""
    session = {
        "guest_chars": {
            "guest_3": {
                "game_rules_sheets": {
                    "s1": {"rulebook_id": "def_original", "skills": {}, "stats": {}},
                    "s2": {"rulebook_id": "coc", "skills": {}, "stats": {}},
                },
            },
        },
    }
    sheets = resolve_char_game_sheets("guest_3", {}, session)
    assert set(sheets.keys()) == {"s1", "s2"}
