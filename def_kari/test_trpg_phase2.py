"""Phase 2 検証: Event Bus + Domain モデルが依存なしで動作することを確認する。

使用方法:
  cd e:\tools\DEF
  python -m def_kari.test_trpg_phase2
"""


# ── Event Bus ─────────────────────────────────────────────────────

def test_event_bus_emit_and_log():
    from def_kari.gm.events import GameEventBus, JUDGMENT_RESOLVED, SCENE_NARRATED

    bus = GameEventBus()
    received = []
    bus.subscribe(JUDGMENT_RESOLVED, lambda sid, ev: received.append(ev))

    bus.emit("sess-1", JUDGMENT_RESOLVED, {"roll": 45, "success": True})
    bus.emit("sess-1", SCENE_NARRATED, {"text": "霧が立ち込める路地。"})
    bus.emit("sess-2", JUDGMENT_RESOLVED, {"roll": 99, "fumble": True})

    # ハンドラはsession横断で発火する（session_idでフィルタしない）
    assert len(received) == 2
    assert received[0]["type"] == JUDGMENT_RESOLVED
    assert received[0]["session_id"] == "sess-1"
    assert received[0]["payload"]["roll"] == 45
    assert received[1]["session_id"] == "sess-2"

    log1 = bus.get_log("sess-1")
    assert len(log1) == 2
    assert log1[0]["type"] == JUDGMENT_RESOLVED
    assert log1[1]["type"] == SCENE_NARRATED

    log2 = bus.get_log("sess-2")
    assert len(log2) == 1
    assert log2[0]["payload"]["fumble"] is True

    print("PASS: event_bus_emit_and_log")


def test_event_bus_clear_log():
    from def_kari.gm.events import GameEventBus, SESSION_ENDED

    bus = GameEventBus()
    bus.emit("sess-x", SESSION_ENDED, {})
    assert len(bus.get_log("sess-x")) == 1

    bus.clear_log("sess-x")
    assert bus.get_log("sess-x") == []

    bus.clear_log("nonexistent")  # 存在しないセッションは無視
    print("PASS: event_bus_clear_log")


def test_event_bus_handler_exception_does_not_propagate():
    from def_kari.gm.events import GameEventBus, FLAG_UPDATED

    bus = GameEventBus()

    def bad_handler(sid, ev):
        raise RuntimeError("handler error")

    bus.subscribe(FLAG_UPDATED, bad_handler)
    bus.emit("sess-err", FLAG_UPDATED, {"key": "gate_open", "value": True})
    assert len(bus.get_log("sess-err")) == 1  # ログには残る
    print("PASS: event_bus_handler_exception_does_not_propagate")


def test_event_constants_unique():
    from def_kari.gm import events as ev

    constants = [
        ev.JUDGMENT_RESOLVED, ev.SCENE_NARRATED, ev.SCENE_CHANGED,
        ev.NPC_DEAD, ev.FLAG_UPDATED, ev.DAMAGE_APPLIED,
        ev.STATUS_CHANGED, ev.TOPIC_CHANGED, ev.SESSION_ENDED,
    ]
    assert len(constants) == len(set(constants)), "イベント定数に重複がある"
    print("PASS: event_constants_unique")


# ── Domain: World ─────────────────────────────────────────────────

def test_world_from_dict_roundtrip():
    from def_kari.gm.domain import World

    data = {
        "id": "arkham_1920",
        "name": "アーカム",
        "setting": "1920年代のニューイングランド",
        "locations": [
            {"id": "miskatonic", "name": "ミスカトニック大学", "description": "古い大学", "connections": ["main_street"]},
            {"id": "main_street", "name": "メインストリート", "connections": ["miskatonic"]},
        ],
        "npcs": [
            {"id": "armitage", "name": "アーミテージ博士", "description": "図書館長", "alive": True, "current_location": "miskatonic"},
        ],
    }

    world = World.from_dict(data)
    assert world.id == "arkham_1920"
    assert len(world.locations) == 2
    assert len(world.npcs) == 1

    npc = world.get_npc("armitage")
    assert npc is not None
    assert npc.alive is True

    loc = world.get_location("miskatonic")
    assert loc is not None
    assert "main_street" in loc.connections

    assert world.get_npc("unknown") is None
    assert world.get_location("unknown") is None

    restored = World.from_dict(world.to_dict())
    assert restored.id == world.id
    assert len(restored.npcs) == len(world.npcs)
    print("PASS: world_from_dict_roundtrip")


