"""Phase 3.5 検証: Context Builder GM/Player/NPC分離が正しく動作することを確認する。

使用方法:
  cd e:\tools\DEF
  python -m def_kari.test_trpg_phase35
"""

# ── テスト用フィクスチャ ────────────────────────────────────────────

_RULEBOOK = {
    "rule_system_name": "クトゥルフの呼び声",
    "world_setting": "1920年代、秘密の恐怖",
    "dice_system": "1d100",
    "judgment": {"success_condition": "roll_lte_skill"},
    "golden_rule": "楽しむこと",
}

_SCENARIO = {
    "title": "邪神の館",
    "synopsis": "古い館に秘密が眠る",
    "scenes": [
        {
            "title": "玄関ホール",
            "description": "薄暗い玄関ホール。埃が積もっている。",
            "gm_notes": "床下に隠し扉がある",
            "npcs": ["butler"],
        }
    ],
    "npcs": [
        {
            "id": "butler",
            "name": "執事ウィルソン",
            "description": "恭しい老執事",
            "gm_notes": "実は邪神に憑依されている",
            "goal": "探索者を館に閉じ込める",
        }
    ],
    "flags": [
        {"key": "found_secret_door", "value": False, "gm_only": False},
        {"key": "butler_is_possessed", "value": True, "gm_only": True},
    ],
}

_SESSION = {
    "current_scene_index": 0,
    "player_knowledge": {
        "char_hanfei": ["前回のセッションで謎のメモを発見した"],
        "char_akagi": [],
    },
}

_CHARACTER = {
    "name": "韓非",
    "knowledge": ["この館の主人は10年前に失踪した"],
}


# ── build_for_gm ──────────────────────────────────────────────────

def test_build_for_gm_includes_gm_notes():
    from def_kari.gm.context_builder import build_for_gm
    ctx = build_for_gm(_RULEBOOK, _SCENARIO, _SESSION, "ja")
    assert "床下に隠し扉がある" in ctx, f"gm_notes が含まれていない:\n{ctx}"
    print("PASS: build_for_gm includes scene gm_notes")


def test_build_for_gm_includes_npc_secrets():
    from def_kari.gm.context_builder import build_for_gm
    ctx = build_for_gm(_RULEBOOK, _SCENARIO, _SESSION, "ja")
    assert "実は邪神に憑依されている" in ctx, f"NPC gm_notes が含まれていない:\n{ctx}"
    assert "探索者を館に閉じ込める" in ctx, f"NPC goal が含まれていない:\n{ctx}"
    print("PASS: build_for_gm includes NPC gm_notes and goal")


def test_build_for_gm_includes_gm_only_flags():
    from def_kari.gm.context_builder import build_for_gm
    ctx = build_for_gm(_RULEBOOK, _SCENARIO, _SESSION, "ja")
    assert "butler_is_possessed" in ctx, f"gm_only フラグが含まれていない:\n{ctx}"
    assert "（GM専用）" in ctx, f"GM専用ラベルが含まれていない:\n{ctx}"
    print("PASS: build_for_gm includes gm_only flags")


def test_build_for_gm_no_scenario():
    from def_kari.gm.context_builder import build_for_gm
    ctx = build_for_gm(_RULEBOOK, None, _SESSION, "ja")
    assert "クトゥルフの呼び声" in ctx
    assert "邪神の館" not in ctx
    print("PASS: build_for_gm works without scenario")


# ── build_for_player ──────────────────────────────────────────────

def test_build_for_player_excludes_gm_notes():
    from def_kari.gm.context_builder import build_for_player
    ctx = build_for_player("char_hanfei", _CHARACTER, _RULEBOOK, _SCENARIO, _SESSION, "ja")
    assert "床下に隠し扉がある" not in ctx, f"gm_notes が漏れている:\n{ctx}"
    assert "実は邪神に憑依されている" not in ctx, f"NPC gm_notes が漏れている:\n{ctx}"
    assert "探索者を館に閉じ込める" not in ctx, f"NPC goal が漏れている:\n{ctx}"
    print("PASS: build_for_player excludes all gm_notes and NPC goals")


def test_build_for_player_excludes_gm_only_flags():
    from def_kari.gm.context_builder import build_for_player
    ctx = build_for_player("char_hanfei", _CHARACTER, _RULEBOOK, _SCENARIO, _SESSION, "ja")
    assert "butler_is_possessed" not in ctx, f"gm_only フラグが漏れている:\n{ctx}"
    print("PASS: build_for_player excludes gm_only flags")


def test_build_for_player_includes_public_info():
    from def_kari.gm.context_builder import build_for_player
    ctx = build_for_player("char_hanfei", _CHARACTER, _RULEBOOK, _SCENARIO, _SESSION, "ja")
    assert "薄暗い玄関ホール" in ctx, f"公開シーン情報が含まれていない:\n{ctx}"
    assert "恭しい老執事" in ctx, f"NPC公開情報が含まれていない:\n{ctx}"
    assert "found_secret_door" in ctx, f"公開フラグが含まれていない:\n{ctx}"
    print("PASS: build_for_player includes public scene/NPC/flag info")


def test_build_for_player_includes_static_knowledge():
    from def_kari.gm.context_builder import build_for_player
    ctx = build_for_player("char_hanfei", _CHARACTER, _RULEBOOK, _SCENARIO, _SESSION, "ja")
    assert "この館の主人は10年前に失踪した" in ctx, f"静的knowledge が含まれていない:\n{ctx}"
    print("PASS: build_for_player includes static knowledge from character")


