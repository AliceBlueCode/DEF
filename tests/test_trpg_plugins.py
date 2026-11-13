"""ルールシステムのプラグインの読み込みと口（マルチルールブック基盤 B-002・B-006〜B-009、B-026・B-027）。

架空のルールシステムのプラグイン `tests/fixtures/plugins/sample_grid` を使う（B-008）。壊れた
プラグインは、それを一時フォルダに写して書き換えて作る。
"""

import json
import shutil
import sys
import time
from pathlib import Path

import pytest

from def_kari.api.routes import trpg as t
from def_kari.trpg import plugin_hooks, plugins, registry, resources

SAMPLE = Path(__file__).parent / "fixtures" / "plugins" / "sample_grid"


@pytest.fixture
def fresh_registry(monkeypatch):
    """レジストリとプラグインの状態を空にし、テストの後で元に戻す。"""
    saved = dict(registry._REGISTRY)
    saved_loaded = registry._BUILTIN_LOADED
    registry._REGISTRY.clear()
    registry._BUILTIN_LOADED = False
    plugins._reset_for_tests()
    monkeypatch.delenv("TRPG_PLUGIN_PATHS", raising=False)
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)
    registry._BUILTIN_LOADED = saved_loaded
    plugins._reset_for_tests()
    for name in [m for m in sys.modules if m.startswith("def_trpg_plugin_")]:
        sys.modules.pop(name, None)


def _copy_plugin(tmp_path, name="sample_grid", decl=None, init=None) -> Path:
    dst = tmp_path / name
    shutil.copytree(SAMPLE, dst)
    if decl is not None:
        d = json.loads((dst / "def_plugin.json").read_text(encoding="utf-8"))
        d.update(decl)
        (dst / "def_plugin.json").write_text(json.dumps(d), encoding="utf-8")
    if init is not None:
        (dst / "sample_grid_plugin" / "__init__.py").write_text(init, encoding="utf-8")
    return dst


def _use(monkeypatch, *paths):
    monkeypatch.setenv("TRPG_PLUGIN_PATHS", ";".join(str(p) for p in paths))
    registry.load_all()


def _reasons():
    return [e["reason"] for e in plugins.load_errors()]


# ── 読み込み ─────────────────────────────────────────────────────

def test_sample_plugin_is_loaded_and_registered(fresh_registry, monkeypatch):
    _use(monkeypatch, SAMPLE)
    assert registry.get("sample_grid") is not None
    assert registry.get("def_original") is not None
    assert [(p.plugin_id, p.plugin_version, p.rule_systems) for p in plugins.loaded_plugins()] == [
        ("sample_grid", "0.1.0", ["sample_grid"])]
    assert plugins.load_errors() == []


def test_judgment_switches_by_rule_system_through_plugin(fresh_registry, monkeypatch, tmp_path):
    """B-040 の2: ルールブックの `rule_system` だけで、判定の実装がプラグインのものに切り替わる。"""
    _use(monkeypatch, SAMPLE)
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "grid_book.json").write_text(json.dumps({"rule_system": "sample_grid"}), encoding="utf-8")
    monkeypatch.setattr(resources, "RULEBOOK_DIRS", [rules])
    monkeypatch.setattr("def_kari.trpg.rule_engine.secrets.randbelow", lambda n: 9)  # 出目 10
    out = t.compute_dice_judgment("1d20", 5, "grid_book")
    assert out["judgment"] == {"success": True, "roll": 10, "total": 15, "judgment_type": "sample_grid_d20"}


def test_code_is_not_loaded_from_the_rulebook_data_setting(fresh_registry, monkeypatch):
    """B-006: ルールブックのデータの設定からはコードを読まない。"""
    monkeypatch.setenv("TRPG_RULEBOOK_REPO_PATHS", str(SAMPLE))
    registry.load_all()
    assert registry.get("sample_grid") is None


def test_loaded_only_once(fresh_registry, monkeypatch):
    _use(monkeypatch, SAMPLE)
    registry.load_all()
    registry.get("sample_grid")
    assert len(plugins.loaded_plugins()) == 1


# ── 読み込まないもの（B-026・B-027） ─────────────────────────────────

@pytest.mark.parametrize("decl,reason_part", [
    ({"def_plugin_api": 2}, "def_plugin_api 2 is not supported"),
    ({"def_plugin_api": "1"}, "def_plugin_api must be an integer"),
    ({"plugin_id": "../x"}, "plugin_id is missing or invalid"),
    ({"plugin_version": ""}, "plugin_version is missing"),
    ({"package": "../sample_grid_plugin"}, "package is missing or invalid"),
    ({"package": "no_such_package"}, "not found"),
    ({"rule_systems": []}, "rule_systems must be a non-empty list"),
    ({"rule_systems": ["other_id"]}, "not in rule_systems"),
])
def test_broken_declaration_is_not_loaded(fresh_registry, monkeypatch, tmp_path, decl, reason_part):
    _use(monkeypatch, _copy_plugin(tmp_path, decl=decl))
    assert registry.get("sample_grid") is None
    assert registry.get("def_original") is not None
    assert any(reason_part in r for r in _reasons()), _reasons()


