"""Phase 4b 検証: NPC Knowledge / Relationship 動的更新。

使用方法:
  cd e:\tools\DEF
  python -m def_kari.test_trpg_phase4b
"""

# ── フィクスチャ ────────────────────────────────────────────────────

_SCENARIO = {
    "title": "邪神の館",
    "synopsis": "古い館に秘密が眠る",
    "scenes": [{"title": "玄関", "description": "薄暗い玄関", "npcs": ["butler"]}],
    "npcs": [
        {
            "id": "butler",
            "name": "執事",
            "description": "老執事",
            "gm_notes": "邪神に憑依",
            "goal": "探索者を閉じ込める",
            "knowledge": ["館に地下室がある"],
            "relationship": {"char_hanfei": {"trust": 40, "hostility": 20}},
        }
    ],
    "flags": [],
}

_SESSION_BASE = {
    "current_scene_index": 0,
    "npc_state": {},
}


# ── build_for_npc: static only ─────────────────────────────────────

def test_build_for_npc_uses_static_knowledge():
    from def_kari.gm.context_builder import build_for_npc
    npc_data = _SCENARIO["npcs"][0]
    ctx = build_for_npc("butler", npc_data, {}, _SCENARIO, _SESSION_BASE, "ja")
    assert "館に地下室がある" in ctx
    assert "探索者を閉じ込める" in ctx
    print("PASS: build_for_npc uses static knowledge and goal")


# ── build_for_npc: static + dynamic merge ─────────────────────────

def test_build_for_npc_merges_dynamic_knowledge():
    from def_kari.gm.context_builder import build_for_npc
    npc_data = _SCENARIO["npcs"][0]
    session = {
        **_SESSION_BASE,
        "npc_state": {
            "butler": {
                "knowledge": ["探索者が扉に気づいた"],
                "relationship": {},
            }
        },
    }
    ctx = build_for_npc("butler", npc_data, {}, _SCENARIO, session, "ja")
    assert "館に地下室がある" in ctx, "静的 knowledge が消えた"
    assert "探索者が扉に気づいた" in ctx, "動的 knowledge が含まれていない"
    print("PASS: build_for_npc merges static + dynamic knowledge")


def test_build_for_npc_dynamic_knowledge_no_duplicate():
    """静的と動的で同じエントリがあっても重複しない。"""
    from def_kari.gm.context_builder import build_for_npc
    npc_data = _SCENARIO["npcs"][0]
    session = {
        **_SESSION_BASE,
        "npc_state": {
            "butler": {
                "knowledge": ["館に地下室がある"],  # 静的と同じ
                "relationship": {},
            }
        },
    }
    ctx = build_for_npc("butler", npc_data, {}, _SCENARIO, session, "ja")
    assert ctx.count("館に地下室がある") == 1, "重複している"
    print("PASS: build_for_npc deduplicates knowledge")


def test_build_for_npc_dynamic_relationship_overrides_static():
    """動的 relationship が静的を上書きする。"""
    from def_kari.gm.context_builder import build_for_npc
    npc_data = _SCENARIO["npcs"][0]  # char_hanfei: trust=40 hostility=20
    session = {
        **_SESSION_BASE,
        "npc_state": {
            "butler": {
                "knowledge": [],
                "relationship": {"char_hanfei": {"trust": 10, "hostility": 90}},  # 上書き
            }
        },
    }
    ctx = build_for_npc("butler", npc_data, {}, _SCENARIO, session, "ja")
    assert "信頼10" in ctx, f"動的 trust が反映されていない:\n{ctx}"
    assert "敵意90" in ctx, f"動的 hostility が反映されていない:\n{ctx}"
    assert "信頼40" not in ctx, "静的 trust が残っている"
    print("PASS: build_for_npc dynamic relationship overrides static")


# ── _build_initial_npc_state ──────────────────────────────────────

def test_build_initial_npc_state_from_scenario(monkeypatch=None):
    """_build_initial_npc_state がシナリオの NPC を正しく初期化する。"""
    import def_kari.api.routes.session as session_module

    # _load_trpg_scenario をモンキーパッチ
    original = session_module._load_trpg_scenario
    session_module._load_trpg_scenario = lambda _: _SCENARIO
    try:
        state = session_module._build_initial_npc_state("dummy_scenario")
        assert "butler" in state
        assert "館に地下室がある" in state["butler"]["knowledge"]
        assert state["butler"]["relationship"]["char_hanfei"]["trust"] == 40
    finally:
        session_module._load_trpg_scenario = original

    print("PASS: _build_initial_npc_state populates from scenario NPC data")