# ── Domain: Story ─────────────────────────────────────────────────

def test_story_from_dict_and_scene_navigation():
    from def_kari.gm.domain import Story

    data = {
        "id": "haunted_house",
        "title": "呪われた屋敷",
        "synopsis": "古い屋敷の謎を解け",
        "scenes": [
            {"id": "s1", "title": "到着", "description": "屋敷に到着した。"},
            {"id": "s2", "title": "探索", "description": "廊下を探索する。"},
            {"id": "s3", "title": "対決", "description": "怪物と対決。"},
        ],
        "flags": {"found_key": False},
        "current_scene_index": 0,
    }

    story = Story.from_dict(data)
    assert story.title == "呪われた屋敷"
    assert len(story.scenes) == 3

    scene = story.current_scene()
    assert scene is not None
    assert scene.title == "到着"

    advanced = story.advance_scene()
    assert advanced is True
    assert story.current_scene().title == "探索"

    story.advance_scene()
    assert story.current_scene().title == "対決"

    at_end = story.advance_scene()
    assert at_end is False  # 最後のシーン
    assert story.current_scene().title == "対決"

    story.set_flag("found_key", True)
    assert story.get_flag("found_key") is True
    assert story.get_flag("missing", "default") == "default"

    restored = Story.from_dict(story.to_dict())
    assert restored.current_scene_index == story.current_scene_index
    assert restored.get_flag("found_key") is True
    print("PASS: story_from_dict_and_scene_navigation")


def test_story_from_scenario_json():
    from def_kari.gm.domain import Story

    scenario = {
        "id": "poc_scenario",
        "title": "テストシナリオ",
        "synopsis": "動作確認用",
        "scenes": [
            {"title": "導入", "description": "探索者たちは集まった。"},
            {"title": "展開", "description": "事件が起きた。"},
        ],
    }

    story = Story.from_scenario_json(scenario)
    assert story.id == "poc_scenario"
    assert len(story.scenes) == 2
    assert story.scenes[0].id == "scene_0"
    assert story.scenes[1].id == "scene_1"
    assert story.current_scene_index == 0
    print("PASS: story_from_scenario_json")


# ── Domain: Campaign ──────────────────────────────────────────────

def test_campaign_from_dict():
    from def_kari.gm.domain import Campaign

    data = {
        "id": "arkham_campaign",
        "title": "アーカムの影",
        "world_id": "arkham_1920",
        "scenario_ids": ["haunted_house", "dark_ritual", "final_confrontation"],
        "current_scenario_index": 1,
        "completed_scenarios": ["haunted_house"],
    }

    campaign = Campaign.from_dict(data)
    assert campaign.title == "アーカムの影"
    assert campaign.current_scenario_id() == "dark_ritual"
    assert len(campaign.completed_scenarios) == 1

    restored = Campaign.from_dict(campaign.to_dict())
    assert restored.current_scenario_id() == campaign.current_scenario_id()
    print("PASS: campaign_from_dict")


def test_campaign_out_of_range():
    from def_kari.gm.domain import Campaign

    campaign = Campaign(id="c1", title="test", scenario_ids=[], current_scenario_index=0)
    assert campaign.current_scenario_id() is None
    print("PASS: campaign_out_of_range")


# ── singleton からのインポート確認 ─────────────────────────────────

def test_game_event_bus_singleton():
    from def_kari.gm.events import game_event_bus, GameEventBus
    assert isinstance(game_event_bus, GameEventBus)
    print("PASS: game_event_bus_singleton")


if __name__ == "__main__":
    test_event_constants_unique()
    test_event_bus_emit_and_log()
    test_event_bus_clear_log()
    test_event_bus_handler_exception_does_not_propagate()
    test_game_event_bus_singleton()
    test_world_from_dict_roundtrip()
    test_story_from_dict_and_scene_navigation()
    test_story_from_scenario_json()
    test_campaign_from_dict()
    test_campaign_out_of_range()
    print("\nPhase 2 tests: all passed.")
