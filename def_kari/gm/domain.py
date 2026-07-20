"""GM Domain Models: World / Story / Campaign の不変データ構造。

JSON互換のdataclassとして定義する。
永続化はJSONファイル経由（data/public/trpg_worlds/ 等）。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any


# ── World ─────────────────────────────────────────────────────────

@dataclass
class WorldLocation:
    id: str
    name: str
    description: str = ""
    connections: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> WorldLocation:
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            description=d.get("description", ""),
            connections=list(d.get("connections", [])),
        )

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class WorldNPC:
    id: str
    name: str
    description: str = ""
    alive: bool = True
    current_location: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> WorldNPC:
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            description=d.get("description", ""),
            alive=bool(d.get("alive", True)),
            current_location=d.get("current_location", ""),
        )

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class World:
    id: str
    name: str
    setting: str = ""
    locations: list[WorldLocation] = field(default_factory=list)
    npcs: list[WorldNPC] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> World:
        return cls(
            id=d.get("id", ""),
            name=d.get("name", ""),
            setting=d.get("setting", ""),
            locations=[WorldLocation.from_dict(loc) for loc in d.get("locations", [])],
            npcs=[WorldNPC.from_dict(npc) for npc in d.get("npcs", [])],
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "setting": self.setting,
            "locations": [loc.to_dict() for loc in self.locations],
            "npcs": [npc.to_dict() for npc in self.npcs],
        }

    def get_npc(self, npc_id: str) -> WorldNPC | None:
        return next((n for n in self.npcs if n.id == npc_id), None)

    def get_location(self, loc_id: str) -> WorldLocation | None:
        return next((loc for loc in self.locations if loc.id == loc_id), None)


# ── Story ─────────────────────────────────────────────────────────

@dataclass
class StoryChapter:
    id: str
    title: str
    scene_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> StoryChapter:
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            scene_ids=list(d.get("scene_ids", [])),
        )

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class StoryScene:
    id: str
    title: str
    description: str = ""
    location_id: str = ""
    required_flags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> StoryScene:
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            location_id=d.get("location_id", ""),
            required_flags=list(d.get("required_flags", [])),
        )

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class Story:
    id: str
    title: str
    synopsis: str = ""
    world_id: str = ""
    chapters: list[StoryChapter] = field(default_factory=list)
    scenes: list[StoryScene] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)
    current_scene_index: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> Story:
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            synopsis=d.get("synopsis", ""),
            world_id=d.get("world_id", ""),
            chapters=[StoryChapter.from_dict(c) for c in d.get("chapters", [])],
            scenes=[StoryScene.from_dict(s) for s in d.get("scenes", [])],
            flags=dict(d.get("flags", {})),
            current_scene_index=int(d.get("current_scene_index", 0)),
        )

    @classmethod
    def from_scenario_json(cls, data: dict) -> Story:
        """既存シナリオJSONからStoryを構築する（context_builder経由で読んだデータを変換）。"""
        scenes = []
        for i, s in enumerate(data.get("scenes", [])):
            scenes.append(StoryScene(
                id=s.get("id", f"scene_{i}"),
                title=s.get("title", ""),
                description=s.get("description", ""),
                location_id=s.get("location_id", ""),
                required_flags=list(s.get("required_flags", [])),
            ))
        chapters = [StoryChapter.from_dict(c) for c in data.get("chapters", [])]
        raw_flags = data.get("flags", {})
        if isinstance(raw_flags, list):
            flags = {f["key"]: f["value"] for f in raw_flags if "key" in f}
        else:
            flags = dict(raw_flags)
        return cls(
            id=data.get("id", ""),
            title=data.get("title", ""),
            synopsis=data.get("synopsis", ""),
            world_id=data.get("world_id", ""),
            chapters=chapters,
            scenes=scenes,
            flags=flags,
            current_scene_index=0,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "synopsis": self.synopsis,
            "world_id": self.world_id,
            "chapters": [c.to_dict() for c in self.chapters],
            "scenes": [s.to_dict() for s in self.scenes],
            "flags": self.flags,
            "current_scene_index": self.current_scene_index,
        }

    def current_scene(self) -> StoryScene | None:
        if 0 <= self.current_scene_index < len(self.scenes):
            return self.scenes[self.current_scene_index]
        return None

    def current_chapter(self) -> StoryChapter | None:
        """現在のシーンが属するチャプターを返す。"""
        if not self.chapters or not self.scenes:
            return None
        current = self.current_scene()
        if not current:
            return None
        return next(
            (c for c in self.chapters if current.id in c.scene_ids),
            None,
        )

    def advance_scene(self) -> bool:
        """次のシーンへ進む。最後のシーンの場合は False を返す。"""
        if self.current_scene_index < len(self.scenes) - 1:
            self.current_scene_index += 1
            return True
        return False

    def advance_chapter(self) -> bool:
        """次のチャプターの最初のシーンへ進む。最後のチャプターの場合は False を返す。"""
        current_ch = self.current_chapter()
        if not current_ch or not self.chapters:
            return self.advance_scene()
        ch_idx = next((i for i, c in enumerate(self.chapters) if c.id == current_ch.id), -1)
        if ch_idx < 0 or ch_idx >= len(self.chapters) - 1:
            return False
        next_ch = self.chapters[ch_idx + 1]
        if not next_ch.scene_ids:
            return False
        scene_id = next_ch.scene_ids[0]
        new_idx = next((i for i, s in enumerate(self.scenes) if s.id == scene_id), -1)
        if new_idx < 0:
            return False
        self.current_scene_index = new_idx
        return True

    def set_flag(self, key: str, value: Any) -> None:
        self.flags[key] = value

    def get_flag(self, key: str, default: Any = None) -> Any:
        return self.flags.get(key, default)


# ── Campaign ──────────────────────────────────────────────────────

@dataclass
class Campaign:
    """複数シナリオにまたがるキャンペーン（将来用: Phase 4以降）。"""
    id: str
    title: str
    world_id: str = ""
    scenario_ids: list[str] = field(default_factory=list)
    current_scenario_index: int = 0
    completed_scenarios: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Campaign:
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            world_id=d.get("world_id", ""),
            scenario_ids=list(d.get("scenario_ids", [])),
            current_scenario_index=int(d.get("current_scenario_index", 0)),
            completed_scenarios=list(d.get("completed_scenarios", [])),
        )

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def current_scenario_id(self) -> str | None:
        if 0 <= self.current_scenario_index < len(self.scenario_ids):
            return self.scenario_ids[self.current_scenario_index]
        return None
