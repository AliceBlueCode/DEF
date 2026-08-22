"""OpenAI互換アダプター(compatible.py)のjson_mode配線のテスト。

json_modeパラメータが受け取られるだけで本体で一切使われていなかった
(TGWアダプターで見つかったのと同型のデッドパラメータ、2026-08-22発覚・修正)。
"""

from unittest.mock import MagicMock, patch

from def_kari.llm.adapters.compatible import make_chat_fn


def _mock_response(content="ok"):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    return resp


def test_json_mode_true_adds_response_format():
    chat_fn, _ = make_chat_fn("https://example.com/v1", "key", "some-model")
    with patch("def_kari.llm.adapters.compatible.requests.post", return_value=_mock_response()) as mock_post:
        chat_fn([{"role": "user", "content": "hi"}], "", json_mode=True)
    body = mock_post.call_args.kwargs["json"]
    assert body["response_format"] == {"type": "json_object"}


def test_json_mode_false_omits_response_format():
    chat_fn, _ = make_chat_fn("https://example.com/v1", "key", "some-model")
    with patch("def_kari.llm.adapters.compatible.requests.post", return_value=_mock_response()) as mock_post:
        chat_fn([{"role": "user", "content": "hi"}], "", json_mode=False)
    body = mock_post.call_args.kwargs["json"]
    assert "response_format" not in body


def test_chat_returns_message_content():
    chat_fn, _ = make_chat_fn("https://example.com/v1", "key", "some-model")
    with patch("def_kari.llm.adapters.compatible.requests.post", return_value=_mock_response("hello world")):
        result = chat_fn([{"role": "user", "content": "hi"}], "", json_mode=False)
    assert result == "hello world"
