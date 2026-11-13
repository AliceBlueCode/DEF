"""ルールシステムのレジストリ（マルチルールブック基盤 B-001〜B-004）のテスト。

- `rule_system` の無いルールブックは def_original（B-001）。
- 判定はルールブックのルールシステムに任せる（B-003）。ここでは架空のルールシステムを登録し、
  `rule_system` だけで判定の実装が切り替わることを確かめる（B-040 の2 の芽）。
- 登録されていない `rule_system` のルールブックは、読まない・一覧に出さない・保存しない（B-002）。
"""

import json

import pytest

from def_kari.api.routes import trpg as t
from def_kari.trpg import registry, resources


class _FakeSystem:
    id = "_test_fake_system"
    capabilities: frozenset[str] = frozenset()

    def validate_rulebook(self, data):
        return [] if data.get("ok") else ["fake: not ok"]

    def general_check(self, roll_total, value, rulebook, **options):
        return {"fake": True, "roll": roll_total, "value": value, "options": options}

    def allowed_skills(self, rulebook):
        return frozenset({"fake_skill"})

    def dice_notation(self, rulebook):
        return "1d20"

    def build_rule_context(self, rulebook, scenario, lang):
        return "fake context"


@pytest.fixture
def fake_system():
    sys_ = _FakeSystem()
    registry.register(sys_)
    yield sys_
    registry._REGISTRY.pop(sys_.id, None)


@pytest.fixture
def dirs(monkeypatch, tmp_path):
    public = tmp_path / "public"
    private = tmp_path / "private"
    for base in (public, private):
        (base / "trpg_rules").mkdir(parents=True)
        (base / "trpg_scenarios").mkdir(parents=True)
    monkeypatch.setattr(resources, "RULEBOOK_DIRS", [public / "trpg_rules", private / "trpg_rules"])
    monkeypatch.setattr(resources, "PUBLIC_RULEBOOK_DIRS", [public / "trpg_rules"])
    return public / "trpg_rules"


def _write(d, name, data):
    (d / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("rb", [{}, {"rule_system": ""}, {"rule_system": None}, {"rule_system": 3}, "not a dict"])
def test_missing_rule_system_is_def_original(rb):
    assert registry.rule_system_of(rb) == "def_original"


def test_def_original_is_builtin():
    s = registry.get("def_original")
    assert s is not None and s.id == "def_original"
    assert s.capabilities == frozenset()
    assert "def_original" in registry.registered_ids()


def test_register_twice_is_refused(fake_system):
    with pytest.raises(ValueError):
        registry.register(_FakeSystem())


def test_judgment_follows_rule_system(dirs, fake_system, monkeypatch):
    _write(dirs, "fakebook", {"rule_system": fake_system.id, "ok": True})
    monkeypatch.setattr("def_kari.trpg.rule_engine.secrets.randbelow", lambda n: 6)  # 出目 7
    out = t.compute_dice_judgment("1d20", 12, "fakebook", is_stat=True)
    assert out["judgment"] == {"fake": True, "roll": 7, "value": 12,
                               "options": {"is_skill": False, "is_stat": True}}


def test_unknown_rule_system_is_not_loaded_or_listed(dirs):
    _write(dirs, "ghost", {"rule_system": "_not_registered"})
    _write(dirs, "plain", {"label": "plain"})
    assert resources.load_rulebook("ghost") == {}
    assert resources.load_rulebook("plain") == {"label": "plain"}
    assert [b["id"] for b in t.list_rulebooks()["rulebooks"]] == ["plain"]


def test_unknown_rule_system_is_not_saved(dirs):
    out = t.save_rulebook("ghost", t.SaveRulebookRequest(content=json.dumps({"rule_system": "_not_registered"})))
    assert out == {"error": "Validation failed", "details": ["unknown rule_system: '_not_registered'"]}
    assert not (dirs / "ghost.json").exists()


def test_validation_follows_rule_system(dirs, fake_system):
    bad = t.save_rulebook("fk", t.SaveRulebookRequest(content=json.dumps({"rule_system": fake_system.id})))
    assert bad == {"error": "Validation failed", "details": ["fake: not ok"]}
    good = t.save_rulebook("fk", t.SaveRulebookRequest(content=json.dumps({"rule_system": fake_system.id, "ok": True})))
    assert good == {"status": "ok", "id": "fk"}