_CAPS_INIT = '''
class S:
    id = "sample_grid"
    capabilities = frozenset({{{caps}}})
    def validate_rulebook(self, d): return []
    def general_check(self, r, v, rb, **o): return {{}}
    def allowed_skills(self, rb): return frozenset()
    def dice_notation(self, rb): return "1d20"
    def build_rule_context(self, rb, sc, lang): return ""
def register(api):
    return S()
'''


@pytest.mark.parametrize("caps,reason_part", [
    ('"teleport"', "unknown capability: 'teleport'"),
    ('"visibility"', "capability 'visibility' requires 'image_prompt'"),
    ('"visibility", "prompt_context", "image_prompt"', None),
    ('"gm_driver", "persistence"', "capability 'gm_driver' requires 'turn_driver'"),
    ('"turn_driver"', "capability 'turn_driver' requires 'persistence'"),
])
def test_capability_rules(fresh_registry, monkeypatch, tmp_path, caps, reason_part):
    _use(monkeypatch, _copy_plugin(tmp_path, init=_CAPS_INIT.format(caps=caps)))
    if reason_part is None:
        assert registry.get("sample_grid") is not None
    else:
        assert registry.get("sample_grid") is None
        assert any(reason_part in r for r in _reasons()), _reasons()


def test_register_that_raises_does_not_stop_others(fresh_registry, monkeypatch, tmp_path):
    bad = _copy_plugin(tmp_path, name="bad", decl={"plugin_id": "bad_one"},
                       init="def register(api):\n    raise RuntimeError('boom')\n")
    _use(monkeypatch, bad, SAMPLE, tmp_path / "missing_folder")
    assert registry.get("sample_grid") is not None
    reasons = _reasons()
    assert any("RuntimeError: boom" in r for r in reasons)
    assert any("folder not found" in r for r in reasons)


def test_plugin_cannot_take_an_existing_id(fresh_registry, monkeypatch, tmp_path):
    init = _CAPS_INIT.format(caps="").replace('id = "sample_grid"', 'id = "def_original"')
    _use(monkeypatch, _copy_plugin(tmp_path, decl={"rule_systems": ["def_original"]}, init=init))
    assert type(registry.get("def_original")).__name__ == "DefOriginal"
    assert any("already registered" in r for r in _reasons())


# ── 口を呼ぶ入口（B-009・B-027） ──────────────────────────────────

class _Sys:
    id = "_hook_test"
    capabilities = frozenset({"memory_policy", "visibility", "prompt_context", "image_prompt"})

    def should_save_memory(self, session):
        raise RuntimeError("broken plugin")

    def history_view(self, session, audience):
        raise RuntimeError("broken plugin")

    def gm_context(self, session, lang):
        return "ctx"


def test_hook_without_capability_is_not_handled():
    sess = {}
    assert plugin_hooks.call(sess, "memory_policy", "should_save_memory", sess,
                             system=registry.get("def_original")) is plugin_hooks.NOT_HANDLED


def test_hook_failure_closes_and_pauses():
    from def_kari.api.routes.session_turn_engine import _pause_for_plugin_error
    sess = {"ai_paused": False}
    out = plugin_hooks.call(sess, "memory_policy", "should_save_memory", sess, system=_Sys(),
                            on_failure=_pause_for_plugin_error)
    assert out is False
    assert sess["ai_paused"] is True
    assert sess["plugin_error"]["method"] == "should_save_memory"


def test_hook_failure_without_callback_does_not_touch_the_session():
    sess = {"ai_paused": False}
    assert plugin_hooks.call(sess, "memory_policy", "should_save_memory", sess, system=_Sys()) is False
    assert sess == {"ai_paused": False}


def test_hook_failure_value_is_a_copy():
    a = plugin_hooks.call({}, "visibility", "history_view", {}, {}, system=_Sys())
    a.append("x")
    assert plugin_hooks.call({}, "visibility", "history_view", {}, {}, system=_Sys()) == []


def test_hook_success_passes_through():
    assert plugin_hooks.call({}, "prompt_context", "gm_context", {}, "ja", system=_Sys()) == "ctx"


def test_unknown_hook_method_is_refused():
    with pytest.raises(ValueError):
        plugin_hooks.call({}, "ui", "do_anything", system=_Sys())


# ── 保存したセッションのルールシステムが使えないとき（B-002） ─────────────

def test_saved_session_with_missing_rule_system_is_not_restored(monkeypatch, tmp_path):
    from def_kari.api.routes import session_persistence as sp
    from def_kari.api.routes.session_state import _sessions
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "needs_plugin.json").write_text(json.dumps({"rule_system": "_not_installed"}), encoding="utf-8")
    monkeypatch.setattr(resources, "RULEBOOK_DIRS", [rules])
    assert "_not_installed" in resources.rulebook_unavailable_reason("needs_plugin")
    assert resources.rulebook_unavailable_reason("missing_book") is None

    f = tmp_path / "autosave.json"
    f.write_text(json.dumps({"id": "_char_unavail", "trpg_rulebook": "needs_plugin", "history": []}),
                 encoding="utf-8")
    sp._restore_one_autosave_file(f, time.time())
    assert "_char_unavail" not in _sessions
    assert f.exists()  # 消さない（プラグインを入れ直せば次の起動で戻る）
