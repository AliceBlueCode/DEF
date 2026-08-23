"""ラウンド完了判定（キーパー発言タイミング）のテスト。

従来はフロントエンド側で「initiative配列の末尾のキャラが喋ったか」という
ヒューリスティックのみでラウンド完了・キーパー発言タイミングを判定していた。
しかし指名（designate）はターンをinitiativeの並び順を無視して直接ジャンプ
させるため、末尾のキャラが一度もそのラウンド中に発言しないまま次ラウンドへ
巻き戻ることがあり、そのラウンドのキーパー発言が握り潰されていた
（2026-08-23、実機で発覚。ユーザー報告:「キーパーにターンが回らなくなっている」）。

`_mark_spoken_and_check_round_complete`はinitiativeの並び順・turnのモジュロ演算に
依存しない、サーバー側の権威データ（「誰が発言済みか」の集合）としてこれを解消する。
"""

from fastapi.testclient import TestClient
from def_kari.api.main import app
from def_kari.api.routes.session import _sessions, issue_player_jwt
from def_kari.api.routes.session_turn_engine import _mark_spoken_and_check_round_complete

client = TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _start_session_with_three_humans():
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


# ── 単体: _mark_spoken_and_check_round_complete ─────────────────────────

def test_round_completes_only_once_everyone_has_spoken():
    session = {"initiative": ["a", "b", "c"]}
    assert _mark_spoken_and_check_round_complete(session, "a") is False
    assert _mark_spoken_and_check_round_complete(session, "b") is False
    assert _mark_spoken_and_check_round_complete(session, "c") is True
    # 完了後は発言済み集合がリセットされ、次ラウンドの記録が始まる
    assert session["_round_spoken"] == []
    assert session["_round_seq"] == 1


def test_round_complete_ignores_array_order_designate_style_jump():
    """指名で配列の並び順を無視してa→c→bの順に発言しても、末尾(c)が発言した時点
    ではなく、全員(a・b・c)が出そろった時点でTrueになること
    （旧: initiative配列の末尾=cが喋った瞬間にキーパーを発火していたため、
    bがまだ発言していないのに早撃ちしてしまう不具合があった）。
    """
    session = {"initiative": ["a", "b", "c"]}
    assert _mark_spoken_and_check_round_complete(session, "a") is False
    # cはinitiative配列の末尾だが、bより先に指名で呼ばれても即完了しない
    assert _mark_spoken_and_check_round_complete(session, "c") is False
    assert _mark_spoken_and_check_round_complete(session, "b") is True


def test_round_complete_same_char_speaking_twice_does_not_double_count():
    session = {"initiative": ["a", "b"]}
    assert _mark_spoken_and_check_round_complete(session, "a") is False
    assert _mark_spoken_and_check_round_complete(session, "a") is False
    assert _mark_spoken_and_check_round_complete(session, "b") is True


def test_round_seq_increments_across_multiple_rounds():
    session = {"initiative": ["a", "b"]}
    _mark_spoken_and_check_round_complete(session, "a")
    assert _mark_spoken_and_check_round_complete(session, "b") is True
    assert session["_round_seq"] == 1
    _mark_spoken_and_check_round_complete(session, "a")
    assert _mark_spoken_and_check_round_complete(session, "b") is True
    assert session["_round_seq"] == 2


def test_round_complete_accounts_for_initiative_grown_mid_round():
    """ゲスト参加等でラウンド途中にinitiativeが増えた場合、新規キャラの発言も
    待ってから完了と判定すること。"""
    session = {"initiative": ["a", "b"]}
    assert _mark_spoken_and_check_round_complete(session, "a") is False
    session["initiative"].append("c")  # ラウンド途中でゲストキャラが参加
    assert _mark_spoken_and_check_round_complete(session, "b") is False
    assert _mark_spoken_and_check_round_complete(session, "c") is True


# ── 結合: /human_turn 経由でround_completed/round_seqが正しく返ること ──────

def test_human_turn_send_reports_round_completed_only_after_all_spoken():
    sid, _host, tokens = _start_session_with_three_humans()
    try:
        sess = _sessions[sid]
        r1 = client.post(
            f"/api/session/{sid}/human_turn",
            json={"action": "send", "text": "hi", "character_id": "char_a", "expected_round": sess["round"]},
            headers=_auth(tokens["char_a"]),
        )
        assert r1.json()["round_completed"] is False

        # 指名の代わりに直接turnを操作し、配列末尾(char_c)を先に呼ぶ
        # （非配列順のジャンプをシミュレート）。ai_taskはNoneに戻しておかないと、
        # send のたびに再起動される背景の _run_ai_turns がturn/roundを
        # 独自に正規化してしまい、この手動操作と競合してしまう。
        sess["turn"] = 2
        sess["ai_task"] = None
        r2 = client.post(
            f"/api/session/{sid}/human_turn",
            json={"action": "send", "text": "hi", "character_id": "char_c", "expected_round": sess["round"]},
            headers=_auth(tokens["char_c"]),
        )
        # 配列末尾(char_c)が喋っても、char_bが未発言なのでまだ完了しない
        assert r2.json()["round_completed"] is False

        sess["turn"] = 1
        sess["ai_task"] = None
        r3 = client.post(
            f"/api/session/{sid}/human_turn",
            json={"action": "send", "text": "hi", "character_id": "char_b", "expected_round": sess["round"]},
            headers=_auth(tokens["char_b"]),
        )
        assert r3.json()["round_completed"] is True
        assert r3.json()["round_seq"] == 1
    finally:
        _sessions.pop(sid, None)


def test_human_turn_skip_reports_round_completed():
    sid, _host, tokens = _start_session_with_three_humans()
    try:
        sess = _sessions[sid]
        for cid in ("char_a", "char_b"):
            client.post(
                f"/api/session/{sid}/human_turn",
                json={"action": "send", "text": "hi", "character_id": cid, "expected_round": sess["round"]},
                headers=_auth(tokens[cid]),
            )
            sess["ai_task"] = None
        r = client.post(
            f"/api/session/{sid}/human_turn",
            json={"action": "skip", "character_id": "char_c", "expected_round": sess["round"]},
            headers=_auth(tokens["char_c"]),
        )
        assert r.json()["round_completed"] is True
    finally:
        _sessions.pop(sid, None)
