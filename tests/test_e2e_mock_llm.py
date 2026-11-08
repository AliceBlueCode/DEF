"""E2E用モックLLM（scripts/e2e_mock_llm.py）の台本の仕組みのテスト。

E2Eのシナリオは、この台本で「生成の失敗」「AIの投票の発議」等を再現する。台本の照合が
壊れると、E2Eは「期待した状況が作れずに通る／落ちる」ため、原因が分かりにくい。
ここで照合の規則そのものを固定しておく（2026-11-08）。
"""

from __future__ import annotations

import importlib.util
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "e2e_mock_llm.py"


@pytest.fixture()
def mock_server():
    spec = importlib.util.spec_from_file_location("e2e_mock_llm_under_test", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    server = ThreadingHTTPServer(("127.0.0.1", 0), mod._Handler)
    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _post(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(url: str):
    with urllib.request.urlopen(url, timeout=5) as res:
        return json.loads(res.read())


def _chat(base: str, text: str) -> tuple[int, dict]:
    return _post(f"{base}/v1/chat/completions", {"messages": [{"role": "user", "content": text}]})


def _content(body: dict) -> str:
    return body["choices"][0]["message"]["content"]


def test_default_response_is_schema_shaped_json(mock_server):
    status, body = _chat(mock_server, "こんにちは")
    assert status == 200
    parsed = json.loads(_content(body))
    assert parsed["dialogue"].startswith("モック応答")
    assert set(parsed) >= {"dialogue", "emotion", "tags"}


def test_rule_matches_on_all_contains_and_respects_not_contains(mock_server):
    _post(f"{mock_server}/_script", {"rules": [
        {"name": "alice", "contains": ["Alice", "行動"], "not_contains": ["弁明"], "json": {"action": "skip"}},
    ]})
    assert json.loads(_content(_chat(mock_server, "Alice の行動を選んで")[1])) == {"action": "skip"}
    # 片方しか含まない → 既定
    assert "dialogue" in json.loads(_content(_chat(mock_server, "Alice です")[1]))
    # not_contains に当たる → 既定
    assert "dialogue" in json.loads(_content(_chat(mock_server, "Alice の行動と弁明")[1]))


def test_rule_times_limit_then_falls_back(mock_server):
    _post(f"{mock_server}/_script", {"rules": [{"name": "once", "contains": ["X"], "content": "raw text", "times": 1}]})
    assert _content(_chat(mock_server, "X")[1]) == "raw text"
    assert "dialogue" in json.loads(_content(_chat(mock_server, "X")[1]))


def test_first_added_rule_wins(mock_server):
    _post(f"{mock_server}/_script", {"rules": [
        {"name": "first", "contains": ["X"], "content": "1"},
        {"name": "second", "contains": ["X"], "content": "2"},
    ]})
    assert _content(_chat(mock_server, "X")[1]) == "1"


def test_status_rule_returns_http_error(mock_server):
    _post(f"{mock_server}/_script", {"rules": [{"name": "boom", "contains": ["X"], "status": 500}]})
    status, body = _chat(mock_server, "X")
    assert status == 500
    assert "boom" in body["error"]["message"]


def test_calls_log_records_matched_rule_and_reset_clears(mock_server):
    _post(f"{mock_server}/_script", {"rules": [{"name": "hit", "contains": ["X"], "content": "x"}]})
    _chat(mock_server, "X")
    _chat(mock_server, "Y")
    calls = _get(f"{mock_server}/_calls")
    assert [c["matched"] for c in calls] == ["hit", ""]
    assert calls[1]["last_user"] == "Y"

    _post(f"{mock_server}/_reset", {})
    assert _get(f"{mock_server}/_calls") == []
    assert "dialogue" in json.loads(_content(_chat(mock_server, "X")[1]))


def _chat_msgs(base: str, messages: list[dict], **extra) -> tuple[int, dict]:
    return _post(f"{base}/v1/chat/completions", {"messages": messages, **extra})


def test_last_user_ignores_history_and_system_identifies_speaker(mock_server):
    """履歴に過去の指示が残っていても、いまの指示（最後の user）だけで照合すること。"""
    _post(f"{mock_server}/_script", {"rules": [{
        "name": "alice-delib",
        "last_user_contains": ["今、投票が提案されています:"],
        "system_contains": ["あなたの役割: Alice"],
        "json": {"dialogue": "反対です"},
    }]})
    history_has_marker = [
        {"role": "system", "content": "あなたの役割: Alice"},
        {"role": "user", "content": "今、投票が提案されています: 古い投票"},
        {"role": "assistant", "content": "…"},
        {"role": "user", "content": "次の発言をしてください"},
        {"role": "system", "content": "必ず以下のJSON形式のみで返答すること"},
    ]
    assert "dialogue" in json.loads(_content(_chat_msgs(mock_server, history_has_marker)[1]))
    assert "モック応答" in json.loads(_content(_chat_msgs(mock_server, history_has_marker)[1]))["dialogue"]

    now_deliberating = history_has_marker[:3] + [{"role": "user", "content": "今、投票が提案されています: X"}]
    assert json.loads(_content(_chat_msgs(mock_server, now_deliberating)[1])) == {"dialogue": "反対です"}
    other_speaker = [{"role": "system", "content": "あなたの役割: Bob"}] + now_deliberating[1:]
    assert "モック応答" in _content(_chat_msgs(mock_server, other_speaker)[1])


def test_json_mode_condition(mock_server):
    _post(f"{mock_server}/_script", {"rules": [{"name": "plain", "json_mode": False, "content": "賛成"}]})
    assert _content(_chat_msgs(mock_server, [{"role": "user", "content": "q"}])[1]) == "賛成"
    with_grammar = _chat_msgs(mock_server, [{"role": "user", "content": "q"}], grammar_string="root ::= x")[1]
    assert "dialogue" in json.loads(_content(with_grammar))
