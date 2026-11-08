"""F-14 フォールバックチェーン（generate_structured_reply）の構造検証テスト。

_autofix・_repair_types など個々の補正関数は test_unit.py / test_mvp_phase4.py が見ている。
ここでは LLM の生出力から最終結果までの「チェーン全体」を、基本設計書 5.4節の仕様から
検証する。LLM 呼び出し（_call_llm）だけを差し替え、出力の形（壊れたJSON・キー欠落・
型違い・思考過程の混入・空レスポンス等）ごとに、

  - どの段で成功するか（attempts の stage）
  - 結果が必ずスキーマ（4フィールド、emotion は EMOTIONS のいずれか）を満たすか
  - 思考過程やメタ情報が dialogue に漏れないか

を確かめる。期待値は現状の出力からではなく仕様から書いている。5.4節の記述が実装より
古い箇所（段3・段4の感情、思考だけの応答を失敗にすること）は、該当テストに根拠を書いた。
"""

import pytest
import requests

from def_kari.llm import client
from def_kari.llm.schema import EMOTIONS

STAGE_DIRECT = "LLMリクエスト"
STAGE_1 = "段1. 自動補正後の再パース"
STAGE_3 = "段3. プレーンテキスト形式からの抽出"
STAGE_4 = "段4. 生テキストをdialogueとして使用(最終安全網)"


def _run(monkeypatch, raw, **kwargs):
    """_call_llm が raw を返す（例外なら送出する）状態で generate_structured_reply を呼ぶ。"""

    def _fake_call_llm(*args, **kw):
        if isinstance(raw, BaseException):
            raise raw
        return raw

    monkeypatch.setattr(client, "_call_llm", _fake_call_llm)
    return client.generate_structured_reply("こんにちは", **kwargs)


def _assert_schema(result):
    """成功時の result は、どの段で得たものでもチャット用スキーマを満たすこと（5.4節）。"""
    assert set(result) == {"dialogue", "emotion", "image_prompt_en", "tags"}
    assert isinstance(result["dialogue"], str)
    emotions = result["emotion"] if isinstance(result["emotion"], list) else [result["emotion"]]
    assert 1 <= len(emotions) <= 2
    assert all(e in EMOTIONS for e in emotions)
    assert isinstance(result["image_prompt_en"], str)
    assert isinstance(result["tags"], list)
    assert all(isinstance(t, str) for t in result["tags"])


def _final_stage(out):
    return out["attempts"][-1]["stage"]


# ---------------------------------------------------------------------------
# 正常系・段1
# ---------------------------------------------------------------------------

class TestValidAndAutofix:
    def test_valid_json_succeeds_without_fallback(self, monkeypatch):
        raw = '{"dialogue": "やあ", "emotion": "happy", "image_prompt_en": "1girl, smile", "tags": []}'
        out = _run(monkeypatch, raw)
        assert out["success"] is True
        assert len(out["attempts"]) == 1
        assert out["attempts"][0]["stage"] == STAGE_DIRECT
        assert out["attempts"][0]["errors"] == []
        _assert_schema(out["result"])
        assert out["result"]["dialogue"] == "やあ"
        assert out["result"]["emotion"] == "happy"

    def test_code_fenced_json_recovers_at_stage1(self, monkeypatch):
        raw = '```json\n{"dialogue": "やあ", "emotion": "happy", "image_prompt_en": "", "tags": []}\n```'
        out = _run(monkeypatch, raw)
        assert out["success"] is True
        assert _final_stage(out) == STAGE_1
        assert out["result"]["dialogue"] == "やあ"

    def test_json_with_surrounding_prose_recovers(self, monkeypatch):
        raw = ('Sure! Here is the reply:\n'
               '{"dialogue": "やあ", "emotion": "happy", "image_prompt_en": "", "tags": []}\n'
               'Hope this helps.')
        out = _run(monkeypatch, raw)
        assert out["success"] is True
        _assert_schema(out["result"])
        assert out["result"]["dialogue"] == "やあ"
        assert out["result"]["emotion"] == "happy"


