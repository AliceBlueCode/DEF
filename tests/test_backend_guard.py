"""外部のサービスへの送信の確かめ（マルチルールブック基盤 B-021・B-025）。

- 確かめの動き（手元・外部の見分け、manifest に従う、ホストに知らせる）。
- 呼び忘れの検出: セッションと GM のコードで、LLM・読み上げ・画像生成を直接呼ぶ関数は、
  すべて `_backend_guard` で確かめていること。呼ぶ側で確かめている関数は `GUARDED_BY_CALLER` に
  理由と呼んでよい関数を書き、その関数以外から呼ばれていないことも確かめる。
"""

import ast
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from def_kari.llm import backend_guard as bg
from def_kari.trpg import resources

ROOT = Path(__file__).resolve().parent.parent


# ── 確かめの動き ─────────────────────────────────────────────────

@pytest.mark.parametrize("kind,backend,local", [
    ("llm", "textgen_webui", True), ("llm", "ollama", True), ("llm", "openai", False),
    ("tts", "voicevox", True), ("tts", "kokoro", True), ("tts", "openai_tts", False),
    ("t2i", "comfyui", True), ("t2i", "civitai", False),
])
def test_builtin_local_backends(kind, backend, local):
    with patch("def_kari.compatible_backends_store.is_local_backend", return_value=False):
        assert bg.is_local(kind, backend) is local


def test_compatible_backend_needs_the_local_mark():
    with patch("def_kari.compatible_backends_store.is_local_backend", side_effect=lambda n: n == "my_lmstudio"):
        assert bg.is_local("llm", "my_lmstudio") is True
        assert bg.is_local("llm", "some_cloud") is False


@pytest.fixture
def books(monkeypatch, tmp_path):
    """外部への送信を許さないルールブック（closed）と、許すルールブック（open）。"""
    for name, allowed in (("closed", False), ("open", True)):
        repo = tmp_path / name
        (repo / "rulebooks").mkdir(parents=True)
        (repo / "manifest.json").write_text(json.dumps({"external_services_allowed": allowed}), encoding="utf-8")
        (repo / "rulebooks" / f"{name}_book.json").write_text(json.dumps({"label": name}), encoding="utf-8")
    monkeypatch.setenv("TRPG_RULEBOOK_REPO_PATHS", f"{tmp_path / 'closed'};{tmp_path / 'open'}")
    monkeypatch.setattr("def_kari.trpg.plugins.loaded_plugins", lambda: [])
    bg._notified.clear()
    yield
    bg._notified.clear()


def test_refusal_follows_the_manifest(books):
    closed = {"id": "s1", "trpg_rulebook": "closed_book"}
    assert "external service" in bg.refusal(closed, "llm", "openai")
    assert bg.refusal(closed, "llm", "textgen_webui") is None
    assert bg.refusal({"id": "s2", "trpg_rulebook": "open_book"}, "llm", "openai") is None
    assert bg.refusal({"id": "s3"}, "llm", "openai") is None  # TRPG の卓でない
    assert bg.refusal(closed, "tts", "") is None  # 送らない（読み上げが無効）


def test_check_raises_and_notifies_the_host_once(books):
    sess = {"id": "s_notify", "trpg_rulebook": "closed_book"}
    with patch("def_kari.gm.events.game_event_bus.emit") as emit:
        for _ in range(2):
            with pytest.raises(bg.ExternalServiceRefused):
                bg.check(sess, "llm", "openai")
        assert bg.allowed(sess, "t2i", "civitai") is False
    events = [(c.args[1], c.args[2]["kind"], c.args[2]["gm_only"]) for c in emit.call_args_list]
    assert events == [("EXTERNAL_SERVICE_REFUSED", "llm", True), ("EXTERNAL_SERVICE_REFUSED", "t2i", True)]


def test_gm_narration_is_refused_not_switched(books):
    """断ったら、別のバックエンドに黙って切り替えず、エラーを返す（B-021）。"""
    from def_kari.gm.gm_agent import GMAgent
    sess = {"id": "s_gm", "trpg_rulebook": "closed_book", "history": [], "name_map": {}}
    with patch("def_kari.gm.events.game_event_bus.emit"), \
            patch("def_kari.llm.backend.LLM_BACKENDS", {"openai": {"chat": lambda *a, **k: "SENT"}}), \
            patch("def_kari.gm.gm_agent.LLM_BACKENDS", {"openai": {"chat": lambda *a, **k: "SENT"}}):
        out = GMAgent().narrate(sess, backend_id="openai")
    assert out["text"] == "" and "external service" in out["error"]


