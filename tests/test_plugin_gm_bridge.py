"""GM をサーバー側から呼ぶ卓（gm_driver。差し込み口 2）と、束の組み立ての口（prompt_context。差し込み口 3）。

手順6の5。架空のルールシステムのプラグインだけで確かめる（B-008）。
- `PluginApi.llm_chat`: 自分のルールシステムの卓だけ、役が必要、外部への送信の確かめと vram_lock を通る。
- `PluginApi.emit`: 自分のルールシステムの卓だけ。
- `/ai_keeper`: gm_driver を持つ卓では GM を呼ばない（409）。
- `build_for_gm` / `build_for_player`: prompt_context を持つ卓では口が作った束。口が失敗したら RuleSystemError。
"""

import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from def_kari.api.routes.session_plugin_bridge import PluginCallError
from def_kari.api.routes.session_state import _sessions
from def_kari.trpg import plugins, registry
from def_kari.trpg.plugins import PluginApi

SAMPLE = Path(__file__).parent / "fixtures" / "plugins" / "sample_grid"

_INIT = '''
class S:
    id = "sample_grid"
    capabilities = frozenset({{{caps}}})
    def validate_rulebook(self, d): return []
    def general_check(self, r, v, rb, **o): return {{}}
    def allowed_skills(self, rb): return frozenset()
    def dice_notation(self, rb): return "1d20"
    def build_rule_context(self, rb, sc, lang): return ""
    def check_create(self, req): return ""
    def uses_def_autosave(self, s): return False
    def list_campaigns(self, rb): return []
    def session_view(self, s, a): return {{}}
    def event_view(self, s, e, a): return e
    def history_view(self, s, a): return []
    def gm_context(self, session, lang):
        if session.get("_break"):
            raise RuntimeError("broken plugin")
        return "GM bundle " + lang
    def player_context(self, session, char_id, lang):
        if session.get("_not_text"):
            return 42
        return "PC bundle " + char_id
    def image_prompt_source(self, s): return ""
def register(api):
    return S()
'''


def _load(monkeypatch, tmp_path, caps):
    dst = tmp_path / "sample_grid"
    shutil.copytree(SAMPLE, dst)
    (dst / "sample_grid_plugin" / "__init__.py").write_text(_INIT.format(caps=caps), encoding="utf-8")
    monkeypatch.setenv("TRPG_PLUGIN_PATHS", str(dst))
    registry.load_all()
    assert registry.get("sample_grid") is not None


@pytest.fixture
def clean_registry():
    saved = dict(registry._REGISTRY)
    saved_loaded = registry._BUILTIN_LOADED
    registry._REGISTRY.clear()
    registry._BUILTIN_LOADED = False
    plugins._reset_for_tests()
    sids = []
    yield sids
    for sid in sids:
        _sessions.pop(sid, None)
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)
    registry._BUILTIN_LOADED = saved_loaded
    plugins._reset_for_tests()
    for name in [m for m in sys.modules if m.startswith("def_trpg_plugin_")]:
        sys.modules.pop(name, None)


def _table(sids, sid, rule_system="sample_grid", **extra):
    _sessions[sid] = {"id": sid, "trpg_mode": True, "trpg_rulebook": "gb", "trpg_rule_system": rule_system,
                      "trpg_plugin_version": "0.1.0" if rule_system == "sample_grid" else "",
                      "backend": "fake_llm", "history": [], **extra}
    sids.append(sid)
    return _sessions[sid]


@pytest.fixture
def fake_backend(monkeypatch):
    from def_kari.llm import backend as llm_backend
    calls = []

    def chat(messages, model, json_mode=False, options=None):
        calls.append({"messages": messages, "json_mode": json_mode, "options": options})
        if messages and messages[-1]["content"] == "fail":
            raise RuntimeError("backend down")
        return "reply"
    monkeypatch.setitem(llm_backend.LLM_BACKENDS, "fake_llm", {"chat": chat, "list_models": lambda: []})
    return calls


def _api():
    return PluginApi("sample_grid", "0.1.0", 1, ["sample_grid"])


def _lock_is_free() -> bool:
    from def_kari.resources.vram_lock import get_vram_lock
    lock = get_vram_lock()
    if lock.acquire(timeout=0):
        lock.release()
        return True
    return False


_MSG = [{"role": "user", "content": "hi"}]


# ── llm_chat ─────────────────────────────────────────

