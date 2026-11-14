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


@pytest.fixture
def compat(monkeypatch, tmp_path):
    """互換バックエンドの定義を一時ファイルに置き換える。"""
    from def_kari import compatible_backends_store as store
    defs = tmp_path / "compatible_backends.json"
    monkeypatch.setattr(store, "_DEF_PATH", defs)
    monkeypatch.setattr(store, "_KEY_PATH", tmp_path / "compatible_backends.key.json")
    monkeypatch.setattr(store, "_DATA_DIR", tmp_path)

    def write(d):
        defs.write_text(json.dumps(d), encoding="utf-8")
    write({})
    return write


def test_compatible_backend_needs_the_local_mark(compat):
    compat({"my_lmstudio": {"base_url": "http://127.0.0.1:1234/v1", "local": True},
            "some_cloud": {"base_url": "https://example.invalid/v1"}})
    assert bg.is_local("llm", "my_lmstudio") is True
    assert bg.is_local("llm", "some_cloud") is False


def test_compatible_backend_with_a_builtin_name_is_not_trusted(compat):
    """C-002: 本体と同じ名前の互換バックエンドは、印が無ければ外部（実装レビュー2の🔴2）。登録もされない。"""
    from def_kari import compatible_backends_store as store
    compat({"ollama": {"base_url": "https://example.invalid/v1", "model": "m"},
            "fine": {"base_url": "http://127.0.0.1:1/v1", "model": "m", "local": True}})
    assert bg.is_local("llm", "ollama") is False
    names = [b["name"] for b in store.all_backends_with_keys()]
    assert "ollama" not in names and "fine" in names
    assert "voicevox" in store.reserved_names() and "a1111" in store.reserved_names()


def test_adding_a_compatible_backend_with_a_builtin_name_is_refused(compat):
    from def_kari.api.routes import settings as st
    req = st.CompatibleBackendRequest(name="textgen_webui", base_url="https://example.invalid/v1", model="m")
    assert "本体" in st.add_compatible_backend(req)["error"]


@pytest.mark.parametrize("url,local", [
    ("http://127.0.0.1:5000/v1", True), ("http://localhost:5000/v1", True), ("http://[::1]:5000/v1", True),
    ("http://192.168.1.20:5000/v1", False), ("https://tgw.example.invalid/v1", False),
])
def test_builtin_local_backend_must_point_to_this_machine(compat, monkeypatch, url, local):
    """C-002: 本体の手元のバックエンドも、向け先がこの機械のときだけ手元（実装レビュー2の🟡1）。"""
    monkeypatch.setenv("TEXTGEN_WEBUI_URL", url)
    assert bg.is_local("llm", "textgen_webui") is local


@pytest.mark.parametrize("model,local", [("llama3:8b", True), ("gpt-oss:120b-cloud", False), ("qwen3:cloud", False)])
def test_ollama_cloud_models_are_external(compat, monkeypatch, model, local):
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
    assert bg.is_local("llm", "ollama", model) is local


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


def test_unreadable_rulebook_closes_the_table(books):
    """C-002: 卓のルールブックが読めないなら、送ってよいと判断しない（実装レビュー2の🔴1）。"""
    gone = {"id": "s9", "trpg_rulebook": "vanished_book"}
    assert "cannot be checked" in bg.refusal(gone, "llm", "openai")
    assert bg.refusal(gone, "llm", "textgen_webui") is None  # 手元には送れる
    perms = resources.table_permissions("vanished_book")
    assert perms["missing"] and not perms["external_services_allowed"] and not perms["online_sessions"]
    assert resources.online_refusal("vanished_book")
    assert not resources.table_permissions("open_book", "no_such_scenario")["external_services_allowed"]


def test_closed_table_is_not_written_to_memory(books):
    """C-002: 外部への送信を許さない卓は、キャラの記憶に書かない（実装レビュー2の🟡2）。"""
    from def_kari.api.routes import session_persistence as sp
    def table(book):
        return {"trpg_rulebook": book, "initiative": ["a"], "name_map": {"a": "A"},
                "history": [{"role": "assistant", "character_id": "a", "content": "A: secret"}]}
    with patch("def_kari.gm.memory.save_episodic") as save:
        sp._save_session_episodic("s1", table("closed_book"))
    save.assert_not_called()
    with patch("def_kari.gm.memory.save_episodic") as save:  # 対照: 送信を許す卓は書く
        sp._save_session_episodic("s2", table("open_book"))
    save.assert_called_once()
    assert sp._table_keeps_content_inside({"trpg_rulebook": "closed_book"}) is True
    assert sp._table_keeps_content_inside({"trpg_rulebook": "open_book"}) is False
    assert sp._table_keeps_content_inside({}) is False


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

# 外部に送りうる呼び方の目印。バックエンドの表を引く書き方と、TTS・T2I の入口の関数（実装レビュー2の🟢で広げた）
_SEND_MARKERS = ('["chat"]', '.get("chat")', "generate_structured_reply(", '["chat_with_tools"]',
                 "synthesize_and_save(", "_generate_t2i_image(", "generate_image(", "synthesize(",
                 "TTS_BACKENDS[", "T2I_BACKENDS[", "LLM_BACKENDS[")

# 探す範囲の外にあり、卓の中身を送らないので確かめないもの: ファイル → 理由
NOT_SCANNED = {
    "def_kari/safety/character_audit.py": "キャラ定義の安全監査。卓（ルールブック・シナリオ）の中身を送らず、"
                                          "セッションの外で呼ばれる",
}

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


def test_not_scanned_files_exist_and_do_not_touch_tables():
    for rel in NOT_SCANNED:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "trpg_rulebook" not in src and "trpg_scenario" not in src, rel


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
