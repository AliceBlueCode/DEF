"""Phase 1 CLI検証: Streamlit無しでLLM応答・翻訳・タグ抽出が動作することを確認する。

使用方法:
  cd e:\tools\DEF
  python -m def_kari.test_phase1
"""

import sys


def test_events():
    from def_kari.core.events import make_event, EVENT_TTS_COMPLETE

    event = make_event(EVENT_TTS_COMPLETE, {"msg_id": "test-123", "audio_path": "test.wav"})
    assert event["type"] == EVENT_TTS_COMPLETE
    assert event["payload"]["msg_id"] == "test-123"
    assert "id" in event
    assert "timestamp" in event
    print("PASS: events")


def test_dispatcher():
    import queue
    from def_kari.core.events import make_event, EVENT_TTS_COMPLETE
    from def_kari.core.dispatcher import drain_events, apply_event

    q = queue.Queue()
    q.put(make_event(EVENT_TTS_COMPLETE, {"msg_id": "m1", "audio_path": "a.wav"}))
    q.put(make_event(EVENT_TTS_COMPLETE, {"msg_id": "m2", "audio_path": "b.wav"}))

    events = drain_events(q)
    assert len(events) == 2
    assert q.empty()

    history = [
        {"id": "m1", "state": "TTS Running", "audio_path": None},
        {"id": "m2", "state": "TTS Running", "audio_path": None},
    ]
    for e in events:
        apply_event(e, history)
    assert history[0]["audio_path"] == "a.wav"
    assert history[0]["state"] == "TTS Completed"
    assert history[1]["audio_path"] == "b.wav"
    print("PASS: dispatcher")


def test_model_registry():
    from def_kari.models.registry import load_model_master, get_prompt_language, get_model_type, get_quirks

    master = load_model_master()
    assert "501" in master
    assert get_prompt_language("501", master) == "ja"

    assert get_model_type("LightChatAssistant-TypeB-2x7B_q8.gguf") == "chat"
    assert get_model_type("unknown") == "chat"

    q = get_quirks("Berghof-NSFW-7B.i1-Q6_K.gguf")
    assert q["json_capable"] is False
    assert q["appends_meta_text"] is True

    q_default = get_quirks("unknown")
    assert q_default["json_capable"] is True
    print("PASS: model_registry")


def test_llm_schema():
    from def_kari.llm.schema import VALIDATOR, EMOTIONS

    valid = {"dialogue": "hello", "emotion": "happy", "image_prompt_en": "1girl", "tags": []}
    assert len(list(VALIDATOR.iter_errors(valid))) == 0

    invalid = {"dialogue": "hello"}
    assert len(list(VALIDATOR.iter_errors(invalid))) > 0
    print("PASS: llm_schema")


def test_llm_prompts():
    from def_kari.llm.prompts import build_system_prompt

    prompt = build_system_prompt("You are Luna.", "1girl, silver hair")
    assert "Luna" in prompt
    assert "silver hair" in prompt
    assert "JSON" in prompt
    print("PASS: llm_prompts")


def test_llm_backend_registry():
    from def_kari.llm.backend import LLM_BACKENDS, DEFAULT_LLM_BACKEND

    assert DEFAULT_LLM_BACKEND in LLM_BACKENDS
    assert len(LLM_BACKENDS) == 4
    for name, backend in LLM_BACKENDS.items():
        assert "chat" in backend, f"{name} missing chat"
        assert "list_models" in backend, f"{name} missing list_models"
    print("PASS: llm_backend_registry")


def test_translation():
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent / "translation"))
    from translation_factory import create_provider

    p = create_provider("library")
    assert p.provider_name == "library"
    result = p.translate("Hello", "en", "ja")
    assert isinstance(result, str) and len(result) > 0
    print(f"  library: 'Hello' -> '{result}'")
    print("PASS: translation")


def test_image_prompt():
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent / "image_prompt"))
    from tag_extractor import extract_flat_tags
    from prompt_generator import generate_prompt_from_text

    noise_tags = extract_flat_tags(
        "Of course I think tests are important. Let's make sure everything works."
    )
    assert len(noise_tags) == 0, f"Expected 0 noise tags, got: {noise_tags}"

    prompt = generate_prompt_from_text(
        "A sad girl with black hair sitting alone on a beach at sunset"
    )
    assert "1girl" in prompt
    assert "sad" in prompt
    assert "beach" in prompt
    print(f"  prompt: {prompt}")
    print("PASS: image_prompt")


def test_llm_client_offline():
    """フォールバックチェーンのオフラインテスト(LLM接続なし)。"""
    from def_kari.llm.client import _autofix, _try_parse_and_validate

    raw = '```json\n{"dialogue": "hello", "emotion": "happy", "image_prompt_en": "1girl", "tags": []}\n```'
    fixed = _autofix(raw)
    ok, parsed, errors = _try_parse_and_validate(fixed)
    assert ok
    assert parsed["dialogue"] == "hello"
    print("PASS: llm_client_offline")


if __name__ == "__main__":
    test_events()
    test_dispatcher()
    test_model_registry()
    test_llm_schema()
    test_llm_prompts()
    test_llm_backend_registry()
    test_translation()
    test_image_prompt()
    test_llm_client_offline()
    print("\nPhase 1 CLI tests: all passed.")
