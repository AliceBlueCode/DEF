"""画像のプロンプトの元（image_prompt の口。差し込み口 7、要求仕様 S-704）と、外部への送信の役（B-021）。

手順6の5。架空のルールシステムのプラグインだけで確かめる（B-008）。
- 口を持つ卓の /generate-image は、口が渡す公開してよい語りだけを元にする（共有の履歴・場面・お題は使わない）。
- 口が失敗した・空なら、画像を作らない。
- 口を持つ卓では、手番の出力の image_prompt_en から自動で挿絵を作らない。
- DEF の中の外部への送信の確かめは、すべて呼び出しの役を渡す（役の無い呼び出しは、プラグインの卓で断られる）。
"""

import ast
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from def_kari.api.routes.session_state import _sessions
from def_kari.trpg import plugins, registry

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = Path(__file__).parent / "fixtures" / "plugins" / "sample_grid"

_INIT = '''
class S:
    id = "sample_grid"
    capabilities = frozenset({"visibility", "prompt_context", "image_prompt"})
    def validate_rulebook(self, d): return []
    def general_check(self, r, v, rb, **o): return {}
    def allowed_skills(self, rb): return frozenset()
    def dice_notation(self, rb): return "1d20"
    def build_rule_context(self, rb, sc, lang): return ""
    def session_view(self, s, a): return {}
    def event_view(self, s, e, a): return e
    def history_view(self, s, a): return []
    def gm_context(self, s, lang): return ""
    def player_context(self, s, c, lang): return ""
    def image_prompt_source(self, session):
        mode = session.get("_src")
        if mode == "boom":
            raise RuntimeError("broken plugin")
        if mode == "empty":
            return "  "
        if mode == "list":
            return ["x"]
        return "a ruined harbor at dusk"
def register(api):
    return S()
'''

SID = "_img_table"


@pytest.fixture
def table(monkeypatch, tmp_path):
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
    _sessions[SID] = {
        "id": SID, "trpg_mode": True, "trpg_rulebook": "gb", "trpg_rule_system": "sample_grid",
        "trpg_plugin_version": "0.1.0", "initiative": [], "name_map": {}, "actions_per_turn": 1,
        "topic": "SECRET TOPIC", "scene": "SECRET SCENE",
        "history": [{"role": "assistant", "character_id": "gm", "content": "gm: SECRET ENEMY PLAN",
                     "image_prompt_en": "secret enemy base"}],
    }
    yield _sessions[SID]
    _sessions.pop(SID, None)
    registry._REGISTRY.clear()
    registry._REGISTRY.update(saved)
    registry._BUILTIN_LOADED = saved_loaded
    plugins._reset_for_tests()
    for name in [m for m in sys.modules if m.startswith("def_trpg_plugin_")]:
        sys.modules.pop(name, None)


def _generate(mode):
    """/generate-image の中身を、T2I の手前まで流して、T2I に渡すはずのプロンプトを返す。"""
    from def_kari.api.routes import session_image as si
    req = si.SessionGenerateImageRequest(t2i_prompt_mode=mode, t2i_backend="")
    with patch("def_kari.settings.load_settings", return_value={}):
        out = si._generate_session_image_impl(SID, req)
    return out


def test_passthrough_uses_only_the_public_text(table):
    from def_kari.api.routes import t2i
    seen = {}
    with patch.object(t2i, "set_t2i_debug", side_effect=lambda d: seen.update(d)):
        out = _generate("passthrough")
    # T2I のバックエンドが無いので、生成の手前で止まる。プロンプトは口の語りだけ
    assert out == {"error": "T2Iバックエンドが未設定です"}
    from def_kari.api.routes import session_image as si
    with patch.object(si, "_apply_char_tags", side_effect=lambda p, c: seen.setdefault("prompt", p) or p):
        _generate("passthrough")
    assert seen["prompt"] == "a ruined harbor at dusk"


def test_llm_mode_sends_only_the_public_text(table):
    from def_kari.llm import backend as llm_backend
    sent = []

    def chat(messages, model, json_mode=False, options=None):
        sent.append("\n".join(m["content"] for m in messages))
        return "harbor, dusk"
    with patch.dict(llm_backend.LLM_BACKENDS, {"fake_llm": {"chat": chat, "list_models": lambda: []}}), \
            patch("def_kari.llm.backend_guard.check") as guard:
        from def_kari.api.routes import session_image as si
        req = si.SessionGenerateImageRequest(backend="fake_llm", t2i_prompt_mode="current")
        with patch("def_kari.settings.load_settings", return_value={}):
            si._generate_session_image_impl(SID, req)
    assert sent and "a ruined harbor at dusk" in sent[0]
    assert all(s not in sent[0] for s in ("SECRET", "secret enemy"))
    assert guard.call_args.kwargs["role"] == "image_prompt"


@pytest.mark.parametrize("mode,paused", [("boom", True), ("empty", False), ("list", False)])
def test_no_image_without_public_text(table, mode, paused):
    table["_src"] = mode
    out = _generate("passthrough")
    assert "no public text" in out["error"]
    assert bool(table.get("ai_paused")) is paused


def test_turn_images_are_not_made_from_turn_output(table):
    from def_kari.api.routes import session_turn_media as tm
    with patch.object(tm, "_generate_t2i_image") as gen, \
            patch.object(tm, "load_settings", return_value={"t2i_backend": "comfyui"}):
        tm._generate_turn_image(SID, {"image_prompt_en": "secret enemy base"})
    gen.assert_not_called()


def test_tables_without_the_hook_still_use_the_history(table):
    table["trpg_rule_system"] = "def_original"
    table["trpg_plugin_version"] = ""
    from def_kari.api.routes import session_image as si
    seen = {}
    with patch.object(si, "_apply_char_tags", side_effect=lambda p, c: seen.setdefault("prompt", p) or p):
        _generate("passthrough")
    assert seen["prompt"] == "secret enemy base"


# ── 外部への送信の役（B-021） ────────────────────────────────────

def _guard_calls():
    for f in sorted((ROOT / "def_kari").rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("check", "allowed", "refusal")
                    and isinstance(node.func.value, ast.Name) and node.func.value.id == "_backend_guard"):
                yield f, node


def test_every_guard_call_states_its_role():
    from def_kari.llm.backend_guard import ROLES
    calls = list(_guard_calls())
    assert len(calls) >= 10
    missing, unknown = [], []
    for f, node in calls:
        role = next((k.value for k in node.keywords if k.arg == "role"), None)
        where = f"{f.relative_to(ROOT).as_posix()}:{node.lineno}"
        if role is None:
            missing.append(where)
        elif not (isinstance(role, ast.Constant) and role.value in ROLES) and not isinstance(role, ast.Name):
            unknown.append(where)
    assert not missing, "外部への送信の確かめに役（role=）を渡していない: " + ", ".join(missing)
    assert not unknown, "知らない役: " + ", ".join(unknown)