# ---------------------------------------------------------------------------
# キー欠落・型違い（_repair_types で補完して段0〜1で通る）
# ---------------------------------------------------------------------------

class TestMissingKeysAndWrongTypes:
    def test_missing_optional_fields_are_filled(self, monkeypatch):
        out = _run(monkeypatch, '{"dialogue": "やあ", "emotion": "happy"}')
        assert out["success"] is True
        _assert_schema(out["result"])
        assert out["result"]["tags"] == []
        assert out["result"]["image_prompt_en"] == ""

    def test_unknown_emotion_falls_back_to_neutral(self, monkeypatch):
        raw = '{"dialogue": "やあ", "emotion": "joyful", "image_prompt_en": "", "tags": []}'
        out = _run(monkeypatch, raw)
        _assert_schema(out["result"])
        assert out["result"]["emotion"] == "neutral"

    def test_emotion_list_is_capped_at_two_valid_entries(self, monkeypatch):
        raw = '{"dialogue": "やあ", "emotion": ["happy", "joyful", "excited", "sad"], "image_prompt_en": "", "tags": []}'
        out = _run(monkeypatch, raw)
        _assert_schema(out["result"])
        assert out["result"]["emotion"] == ["happy", "excited"]

    def test_wrong_types_are_coerced(self, monkeypatch):
        raw = '{"dialogue": 42, "emotion": "sad", "image_prompt_en": ["1girl", "rain"], "tags": "nsfw, violence"}'
        out = _run(monkeypatch, raw)
        assert out["success"] is True
        _assert_schema(out["result"])
        assert out["result"]["dialogue"] == "42"
        assert out["result"]["image_prompt_en"] == "1girl, rain"
        assert out["result"]["tags"] == ["nsfw", "violence"]

    def test_extra_key_does_not_leak_into_dialogue(self, monkeypatch):
        """スキーマ外のキー（内心の独白など）が付いても、セリフはdialogueの値だけになること。"""
        raw = ('{"dialogue": "やあ", "emotion": "happy", "image_prompt_en": "", "tags": [], '
               '"inner_thoughts": "本当は会いたくなかった"}')
        out = _run(monkeypatch, raw)
        assert out["success"] is True
        _assert_schema(out["result"])
        assert out["result"]["dialogue"] == "やあ"
        assert "本当は会いたくなかった" not in out["result"]["dialogue"]

    def test_misspelled_key_is_kept_while_extra_key_is_dropped(self, monkeypatch):
        """余計なキーを捨てるとき、表記揺れのキー（"Dialogues"・"emotions"）まで捨てないこと。"""
        raw = ('{"Dialogues": "やあ", "emotions": "happy", "image_prompt_en": "", "tags": [], '
               '"inner_thoughts": "本当は会いたくなかった"}')
        out = _run(monkeypatch, raw)
        assert out["success"] is True
        assert out["result"]["dialogue"] == "やあ"
        assert out["result"]["emotion"] == "happy"

    @pytest.mark.parametrize("raw", [
        '{"response": "こんにちは", "emotion": "happy", "image_prompt_en": "", "tags": []}',
        '{"セリフ": "こんにちは", "emotion": "happy"}',
        '{"character": {"dialogue": "こんにちは", "emotion": "happy"}}',
    ])
    def test_unknown_dialogue_key_does_not_succeed_with_empty_dialogue(self, monkeypatch, raw):
        """セリフのキー名が想定外のとき、本文を捨てて空のセリフで成功しないこと（レビュー指摘
        2026-11-08）。後段に回り、本文はどこかに残る。"""
        out = _run(monkeypatch, raw)
        assert out["attempts"][0]["errors"]  # 直接パースの段では成功しない
        if out["success"]:
            assert "こんにちは" in out["result"]["dialogue"]

    def test_missing_dialogue_without_extra_keys_keeps_image_prompt(self, monkeypatch):
        """dialogueが無いだけで余計なキーも無いJSONは、従来どおり直接パースの段で通し、
        image_prompt_en を失わないこと（レビュー指摘 2026-11-08）。"""
        raw = '{"emotion": "happy", "image_prompt_en": "1girl, smile", "tags": []}'
        out = _run(monkeypatch, raw)
        assert out["success"] is True
        assert _final_stage(out) == STAGE_DIRECT
        assert out["result"]["dialogue"] == ""
        assert out["result"]["image_prompt_en"] == "1girl, smile"

    def test_canonical_key_wins_over_misspelled_duplicate(self, monkeypatch):
        raw = '{"dialogue": "正しい方", "dialogues": "揺れた方", "emotion": "happy", "image_prompt_en": "", "tags": []}'
        out = _run(monkeypatch, raw)
        assert out["result"]["dialogue"] == "正しい方"


