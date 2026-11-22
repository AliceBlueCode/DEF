"""記憶に書くかを決める口（memory_policy。差し込み口 9、要求仕様 S-1001）。

手順6の5。架空のルールシステムのプラグインだけで確かめる（B-008）。口を持つ卓では、口が True と答えたときだけ
キャラの記憶に書く。確かめるのは `_save_session_episodic` の頭の1か所（終了・追放の決着の両方がここを通る）。
"""

import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from def_kari.api.routes import session_persistence as sp
from def_kari.trpg import plugins, registry

SAMPLE = Path(__file__).parent / "fixtures" / "plugins" / "sample_grid"

_INIT = '''
class S:
    id = "sample_grid"
    capabilities = frozenset({"memory_policy"})
    def validate_rulebook(self, d): return []
    def general_check(self, r, v, rb, **o): return {}
    def allowed_skills(self, rb): return frozenset()
    def dice_notation(self, rb): return "1d20"
    def build_rule_context(self, rb, sc, lang): return ""
    def should_save_memory(self, session):
        if session.get("_answer") == "boom":
            raise RuntimeError("broken plugin")
        return session.get("_answer")
def register(api):
    return S()
'''


@pytest.fixture
def plugin(monkeypatch, tmp_path):
    saved = dict(registry._REGISTRY)
    saved_loaded = registry._BUILTIN_LOADED
    registry._REGISTRY.clear()
    registry._BUILTIN_LOADED = False
    plugins._reset_for_tests()
    dst = tmp_path / "sample_grid"
    shutil.copytree(SAMPLE, dst)
    (dst / "sample_grid_plugin" / "__init__.py").write_text(_INIT, encoding="utf-8")
    monkeypatch.setenv("TRPG_PLUGIN_PATHS", str(dst))
    registry.load_all()
    assert registry.get("sample_grid") is not None
    # 外部への送信を許す卓として扱う（その守りは test_backend_guard.py が確かめる）
    monkeypatch.setattr(sp, "_table_keeps_content_inside", lambda s: False)
    yield
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)
    registry._BUILTIN_LOADED = saved_loaded
    plugins._reset_for_tests()
    for name in [m for m in sys.modules if m.startswith("def_trpg_plugin_")]:
        sys.modules.pop(name, None)


def _table(answer, rule_system="sample_grid"):
    return {"trpg_rulebook": "gb", "trpg_rule_system": rule_system,
            "trpg_plugin_version": "0.1.0" if rule_system == "sample_grid" else "", "_answer": answer,
            "initiative": ["a"], "name_map": {"a": "A"},
            "history": [{"role": "assistant", "character_id": "a", "content": "A: hello"}]}


@pytest.mark.parametrize("answer,saved", [(True, True), (False, False), (None, False), ("yes", False),
                                          (1, False), ("boom", False)])
def test_memory_is_written_only_when_the_rule_system_says_true(plugin, answer, saved):
    with patch("def_kari.gm.memory.save_episodic") as save:
        sp._save_session_episodic("s1", _table(answer))
    assert save.called is saved


def test_tables_without_the_hook_are_unchanged(plugin):
    with patch("def_kari.gm.memory.save_episodic") as save:
        sp._save_session_episodic("s2", _table(False, rule_system="def_original"))
    save.assert_called_once()


def test_unresolvable_pinned_system_does_not_write(plugin):
    table = _table(True)
    table["trpg_plugin_version"] = "9.9.9"
    with patch("def_kari.gm.memory.save_episodic") as save:
        sp._save_session_episodic("s3", table)
    save.assert_not_called()