def test_llm_chat_calls_the_table_backend_through_the_guard(clean_registry, fake_backend):
    _table(clean_registry, "_gm_t1")
    with patch("def_kari.llm.backend_guard.check") as guard:
        assert _api().llm_chat("_gm_t1", _MSG, role="gm", json_mode=True, options={"num_predict": 9}) == "reply"
    guard.assert_called_once()
    assert guard.call_args.kwargs["role"] == "gm" and guard.call_args.args[1:3] == ("llm", "fake_llm")
    assert fake_backend == [{"messages": _MSG, "json_mode": True, "options": {"num_predict": 9}}]
    assert _lock_is_free()


@pytest.mark.parametrize("role", [None, "", "narrator", "GM"])
def test_llm_chat_needs_a_known_role(clean_registry, fake_backend, role):
    _table(clean_registry, "_gm_t2")
    with pytest.raises(PluginCallError, match="role"):
        _api().llm_chat("_gm_t2", _MSG, role=role)
    assert fake_backend == []


def test_llm_chat_only_on_the_plugins_own_tables(clean_registry, fake_backend):
    _table(clean_registry, "_gm_other", rule_system="def_original")
    with pytest.raises(PluginCallError, match="does not belong"):
        _api().llm_chat("_gm_other", _MSG, role="gm")
    with pytest.raises(PluginCallError, match="not found"):
        _api().llm_chat("_gm_missing", _MSG, role="gm")
    assert fake_backend == []


def test_llm_chat_refused_by_the_guard_sends_nothing(clean_registry, fake_backend):
    from def_kari.llm import backend_guard
    _table(clean_registry, "_gm_t3")
    with patch.object(backend_guard, "check", side_effect=backend_guard.ExternalServiceRefused("closed table")):
        with pytest.raises(PluginCallError, match="closed table"):
            _api().llm_chat("_gm_t3", _MSG, role="gm")
    assert fake_backend == [] and _lock_is_free()


def test_llm_chat_failure_releases_the_lock(clean_registry, fake_backend):
    _table(clean_registry, "_gm_t4")
    with patch("def_kari.llm.backend_guard.check"):
        with pytest.raises(PluginCallError, match="backend down"):
            _api().llm_chat("_gm_t4", [{"role": "user", "content": "fail"}], role="gm")
    assert _lock_is_free()


def test_llm_chat_checks_messages(clean_registry, fake_backend):
    _table(clean_registry, "_gm_t5")
    for bad in ("text", [{"role": "user"}], [{"role": "user", "content": 3}]):
        with pytest.raises(PluginCallError, match="messages"):
            _api().llm_chat("_gm_t5", bad, role="gm")


# ── emit ─────────────────────────────────────────────

def test_emit_only_on_the_plugins_own_tables(clean_registry):
    from def_kari.gm.events import game_event_bus
    _table(clean_registry, "_gm_e1")
    _table(clean_registry, "_gm_e2", rule_system="def_original")
    _api().emit("_gm_e1", "GRID_NARRATION", {"text": "x"})
    assert game_event_bus.get_log("_gm_e1")[-1]["type"] == "GRID_NARRATION"
    with pytest.raises(PluginCallError):
        _api().emit("_gm_e2", "GRID_NARRATION", {"text": "x"})
    with pytest.raises(PluginCallError):
        _api().emit("_gm_e1", "", {})
    with pytest.raises(PluginCallError):
        _api().emit("_gm_e1", "X", "not a dict")


# ── /ai_keeper（差し込み口 2） ──────────────────────────────

def test_ai_keeper_is_not_used_on_tables_whose_gm_runs_on_the_server(clean_registry, monkeypatch, tmp_path):
    from def_kari.api.routes.session_gameplay import AIKeeperRequest, ai_keeper_narrate
    _load(monkeypatch, tmp_path, '"gm_driver", "turn_driver", "persistence"')
    _table(clean_registry, "_gm_k1")
    with patch("def_kari.api.routes.session_gameplay._gm_agent") as agent:
        with pytest.raises(HTTPException) as e:
            ai_keeper_narrate("_gm_k1", AIKeeperRequest(), {"role": "host"})
    assert e.value.status_code == 409
    agent.narrate.assert_not_called()


# ── 束（差し込み口 3） ────────────────────────────────────

def test_bundles_come_from_the_rule_system(clean_registry, monkeypatch, tmp_path):
    from def_kari.gm.context_builder import build_for_gm, build_for_player
    _load(monkeypatch, tmp_path, '"visibility", "prompt_context", "image_prompt"')
    sess = _table(clean_registry, "_gm_c1", scenes=[{"gm_notes": "hidden"}])
    assert build_for_gm({"rule_system": "sample_grid"}, None, sess, "ja") == "GM bundle ja"
    assert build_for_player("char_a", {}, {"rule_system": "sample_grid"}, None, sess, "en") == "PC bundle char_a"


