"""turn/round状態を書き換える関数群のキャラクタライゼーションテスト。

`session_turn_engine.py`の`_advance_turn`・`_emit_waiting_for_human`・
`_resolve_turn_start`・`_finalize_ai_turn`・`retake_turn`・`skip_turn`・
`human_turn_action`は、いずれも`session["turn"]`/`session["round"]`/
`session["_round_seq"]`/`session["_round_spoken"]`/`session["action_count"]`/
`session["_skip_gen"]`のいずれかを書き換える。過去に3回連続でこの領域から
バグが出た（`_round_seq`の非同期遅延更新レース・GM強制スキップの`_round_seq`
更新漏れ・`vram_lock`の二重チェックロッキング崩れ）ため、書き込み窓口を
`_normalize_round_turn`へ集約する前に、現状の（未変更の）挙動をこのファイルで
先にpinする。集約後、このファイルの各アサーションは「意図した挙動修正」か
「事故的なリグレッション」かを個別に判定してから更新する
（意図した修正の場合はコメントで理由を残す）。

2026-09-18、ユーザーからの明示承認を得て着手。詳細な設計はPlanファイル
（`tender-puzzling-frog.md`）参照。
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from def_kari.api.main import app
from def_kari.api.routes.session import _sessions, issue_player_jwt
from def_kari.api.routes.session_turn_engine import (
    _advance_turn,
    _apply_skip,
    _emit_waiting_for_human,
    _finalize_ai_turn,
    _mark_spoken_and_check_round_complete,
    _resolve_turn_start,
    SessionNextRequest,
)

client = TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _base_session(sid: str, initiative: list[str], turn: int = 0, round_: int = 1) -> dict:
    """test_disconnect_timeout.py::_base_sessionと同型の最小セッション辞書。"""
    return {
        "id": sid,
        "initiative": initiative,
        "human_char_ids": [],
        "guest_chars": {},
        "players": {},
        "ws_connections": {},
        "name_map": {c: c for c in initiative},
        "counters": {},
        "history": [],
        "turn": turn,
        "round": round_,
        "action_count": 0,
        "actions_per_turn": 2,
        "ai_task": None,
        "trpg_mode": False,
    }


def _start_session_with_three_humans():
    """test_round_completion.pyと同型のヘルパー（retake_turn等のHTTP経路用）。"""
    resp = client.post("/api/session/start", json={"character_ids": []})
    d = resp.json()
    sid = d["session_id"]
    host_token = d["host_token"]
    sess = _sessions[sid]
    sess["initiative"] = ["char_a", "char_b", "char_c"]
    sess["turn"] = 0
    sess["human_char_ids"] = ["char_a", "char_b", "char_c"]
    sess["name_map"]["char_a"] = "Alice"
    sess["name_map"]["char_b"] = "Bob"
    sess["name_map"]["char_c"] = "Carol"
    sess["counters"] = {"char_a": 5, "char_b": 5, "char_c": 5}
    tokens = {}
    for cid in ("char_a", "char_b", "char_c"):
        tok = issue_player_jwt(sid, "player", cid)
        sess["players"][tok] = cid
        tokens[cid] = tok
    return sid, host_token, tokens


# ── 1a. 既に_advance_turnへ集約済みの経路（回帰確認用） ──────────────────

def test_advance_turn_forward_within_round():
    session = _base_session("_t1", ["a", "b", "c"], turn=0)
    _advance_turn(session, 1)
    assert session["turn"] == 1
    assert session["round"] == 1


def test_advance_turn_wraps_round_and_resets_turn_modulo():
    session = _base_session("_t2", ["a", "b", "c"], turn=2)
    _advance_turn(session, 3)
    assert session["turn"] == 0
    assert session["round"] == 2


def test_advance_turn_wraps_multiple_rounds_if_new_turn_far_past_boundary():
    """_advance_turnはmoduloベースなので、1ラウンド分を超えた飛び越しも1回で吸収する。"""
    session = _base_session("_t3", ["a", "b", "c"], turn=0)
    _advance_turn(session, 7)
    assert session["turn"] == 7 % 3
    assert session["round"] == 1 + 1  # round += 1は無条件で1回のみ


@pytest.mark.asyncio
async def test_apply_skip_advances_turn_marks_spoken_and_round_seq():
    """_apply_skipはasyncio.create_taskを無条件に呼ぶため、実行中のイベントループが
    要る（test_disconnect_timeout.pyの既存パターンに合わせ@pytest.mark.asyncioにする）。"""
    sid = "_t4"
    _sessions[sid] = _base_session(sid, ["char_a", "char_b"], turn=0)
    try:
        with patch("def_kari.api.routes.session_turn_engine._run_ai_turns"):
            session = _sessions[sid]
            result = _apply_skip(sid, session, "char_a")
        assert result["action"] == "skip"
        assert session["turn"] == 1
        assert session["_round_spoken"] == ["char_a"]
        assert session.get("_round_seq", 0) == 0  # まだ全員発言していない
        assert result["round_completed"] is False
    finally:
        _sessions.pop(sid, None)


def test_keeper_skip_endpoint_advances_round_seq_and_resets_spoken():
    sid, host_token, tokens = _start_session_with_three_humans()
    try:
        sess = _sessions[sid]
        assert sess.get("_round_seq", 0) == 0
        for _ in range(3):
            resp = client.post(f"/api/session/{sid}/skip", headers=_auth(host_token))
            assert resp.status_code == 200
            sess["ai_task"] = None
        assert sess.get("_round_seq", 0) == 1
        assert sess.get("_round_spoken", ["stale"]) == []
    finally:
        _sessions.pop(sid, None)


def test_human_turn_send_advances_turn_synchronously():
    """human_turn_action(send)がバックグラウンドタスク任せにせず、同一リクエスト内で
    session["turn"]/["round"]を正規化することを直接確認する（既存テストはレスポンス
    JSONのみ検証しており、session辞書そのものは見ていなかったため新設）。"""
    sid, host_token, tokens = _start_session_with_three_humans()
    try:
        sess = _sessions[sid]
        resp = client.post(
            f"/api/session/{sid}/human_turn",
            json={"action": "send", "text": "hi", "expected_round_seq": 0},
            headers=_auth(tokens["char_a"]),
        )
        assert resp.status_code == 200
        assert sess["turn"] == 1
        assert sess["round"] == 1
    finally:
        _sessions.pop(sid, None)


# ── 1b. _emit_waiting_for_human ──────────────────────────────────────────

def test_emit_waiting_for_human_normalizes_out_of_range_turn():
    sid = "_t5"
    session = _base_session(sid, ["a", "b"], turn=2)  # == len(initiative)、境界超過
    session["human_char_ids"] = ["a", "b"]
    _sessions[sid] = session
    try:
        result = _emit_waiting_for_human(sid, session)
        assert result is True
        assert session["round"] == 2
        assert session["turn"] == 0
    finally:
        _sessions.pop(sid, None)


def test_emit_waiting_for_human_normalizes_turn_more_than_one_over_boundary():
    """turnがinitiative長を1より多く超えている場合、moduloで正しく折り返す
    （このケースは実際には起こらない前提だが、正規化ロジックの頑健性として確認）。"""
    sid = "_t5b"
    session = _base_session(sid, ["a", "b"], turn=5)  # 5 % 2 == 1
    session["human_char_ids"] = ["a", "b"]
    _sessions[sid] = session
    try:
        _emit_waiting_for_human(sid, session)
        assert session["turn"] == 1
        assert session["round"] == 2  # round += 1は無条件で1回のみ（何周分かは見ない）
    finally:
        _sessions.pop(sid, None)


def test_emit_waiting_for_human_no_op_for_ai_current_speaker():
    sid = "_t6"
    session = _base_session(sid, ["a", "b"], turn=0)
    session["human_char_ids"] = []  # "a"はAI扱い
    _sessions[sid] = session
    try:
        result = _emit_waiting_for_human(sid, session)
        assert result is False
        assert session["turn"] == 0
        assert session["round"] == 1
    finally:
        _sessions.pop(sid, None)


def test_emit_waiting_for_human_in_range_turn_untouched():
    sid = "_t7"
    session = _base_session(sid, ["a", "b", "c"], turn=1)
    session["human_char_ids"] = ["a", "b", "c"]
    _sessions[sid] = session
    try:
        _emit_waiting_for_human(sid, session)
        assert session["turn"] == 1
        assert session["round"] == 1
    finally:
        _sessions.pop(sid, None)


# ── 1c. _resolve_turn_start ───────────────────────────────────────────────

def test_resolve_turn_start_normal_forward_no_boundary():
    session = _base_session("_t8", ["a", "b"], turn=0)
    session["human_char_ids"] = ["a", "b"]
    req = SessionNextRequest(session_id="_t8")
    early, ctx = _resolve_turn_start(session, req)
    assert early is not None and early.get("waiting_for_human") is True
    assert session["turn"] == 0
    assert session["round"] == 1


def test_resolve_turn_start_round_wraparound_hard_reset_to_zero():
    session = _base_session("_t9", ["a", "b"], turn=2)  # == len(initiative)
    session["human_char_ids"] = ["a", "b"]
    req = SessionNextRequest(session_id="_t9")
    _resolve_turn_start(session, req)
    assert session["round"] == 2
    assert session["turn"] == 0


def test_resolve_turn_start_designate_jump_within_current_round():
    session = _base_session("_t10", ["a", "b", "c"], turn=0)
    session["human_char_ids"] = ["a", "b", "c"]
    session["designated_next"] = "c"
    req = SessionNextRequest(session_id="_t10")
    _resolve_turn_start(session, req)
    assert session["turn"] == 2  # initiative.index("c")
    assert session["action_count"] == 0
    assert session["round"] == 1  # 指名だけではラウンドは進まない
    assert "designated_next" not in session


def test_resolve_turn_start_designate_return_turn_is_stashed_as_underscore_prefixed():
    session = _base_session("_t11", ["a", "b", "c"], turn=0)
    session["human_char_ids"] = ["a", "b", "c"]
    session["designated_next"] = "c"
    session["designated_return_turn"] = 1
    req = SessionNextRequest(session_id="_t11")
    _resolve_turn_start(session, req)
    assert session["_designated_return_turn"] == 1
    assert "designated_return_turn" not in session


def test_resolve_turn_start_designate_target_not_in_initiative_ignored():
    session = _base_session("_t12", ["a", "b"], turn=0)
    session["human_char_ids"] = ["a", "b"]
    session["designated_next"] = "not_in_initiative"
    req = SessionNextRequest(session_id="_t12")
    _resolve_turn_start(session, req)
    assert session["turn"] == 0  # 通常のturn解決にフォールバック
    assert "designated_next" not in session  # 無効でも消費される


def test_resolve_turn_start_designate_after_round_wraparound_interaction():
    """境界超過とdesignateが同時発生した場合、正規化が先・指名が後で、指名が最終的に勝つ。"""
    session = _base_session("_t13", ["a", "b", "c"], turn=3)  # == len(initiative)
    session["human_char_ids"] = ["a", "b", "c"]
    session["designated_next"] = "b"
    req = SessionNextRequest(session_id="_t13")
    _resolve_turn_start(session, req)
    assert session["round"] == 2  # 巻き戻りは発生する
    assert session["turn"] == 1  # だが最終的にはdesignateの"b"（新ラウンド内のindex）


def test_resolve_turn_start_negative_counter_forces_skip_unnormalized():
    session = _base_session("_t14", ["a", "b"], turn=1)  # turn+1 == len(initiative)
    session["human_char_ids"] = []
    session["counters"]["b"] = -1
    req = SessionNextRequest(session_id="_t14")
    early, ctx = _resolve_turn_start(session, req)
    assert early is not None and early.get("skipped") is True
    assert session["counters"]["b"] == 0
    assert session["turn"] == 2  # 生の値のまま、正規化されない
    assert session["round"] == 1  # 正規化されていないのでroundも据え置き
    assert session["action_count"] == 0
    # 2回目の呼び出しで初めて正規化される
    req2 = SessionNextRequest(session_id="_t14")
    _resolve_turn_start(session, req2)
    assert session["turn"] == 0
    assert session["round"] == 2


def test_resolve_turn_start_waiting_for_human_no_llm_call():
    session = _base_session("_t15", ["a"], turn=0)
    session["human_char_ids"] = ["a"]
    req = SessionNextRequest(session_id="_t15")
    early, ctx = _resolve_turn_start(session, req)
    assert early == {
        "waiting_for_human": True,
        "character_id": "a",
        "character_name": "a",
        "round": 1,
        "counters": {},
    }
    assert ctx is None


# ── 1d. _finalize_ai_turn ─────────────────────────────────────────────────

def _finalize(session, current_char_id, turn, text="reply", skip_gen_before=0, ai_action=None):
    req = SessionNextRequest(session_id=session["id"])
    return _finalize_ai_turn(
        session, req, current_char_id, session["name_map"], session["counters"],
        session["initiative"], turn, text, "neutral", [], "",
        "mock", skip_gen_before, ai_action or {"action": "none"}, "",
    )


def test_finalize_ai_turn_partial_turn_increments_action_count_no_turn_advance():
    session = _base_session("_t16", ["a", "b"], turn=0)
    session["actions_per_turn"] = 2
    result = _finalize(session, "a", 0, text="partial reply one")
    assert session["action_count"] == 1
    assert session["turn"] == 0  # ターンはまだ進んでいない
    assert result["round_completed"] is False
    # action_countの閾値到達前でも、発言済み記録は無条件で入る
    assert session["_round_spoken"] == ["a"]


def test_finalize_ai_turn_completed_turn_normalizes_synchronously():
    """2026-09-19、_normalize_round_turnをskip_genガード内に追加する集約により意図的に
    挙動が変わった1件。以前はturnがinitiative長と同値のままround未加算の状態が
    次のAIターン評価か_emit_waiting_for_humanが走るまで残っていた
    （このテストは元々`..._unnormalized`という名前でその状態をpinしていた）。
    人間側の経路で_advance_turnが閉じたのと同じ種類の「即座に正規化されない
    ウィンドウ」をAI側でも閉じたため、正規化後の値に更新する。"""
    session = _base_session("_t17", ["a", "b"], turn=1)  # 最後のキャラ
    session["actions_per_turn"] = 1  # 1アクションで即ターン完了
    _finalize(session, "b", 1, text="final reply")
    assert session["turn"] == 0  # 正規化済み
    assert session["round"] == 2  # 正規化済み


def test_finalize_ai_turn_designated_return_turn_takes_priority_over_turn_plus_one():
    session = _base_session("_t18", ["a", "b", "c"], turn=0)
    session["actions_per_turn"] = 1
    session["_designated_return_turn"] = 5  # 5 % 3 == 2
    _finalize(session, "a", 0, text="reply")
    assert session["turn"] == 2
    assert "_designated_return_turn" not in session


def test_finalize_ai_turn_skip_gen_race_guard_blocks_turn_write():
    session = _base_session("_t19", ["a", "b"], turn=0)
    session["actions_per_turn"] = 1
    session["_skip_gen"] = 1  # keeper_skipが競合発生（呼び出し時のsnapshotは0のまま渡す）
    _finalize(session, "a", 0, text="reply", skip_gen_before=0)
    assert session["turn"] == 0  # 上書きされない（元の値のまま）
    assert session["action_count"] == 0  # action_countのリセットはガード外なので実行される


def test_finalize_ai_turn_round_completed_flag_reflects_live_state():
    session = _base_session("_t20", ["a", "b"], turn=1)
    session["actions_per_turn"] = 1
    session["_round_spoken"] = ["a"]  # "a"は既に発言済み、"b"が最後
    result = _finalize(session, "b", 1, text="reply")
    assert result["round_completed"] is True
    assert result["round_seq"] == 1


# ── 1e. retake_turn ────────────────────────────────────────────────────────

def _snapshot(sess):
    return {
        "turn": sess.get("turn"),
        "round": sess.get("round"),
        "action_count": sess.get("action_count"),
        "_round_seq": sess.get("_round_seq", 0),
        "_round_spoken": list(sess.get("_round_spoken", [])),
    }


def test_retake_mid_turn_branch_removes_partial_actions_only():
    sid, host_token, tokens = _start_session_with_three_humans()
    try:
        sess = _sessions[sid]
        sess["action_count"] = 1
        sess["history"] = [
            {"role": "user", "content": "topic"},
            {"role": "assistant", "content": "Alice: hi", "character_id": "char_a"},
        ]
        before = _snapshot(sess)
        resp = client.post(f"/api/session/{sid}/retake", headers=_auth(host_token))
        assert resp.status_code == 200
        assert resp.json()["removed"] == 1
        after = _snapshot(sess)
        # OBSERVED CURRENT BEHAVIOR (キャラクタライゼーション、2026-09-18時点):
        # action_count以外(turn/round/_round_seq/_round_spoken)は変化しない。
        assert after["turn"] == before["turn"]
        assert after["round"] == before["round"]
        assert after["action_count"] == 0
        assert after["_round_seq"] == before["_round_seq"]
        assert after["_round_spoken"] == before["_round_spoken"]
        assert sess["history"] == [{"role": "user", "content": "topic"}]
    finally:
        _sessions.pop(sid, None)


def test_retake_same_round_branch_steps_back_one_character():
    sid, host_token, tokens = _start_session_with_three_humans()
    try:
        sess = _sessions[sid]
        # char_aが発言完了 → turn=1（char_bの番）
        r1 = client.post(
            f"/api/session/{sid}/human_turn",
            json={"action": "send", "text": "hi from a", "expected_round_seq": 0},
            headers=_auth(tokens["char_a"]),
        )
        assert r1.status_code == 200
        sess["ai_task"] = None
        before = _snapshot(sess)
        assert before["turn"] == 1
        resp = client.post(f"/api/session/{sid}/retake", headers=_auth(host_token))
        assert resp.status_code == 200
        after = _snapshot(sess)
        assert after["turn"] == 0  # char_aの番に戻る
        assert after["round"] == before["round"]
        assert after["action_count"] == 0
        # 2026-09-19、_restore_round_spoken_for_retakeによる意図した修正:
        # 巻き戻されたchar_aの「発言済み」記録が正しく取り除かれる
        # （修正前はbefore["_round_spoken"] == ["char_a"]のまま残っていた——
        # retake_turnの根本的な欠陥そのものだった）。
        assert before["_round_spoken"] == ["char_a"]
        assert after["_round_spoken"] == []
        assert after["_round_seq"] == before["_round_seq"] == 0
    finally:
        _sessions.pop(sid, None)


def test_retake_round_boundary_branch_decrements_round_and_lands_on_last_char():
    sid, host_token, tokens = _start_session_with_three_humans()
    try:
        sess = _sessions[sid]
        for cid in ("char_a", "char_b", "char_c"):
            r = client.post(
                f"/api/session/{sid}/human_turn",
                json={"action": "send", "text": f"hi from {cid}", "expected_round_seq": sess.get("_round_seq", 0)},
                headers=_auth(tokens[cid]),
            )
            assert r.status_code == 200
            sess["ai_task"] = None
        # 全員発言完了、次はラウンド2のchar_a
        assert sess["round"] == 2
        assert sess["turn"] == 0
        assert sess["_round_seq"] == 1
        assert sess["_round_spoken"] == []
        resp = client.post(f"/api/session/{sid}/retake", headers=_auth(host_token))
        assert resp.status_code == 200
        after = _snapshot(sess)
        assert after["round"] == 1  # 1つ前のラウンドへ
        # このテストは自然順(a,b,c)で発言させているため、履歴実体から特定した
        # retaken_char_id(char_c)はinitiative[-1]と一致し、turnの値自体は
        # 修正前と変わらない（designateで食い違うケースは別テストで確認済み）。
        assert after["turn"] == 2  # initiative.index("char_c")
        assert after["action_count"] == 0
        # _round_seqは減算されない(retake_turnが意図的に一切触らないため、設計方針
        # 参照)。
        assert after["_round_seq"] == 1
        # 2026-09-19、_restore_round_spoken_for_retakeによる意図した修正:
        # ラウンド境界での巻き戻しはchar_c以外全員を再度spoken扱いに復元する
        # （修正前は[]のまま——char_a/b/cが「ラウンド1で発言済み」だった記録が
        # 完全に失われ、以後ラウンドが二度と完了しなくなる欠陥だった）。
        assert after["_round_spoken"] == ["char_a", "char_b"]
    finally:
        _sessions.pop(sid, None)


def test_retake_at_absolute_beginning_returns_error():
    sid, host_token, tokens = _start_session_with_three_humans()
    try:
        sess = _sessions[sid]
        before = _snapshot(sess)
        before_history = list(sess["history"])
        resp = client.post(f"/api/session/{sid}/retake", headers=_auth(host_token))
        assert resp.status_code == 200
        assert resp.json() == {"error": "Cannot retake: at the beginning"}
        after = _snapshot(sess)
        assert after == before
        assert sess["history"] == before_history
    finally:
        _sessions.pop(sid, None)


def test_retake_round_boundary_after_designate_jump_picks_correct_character():
    """発見的テストの結果、2026-09-19の修正で解消された1件。

    当初（2026-09-18）: /human_turn経由のsendは_advance_turnのturn+1算術を必ず通る
    ため、「turnを繰り上げてラウンド境界を確定させたキャラ」は構造上常に
    initiative[-1]と一致してしまい、この経路単体ではretake_turnのinitiative[-1]
    前提とのズレを実際には作れないと判明した（最初のシミュレーション方法の誤り）。
    ズレが起きうるのはAIターン側の指名（_resolve_turn_startのdesignated_next消費、
    _advance_turnを経由しない直接ジャンプ）と組み合わさった場合のみ。そのケースを
    状態を直接構築して再現したところ、実際に食い違いが観測された
    （turn==sess["initiative"].index("char_c")、実際の最終発言者はchar_b）ため、
    retake_turnのturn再計算を履歴実体ベース（_retaken_char_id）に修正した。
    このテストは修正後、食い違いが解消されたことを確認する。
    """
    sid, host_token, tokens = _start_session_with_three_humans()
    try:
        sess = _sessions[sid]
        sess["turn"] = 0
        sess["round"] = 2
        sess["_round_spoken"] = []
        sess["_round_seq"] = 1
        sess["action_count"] = 0
        # 実際に最後に発言したのはchar_b（指名でinitiative[-1]=char_cより先に
        # 発言済みだった、という状況を模す）。initiative[-1]は char_c。
        sess["history"] = [
            {"role": "user", "content": "topic"},
            {"role": "assistant", "content": "Alice: a", "character_id": "char_a"},
            {"role": "assistant", "content": "Carol: c", "character_id": "char_c"},
            {"role": "assistant", "content": "Bob: b", "character_id": "char_b"},
        ]
        last_speaker_in_history = sess["history"][-1]["character_id"]
        assert last_speaker_in_history == "char_b"
        resp = client.post(f"/api/session/{sid}/retake", headers=_auth(host_token))
        assert resp.status_code == 200
        # 修正後: 履歴実体(char_b)から正しくturnを再計算する。initiative[-1]
        # (char_c)ではなく、実際の最終発言者(char_b)のindexと一致する。
        assert sess["turn"] == sess["initiative"].index("char_b")
        assert sess["turn"] == sess["initiative"].index(last_speaker_in_history)
        # 除去される履歴も、正しくchar_bの発言（末尾）になる。
        assert sess["history"][-1]["character_id"] == "char_c"
        # _round_spokenもchar_b以外(char_a, char_c)を再度spoken扱いに復元する。
        assert sess["_round_spoken"] == ["char_a", "char_c"]
    finally:
        _sessions.pop(sid, None)


def test_retake_restarts_ai_task():
    sid, host_token, tokens = _start_session_with_three_humans()
    try:
        sess = _sessions[sid]
        sess["action_count"] = 1
        sess["history"] = [{"role": "assistant", "content": "x", "character_id": "char_a"}]
        with patch("def_kari.api.routes.session_turn_engine._run_ai_turns"):
            resp = client.post(f"/api/session/{sid}/retake", headers=_auth(host_token))
        assert resp.status_code == 200
        assert sess.get("ai_task") is not None
    finally:
        _sessions.pop(sid, None)