def test_build_for_player_includes_dynamic_knowledge():
    from def_kari.gm.context_builder import build_for_player
    ctx = build_for_player("char_hanfei", _CHARACTER, _RULEBOOK, _SCENARIO, _SESSION, "ja")
    assert "前回のセッションで謎のメモを発見した" in ctx, f"動的knowledge が含まれていない:\n{ctx}"
    print("PASS: build_for_player includes dynamic knowledge from session")


def test_build_for_player_no_other_char_knowledge():
    """別キャラの knowledge は自分のコンテキストに含まれない。"""
    from def_kari.gm.context_builder import build_for_player
    # char_akagi は knowledge なし
    ctx = build_for_player("char_akagi", {"name": "赤城", "knowledge": []}, _RULEBOOK, _SCENARIO, _SESSION, "ja")
    assert "前回のセッションで謎のメモを発見した" not in ctx, f"他キャラの knowledge が漏れている:\n{ctx}"
    print("PASS: build_for_player does not leak other char's knowledge")


# ── build_for_npc ─────────────────────────────────────────────────

def test_build_for_npc_includes_goal():
    from def_kari.gm.context_builder import build_for_npc
    npc_data = {
        "goal": "探索者を欺く",
        "knowledge": ["館の地下に祭壇がある"],
        "relationship": {},
    }
    ctx = build_for_npc("butler", npc_data, _RULEBOOK, _SCENARIO, _SESSION, "ja")
    assert "探索者を欺く" in ctx, f"NPC goal が含まれていない:\n{ctx}"
    assert "館の地下に祭壇がある" in ctx, f"NPC knowledge が含まれていない:\n{ctx}"
    print("PASS: build_for_npc includes goal and knowledge")


def test_build_for_npc_includes_relationships():
    from def_kari.gm.context_builder import build_for_npc
    npc_data = {
        "goal": "監視する",
        "knowledge": [],
        "relationship": {"char_hanfei": {"trust": 10, "hostility": 80}},
    }
    ctx = build_for_npc("butler", npc_data, _RULEBOOK, _SCENARIO, _SESSION, "ja")
    assert "char_hanfei" in ctx
    assert "敵意80" in ctx
    print("PASS: build_for_npc includes relationship data")


# ── characters.py knowledge フィールド ────────────────────────────

def test_get_character_exposes_knowledge():
    from def_kari.characters import get_character
    char = get_character("character_claude_001")
    assert "knowledge" in char, "knowledge フィールドが存在しない"
    assert isinstance(char["knowledge"], list), f"knowledge が list でない: {type(char['knowledge'])}"
    print("PASS: get_character exposes knowledge field")


def test_get_character_no_knowledge_returns_empty_list():
    from def_kari.characters import get_character
    char = get_character("character_aoi_001")
    assert char.get("knowledge") == [], f"expected [], got {char.get('knowledge')}"
    print("PASS: get_character returns [] when no knowledge field")


# ── FLAG_UPDATED → player_knowledge 連動 ─────────────────────────

def test_flag_updated_handler_updates_player_knowledge():
    """FLAG_UPDATED（gm_only: False）が player_knowledge を更新することを確認する。"""
    import importlib, types

    # session.py をインポートしてハンドラを取得
    import def_kari.api.routes.session as session_module

    # ダミーセッションを _sessions に挿入
    dummy_session_id = "test-flag-session"
    session_module._sessions[dummy_session_id] = {
        "initiative": ["char_a", "char_b"],
        "player_knowledge": {"char_a": [], "char_b": []},
    }

    try:
        session_module._handle_flag_updated(
            dummy_session_id,
            {"payload": {"key": "found_secret_door", "value": True, "gm_only": False}},
        )
        pk = session_module._sessions[dummy_session_id]["player_knowledge"]
        assert "フラグ「found_secret_door」が更新された（値: True）" in pk["char_a"]
        assert "フラグ「found_secret_door」が更新された（値: True）" in pk["char_b"]
    finally:
        del session_module._sessions[dummy_session_id]

    print("PASS: FLAG_UPDATED handler updates player_knowledge for all chars")


def test_flag_updated_handler_ignores_gm_only():
    """FLAG_UPDATED（gm_only: True）は player_knowledge を更新しない。"""
    import def_kari.api.routes.session as session_module

    dummy_session_id = "test-flag-gm-session"
    session_module._sessions[dummy_session_id] = {
        "initiative": ["char_a"],
        "player_knowledge": {"char_a": []},
    }

    try:
        session_module._handle_flag_updated(
            dummy_session_id,
            {"payload": {"key": "butler_is_possessed", "value": True, "gm_only": True}},
        )
        pk = session_module._sessions[dummy_session_id]["player_knowledge"]
        assert pk["char_a"] == [], f"gm_only フラグが漏れた: {pk['char_a']}"
    finally:
        del session_module._sessions[dummy_session_id]

    print("PASS: FLAG_UPDATED handler ignores gm_only flags")


if __name__ == "__main__":
    test_build_for_gm_includes_gm_notes()
    test_build_for_gm_includes_npc_secrets()
    test_build_for_gm_includes_gm_only_flags()
    test_build_for_gm_no_scenario()
    test_build_for_player_excludes_gm_notes()
    test_build_for_player_excludes_gm_only_flags()
    test_build_for_player_includes_public_info()
    test_build_for_player_includes_static_knowledge()
    test_build_for_player_includes_dynamic_knowledge()
    test_build_for_player_no_other_char_knowledge()
    test_build_for_npc_includes_goal()
    test_build_for_npc_includes_relationships()
    test_get_character_exposes_knowledge()
    test_get_character_no_knowledge_returns_empty_list()
    test_flag_updated_handler_updates_player_knowledge()
    test_flag_updated_handler_ignores_gm_only()
    print("\nPhase 3.5 tests: all passed.")