# ---------------------------------------------------------------------------
# 思考過程の混入
# ---------------------------------------------------------------------------

class TestThinking:
    def test_think_block_before_json_is_removed(self, monkeypatch):
        raw = ('<think>ユーザーは挨拶している。明るく返そう。</think>\n'
               '{"dialogue": "やあ", "emotion": "happy", "image_prompt_en": "", "tags": []}')
        out = _run(monkeypatch, raw)
        assert out["success"] is True
        assert out["result"]["dialogue"] == "やあ"

    def test_think_only_response_does_not_leak_reasoning(self, monkeypatch):
        """思考だけで途切れた応答（思考モデルのトークン切れ）で、思考過程がセリフとして出ないこと。"""
        raw = "<think>ユーザーは挨拶している。設定によると彼女は内気なので"
        out = _run(monkeypatch, raw)
        assert out["success"] is False
        assert out["result"] is None
        assert "トークン切れ" in out["attempts"][-1]["errors"][0]

    def test_closed_think_with_empty_body_fails(self, monkeypatch):
        out = _run(monkeypatch, "<think>何も言わないでおこう</think>\n")
        assert out["success"] is False
        reason = out["attempts"][-1]["errors"][0]
        assert "思考過程のみ" in reason and "トークン切れ" not in reason

    def test_orphan_close_tag_reasoning_is_removed(self, monkeypatch):
        """チャットテンプレートが<think>をプロンプト側に入れるモデル（Qwen3系・R1系）は
        「推論…</think>本文」と開きタグ無しで返す。推論がセリフに出ないこと。"""
        out = _run(monkeypatch, "ユーザーは挨拶している。明るく返そう。</think>\nやあ、元気？")
        assert out["success"] is True
        assert out["result"]["dialogue"] == "やあ、元気？"

    def test_close_tag_inside_dialogue_value_is_kept(self, monkeypatch):
        """JSONの値の中の</think>は推論の終わりではない（レビュー指摘 2026-11-08）。"""
        raw = '{"dialogue": "タグ</think>って何？", "emotion": "thoughtful", "image_prompt_en": "", "tags": []}'
        out = _run(monkeypatch, raw)
        assert out["success"] is True
        assert _final_stage(out) == STAGE_DIRECT
        assert out["result"]["dialogue"] == "タグ</think>って何？"

    def test_second_think_cut_off_is_reported_as_truncation(self, monkeypatch):
        out = _run(monkeypatch, "<think>a</think><think>bの途中で")
        assert out["success"] is False
        assert "トークン切れ" in out["attempts"][-1]["errors"][0]

    def test_orphan_close_tag_before_json(self, monkeypatch):
        raw = ('推論…</think>\n'
               '{"dialogue": "やあ", "emotion": "happy", "image_prompt_en": "", "tags": []}')
        out = _run(monkeypatch, raw)
        assert out["success"] is True
        assert out["result"]["dialogue"] == "やあ"

    def test_json_inside_unclosed_think_is_still_recovered(self, monkeypatch):
        """閉じていない<think>の中にJSONを書くモデルでも、JSONは拾えること。"""
        raw = '<think>{"dialogue": "やあ", "emotion": "happy", "image_prompt_en": "", "tags": []}'
        out = _run(monkeypatch, raw)
        assert out["success"] is True
        assert out["result"]["dialogue"] == "やあ"