def test_ai_turn_is_refused_before_the_llm(books):
    from def_kari.api.routes import session_turn_engine as te
    sess = {"id": "s_turn", "trpg_rulebook": "closed_book", "history": [], "round": 1, "counters": {}}
    with patch("def_kari.gm.events.game_event_bus.emit"), \
            patch.object(te._player_agent, "narrate", side_effect=AssertionError("must not be called")):
        early, *_ = te._generate_ai_turn_reply(sess, "c1", {}, "", [], "", "openai", "", [], [], {}, "", 0, False)
    assert "external service" in early["error"]


# ── 呼び忘れの検出 ────────────────────────────────────────────────

_SEND_MARKERS = ('["chat"]', '.get("chat")', "generate_structured_reply(", '["chat_with_tools"]',
                 "synthesize_and_save(", "_generate_t2i_image(")

# 呼ぶ側で確かめている関数: 関数名 → (呼んでよい関数, 理由)
GUARDED_BY_CALLER = {
    "_decide_check_pairs": ({"plan_judgments"}, "plan_judgments は gm_agent.narrate が確かめた後に呼ぶ"),
    "plan_judgments": ({"narrate"}, "gm_agent.narrate が確かめた後に呼ぶ"),
    "_plan_action": ({"narrate"}, "player_agent.narrate の中から呼ぶ"),
    "_ai_action_select": ({"_resolve_ai_action"}, "_resolve_ai_action が allowed() で確かめてから呼ぶ"),
    "_synthesize_turn_audio_sync": ({"_generate_turn_audio", "_synthesize_and_notify_audio"},
                                    "呼ぶ2つの関数が allowed() で確かめる"),
}
# player_agent.narrate（クラスの中の narrate）は _generate_ai_turn_reply が確かめた後に呼ぶ
GUARDED_BY_CALLER_METHODS = {("player_agent.py", "narrate"): "_generate_ai_turn_reply が確かめた後に呼ぶ"}


def _functions():
    files = sorted((ROOT / "def_kari" / "api" / "routes").glob("session*.py")) + sorted((ROOT / "def_kari" / "gm").glob("*.py"))
    for f in files:
        src = f.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f, node, ast.get_source_segment(src, node) or ""


def test_every_sender_checks_the_guard():
    missing = []
    for f, node, seg in _functions():
        body = seg.split("\n", 1)[1] if "\n" in seg else ""
        if not any(m in body for m in _SEND_MARKERS):
            continue
        if "_backend_guard." in seg or node.name in GUARDED_BY_CALLER or (f.name, node.name) in GUARDED_BY_CALLER_METHODS:
            continue
        missing.append(f"{f.relative_to(ROOT).as_posix()}:{node.lineno} {node.name}")
    assert not missing, ("外部に送りうるのに、外部への送信の確かめ（_backend_guard）を通していない関数がある。"
                         "送る直前に _backend_guard.check / allowed を呼ぶか、呼ぶ側で確かめているなら "
                         "GUARDED_BY_CALLER に理由を書くこと:\n  " + "\n  ".join(missing))


def test_guarded_by_caller_is_only_called_from_its_callers():
    stray = []
    for f, node, seg in _functions():
        for call in ast.walk(node):
            if isinstance(call, ast.Call):
                name = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
                if name in GUARDED_BY_CALLER and node.name not in GUARDED_BY_CALLER[name][0] and node.name != name:
                    stray.append(f"{f.name}:{call.lineno} {node.name} calls {name}")
    assert not stray, "呼ぶ側で確かめる前提の関数が、ほかの所から呼ばれている:\n  " + "\n  ".join(stray)


def test_player_agent_narrate_is_only_called_after_the_guard():
    callers = []
    for f, node, seg in _functions():
        if f.name == "player_agent.py":
            continue
        if "_player_agent.narrate(" in seg:
            callers.append(node.name)
    assert set(callers) == {"_generate_ai_turn_reply"}, callers