def test_a_failing_bundle_stops_instead_of_falling_back(clean_registry, monkeypatch, tmp_path):
    from def_kari.gm.context_builder import build_for_gm, build_for_player
    _load(monkeypatch, tmp_path, '"visibility", "prompt_context", "image_prompt"')
    sess = _table(clean_registry, "_gm_c2", _break=True, _not_text=True)
    with pytest.raises(registry.RuleSystemError):
        build_for_gm({"rule_system": "sample_grid"}, None, sess, "ja")
    with pytest.raises(registry.RuleSystemError):
        build_for_player("char_a", {}, {"rule_system": "sample_grid"}, None, sess, "ja")


def test_llm_chat_gives_up_when_the_vram_lock_is_busy(clean_registry, fake_backend, monkeypatch):
    """🟡5 の6: 錠が取れなければ呼ばずに断る。"""
    from def_kari.api.routes import session_plugin_bridge as bridge

    class _Busy:
        def acquire(self, timeout=None):
            return False

        def release(self):
            raise AssertionError("must not release a lock it did not get")
    monkeypatch.setattr("def_kari.resources.vram_lock.get_vram_lock", lambda: _Busy())
    monkeypatch.setattr(bridge, "_VRAM_LOCK_TIMEOUT_SECONDS", 0.01)
    _table(clean_registry, "_gm_busy")
    with patch("def_kari.llm.backend_guard.check"):
        with pytest.raises(PluginCallError, match="vram_lock busy"):
            _api().llm_chat("_gm_busy", _MSG, role="gm")
    assert fake_backend == []


# ── 卓の情報（手番を自分で回す卓が、どの続きものの卓か・止まっているかを引く） ──

def test_table_info_only_on_the_plugins_own_tables(clean_registry):
    s = _table(clean_registry, "_gm_t1", campaign_id="c-1")
    _table(clean_registry, "_gm_t2", rule_system="def_original", campaign_id="c-2")
    info = _api().table_info("_gm_t1")
    assert info == {"session_id": "_gm_t1", "campaign_id": "c-1", "rulebook_id": "gb", "rule_system": "sample_grid",
                    "plugin_version": "0.1.0", "paused": False, "plugin_error": False}
    s["ai_paused"] = True
    s["plugin_error"] = {"capability": "turn_driver"}
    assert _api().table_info("_gm_t1")["paused"] is True and _api().table_info("_gm_t1")["plugin_error"] is True
    info["campaign_id"] = "changed"   # 写しなので卓は変わらない
    assert s["campaign_id"] == "c-1"
    with pytest.raises(PluginCallError):
        _api().table_info("_gm_t2")
    with pytest.raises(PluginCallError):
        _api().table_info("_gm_none")


def test_llm_chat_uses_the_loaded_model_profile_under_the_plugins_options(clean_registry, monkeypatch):
    """DEF の GM と同じく、モデルのプロファイル（会話の型・温度）を土台にし、プラグインの値で上書きする。"""
    from def_kari.llm import backend as llm_backend
    from def_kari.llm import tgw_manager
    from def_kari.models import registry as model_registry
    calls = []
    monkeypatch.setitem(llm_backend.LLM_BACKENDS, "textgen_webui",
                        {"chat": lambda m, model, json_mode=False, options=None: calls.append(options) or "ok",
                         "list_models": lambda: []})
    monkeypatch.setattr(tgw_manager, "get_loaded_model_name", lambda: "some-model.gguf")
    monkeypatch.setattr(model_registry, "get_llm_profile", lambda name: {
        "generation_params": {"temperature": 0.4, "instruction_template": "Mistral"}} if name == "some-model.gguf" else {})
    _table(clean_registry, "_gm_p1", backend="textgen_webui")
    with patch("def_kari.llm.backend_guard.check"):
        _api().llm_chat("_gm_p1", _MSG, role="gm", options={"num_predict": 1500, "temperature": 0.2})
    assert calls == [{"temperature": 0.2, "instruction_template": "Mistral", "num_predict": 1500}]
    monkeypatch.setattr(tgw_manager, "get_loaded_model_name", lambda: None)
    with patch("def_kari.llm.backend_guard.check"):
        _api().llm_chat("_gm_p1", _MSG, role="gm")
    assert calls[-1] == {}