# ---------------------------------------------------------------------------
# 段3・段4
# ---------------------------------------------------------------------------

class TestPlainTextFallbacks:
    # 5.4節は段3について「emotionは"neutral"を補完」と書くが、これは感情が書かれて
    # いない場合の補完と読む。書かれていて12種類のどれかなら、それを使う（実装どおり）。
    def test_plain_key_value_format_is_extracted_at_stage3(self, monkeypatch):
        raw = "dialogue: やあ、元気？\nemotion: happy\nimage_prompt_en: 1girl, smile\ntags: []"
        out = _run(monkeypatch, raw)
        assert out["success"] is True
        assert _final_stage(out) == STAGE_3
        _assert_schema(out["result"])
        assert out["result"]["dialogue"] == "やあ、元気？"
        assert out["result"]["emotion"] == "happy"
        assert out["result"]["image_prompt_en"] == "1girl, smile"

    def test_plain_format_with_unknown_emotion_still_satisfies_schema(self, monkeypatch):
        raw = "dialogue: やあ\nemotion: cheerful\nimage_prompt_en: 1girl"
        out = _run(monkeypatch, raw)
        assert out["success"] is True
        _assert_schema(out["result"])
        assert out["result"]["emotion"] == "neutral"

    def test_prose_reply_uses_stage4_safety_net(self, monkeypatch):
        out = _run(monkeypatch, "やあ、今日はいい天気だね。")
        assert out["success"] is True
        assert _final_stage(out) == STAGE_4
        _assert_schema(out["result"])
        assert out["result"]["dialogue"] == "やあ、今日はいい天気だね。"
        assert out["result"]["emotion"] == "neutral"
        assert out["result"]["tags"] == []

    # 5.4節は段4のemotionを"neutral"固定と書くが、同じ設計書の quirks 表
    # （emotion_in_text）は「テキストから感情を推定してemotionに反映」とする。後者が
    # 新しい仕様で、5.4節の記述が追いついていない（設計書の更新項目）。
    def test_stage4_estimates_emotion_when_quirk_is_set(self, monkeypatch):
        out = _run(monkeypatch, "やった！すごく嬉しい！", quirks={"emotion_in_text": True})
        assert _final_stage(out) == STAGE_4
        assert out["result"]["emotion"] == "happy"

    def test_every_attempt_is_logged_in_order(self, monkeypatch):
        out = _run(monkeypatch, "やあ、今日はいい天気だね。")
        stages = [a["stage"] for a in out["attempts"]]
        assert stages[0] == STAGE_DIRECT
        assert stages[-1] == STAGE_4
        # 直接 → 段1 → 段2 → 段3 → 段4。段を増減したら、この数と5.4節を一緒に直す
        assert len(stages) == 5
        assert all(a["errors"] for a in out["attempts"][:-1])


# ---------------------------------------------------------------------------
# 応答が無い・呼び出し失敗
# ---------------------------------------------------------------------------

class TestNoReply:
    def test_empty_response_fails_with_reason(self, monkeypatch):
        out = _run(monkeypatch, "")
        assert out["success"] is False
        assert out["result"] is None
        assert out["attempts"][0]["errors"]

    def test_whitespace_only_response_fails(self, monkeypatch):
        out = _run(monkeypatch, "   \n  ")
        assert out["success"] is False
        assert out["result"] is None
        assert "思考過程" not in out["attempts"][-1]["errors"][0]

    @pytest.mark.parametrize("exc", [
        requests.ConnectionError("refused"),
        requests.Timeout("timed out"),
        RuntimeError("backend error"),
    ])
    def test_request_failure_fails_with_reason(self, monkeypatch, exc):
        out = _run(monkeypatch, exc)
        assert out["success"] is False
        assert out["result"] is None
        assert type(exc).__name__ in out["attempts"][0]["errors"][0]