def test_build_initial_npc_state_empty_scenario():
    import def_kari.api.routes.session as session_module
    original = session_module._load_trpg_scenario
    session_module._load_trpg_scenario = lambda _: {}
    try:
        state = session_module._build_initial_npc_state("dummy_scenario")
        assert state == {}
    finally:
        session_module._load_trpg_scenario = original
    print("PASS: _build_initial_npc_state returns {} for scenario with no NPCs")


# ── add_npc_knowledge handler ─────────────────────────────────────

def test_add_npc_knowledge_updates_session():
    """add_npc_knowledge エンドポイントが npc_state を更新することを確認する。"""
    import def_kari.api.routes.session as session_module

    dummy_session_id = "test-npc-knowledge"
    session_module._sessions[dummy_session_id] = {
        "npc_state": {
            "butler": {"knowledge": ["初期知識"], "relationship": {}},
        },
        "initiative": [],
    }
    try:
        from def_kari.api.routes.session import NpcKnowledgeRequest, add_npc_knowledge
        req = NpcKnowledgeRequest(entry="探索者が扉を開けようとした")
        result = add_npc_knowledge(dummy_session_id, "butler", req)
        assert "探索者が扉を開けようとした" in result["knowledge"]
        assert "初期知識" in result["knowledge"]
    finally:
        del session_module._sessions[dummy_session_id]

    print("PASS: add_npc_knowledge updates npc_state.knowledge")


def test_add_npc_knowledge_no_duplicate():
    """同じエントリを2回追加しても重複しない。"""
    import def_kari.api.routes.session as session_module
    from def_kari.api.routes.session import NpcKnowledgeRequest, add_npc_knowledge

    dummy_session_id = "test-npc-nodup"
    session_module._sessions[dummy_session_id] = {
        "npc_state": {"butler": {"knowledge": [], "relationship": {}}},
        "initiative": [],
    }
    try:
        req = NpcKnowledgeRequest(entry="同じ情報")
        add_npc_knowledge(dummy_session_id, "butler", req)
        add_npc_knowledge(dummy_session_id, "butler", req)
        state = session_module._sessions[dummy_session_id]["npc_state"]["butler"]
        assert state["knowledge"].count("同じ情報") == 1
    finally:
        del session_module._sessions[dummy_session_id]

    print("PASS: add_npc_knowledge prevents duplicate entries")


# ── update_npc_relationship handler ──────────────────────────────

def test_update_npc_relationship():
    """update_npc_relationship が関係値を正しく更新する。"""
    import def_kari.api.routes.session as session_module
    from def_kari.api.routes.session import NpcRelationshipRequest, update_npc_relationship

    dummy_session_id = "test-npc-rel"
    session_module._sessions[dummy_session_id] = {
        "npc_state": {
            "butler": {"knowledge": [], "relationship": {"char_hanfei": {"trust": 40, "hostility": 20}}},
        },
    }
    try:
        req = NpcRelationshipRequest(char_id="char_hanfei", hostility=80)
        result = update_npc_relationship(dummy_session_id, "butler", req)
        # hostility だけ更新、trust は変わらない
        assert result["relationship"]["hostility"] == 80
        assert result["relationship"]["trust"] == 40
    finally:
        del session_module._sessions[dummy_session_id]

    print("PASS: update_npc_relationship updates partial fields correctly")


def test_update_npc_relationship_clamps():
    """関係値は 0〜100 にクランプされる。"""
    import def_kari.api.routes.session as session_module
    from def_kari.api.routes.session import NpcRelationshipRequest, update_npc_relationship

    dummy_session_id = "test-npc-clamp"
    session_module._sessions[dummy_session_id] = {
        "npc_state": {"butler": {"knowledge": [], "relationship": {}}},
    }
    try:
        req = NpcRelationshipRequest(char_id="char_a", trust=150, hostility=-10)
        result = update_npc_relationship(dummy_session_id, "butler", req)
        assert result["relationship"]["trust"] == 100
        assert result["relationship"]["hostility"] == 0
    finally:
        del session_module._sessions[dummy_session_id]

    print("PASS: update_npc_relationship clamps values to [0, 100]")


if __name__ == "__main__":
    test_build_for_npc_uses_static_knowledge()
    test_build_for_npc_merges_dynamic_knowledge()
    test_build_for_npc_dynamic_knowledge_no_duplicate()
    test_build_for_npc_dynamic_relationship_overrides_static()
    test_build_initial_npc_state_from_scenario()
    test_build_initial_npc_state_empty_scenario()
    test_add_npc_knowledge_updates_session()
    test_add_npc_knowledge_no_duplicate()
    test_update_npc_relationship()
    test_update_npc_relationship_clamps()
    print("\nPhase 4b tests: all passed.")
