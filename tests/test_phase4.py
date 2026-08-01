"""Phase 4: サーバー自律AIターン（_run_ai_turns / _execute_ai_turn / _end_session）のテスト。"""

import asyncio
import pytest
from unittest.mock import patch, MagicMock


# ── _get_current_speaker ─────────────────────────────────────────────

def test_get_current_speaker_normal():
    from def_kari.api.routes.session import _get_current_speaker
    sess = {"initiative": ["alice", "bob", "carol"], "turn": 1}
    assert _get_current_speaker(sess) == "bob"


def test_get_current_speaker_wrap():
    from def_kari.api.routes.session import _get_current_speaker
    sess = {"initiative": ["alice", "bob"], "turn": 4}
    assert _get_current_speaker(sess) == "alice"  # 4 % 2 == 0


def test_get_current_speaker_empty():
    from def_kari.api.routes.session import _get_current_speaker
    assert _get_current_speaker({"initiative": [], "turn": 0}) is None


# ── _run_ai_turns: 人間ターンで即停止 ──────────────────────────────

@pytest.mark.asyncio
async def test_run_ai_turns_stops_at_human():
    """現在のスピーカーが人間なら即停止してAIターンを実行しない。"""
    from def_kari.api.routes.session import _run_ai_turns, _sessions
    sid = "test-phase4-human"
    _sessions[sid] = {
        "initiative": ["char_human"],
        "turn": 0,
        "human_char_ids": ["char_human"],
        "guest_chars": {},
        "ai_task": None,
        "idle_shutdown_task": None,
    }
    called = []
    with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=lambda s: called.append(s) or {}):
        await _run_ai_turns(sid)
    assert called == []  # AIターンは呼ばれない
    del _sessions[sid]


@pytest.mark.asyncio
async def test_run_ai_turns_stops_on_error():
    """_execute_ai_turn が error を返したら停止する。"""
    from def_kari.api.routes.session import _run_ai_turns, _sessions
    sid = "test-phase4-error"
    _sessions[sid] = {
        "initiative": ["char_ai"],
        "turn": 0,
        "human_char_ids": [],
        "guest_chars": {},
        "ai_task": None,
        "idle_shutdown_task": None,
        "name_map": {"char_ai": "AI"},
    }
    calls = []
    def _fake_execute(s):
        calls.append(s)
        return {"error": "backend down"}

    with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=_fake_execute):
        await _run_ai_turns(sid)
    assert len(calls) == 1  # 1回試みてerrorで停止
    del _sessions[sid]


@pytest.mark.asyncio
async def test_run_ai_turns_stops_on_waiting_for_human():
    """_execute_ai_turn が waiting_for_human を返したら停止する。"""
    from def_kari.api.routes.session import _run_ai_turns, _sessions
    sid = "test-phase4-wait"
    _sessions[sid] = {
        "initiative": ["char_ai"],
        "turn": 0,
        "human_char_ids": [],
        "guest_chars": {},
        "ai_task": None,
        "idle_shutdown_task": None,
    }
    calls = []
    def _fake_execute(s):
        calls.append(s)
        return {"waiting_for_human": True}

    with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=_fake_execute):
        await _run_ai_turns(sid)
    assert len(calls) == 1
    del _sessions[sid]


@pytest.mark.asyncio
async def test_run_ai_turns_cancelled():
    """キャンセルされたらCancelledErrorが伝播する（_end_session等でキャンセル可能）。"""
    from def_kari.api.routes.session import _run_ai_turns, _sessions
    sid = "test-phase4-cancel"
    _sessions[sid] = {
        "initiative": ["char_ai"],
        "turn": 0,
        "human_char_ids": [],
        "guest_chars": {},
        "ai_task": None,
        "idle_shutdown_task": None,
    }

    blocker = asyncio.Event()

    def _slow_execute(s):
        # run_in_executor で呼ばれる同期関数の代わりに長時間ブロックをシミュレート
        import time
        time.sleep(0.05)
        return {}

    async def _run():
        with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=_slow_execute):
            await _run_ai_turns(sid)

    task = asyncio.create_task(_run())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    del _sessions[sid]


# ── _end_session ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_end_session_cancels_ai_task():
    """_end_session が ai_task をキャンセルすること。"""
    from def_kari.api.routes.session import _end_session, _sessions

    sid = "test-phase4-end"
    cancelled = []

    async def _long_task():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            cancelled.append(True)
            raise

    ai_task = asyncio.create_task(_long_task())
    await asyncio.sleep(0)  # タスクを sleep まで進める
    _sessions[sid] = {
        "ai_task": ai_task,
        "idle_shutdown_task": None,
        "ws_connections": {},
        "players": {},
    }
    await _end_session(sid)
    assert cancelled == [True]
    # _end_session が pop するので既に削除済み
    assert sid not in _sessions


@pytest.mark.asyncio
async def test_end_session_no_session_is_noop():
    """存在しないセッションに _end_session を呼んでも例外が出ないこと。"""
    from def_kari.api.routes.session import _end_session
    await _end_session("nonexistent-session-id")  # 例外なし


# ── human_turn の send 後に ai_task が作られること ─────────────────

def test_human_turn_send_creates_ai_task():
    """POST /{session_id}/human_turn (send) で ai_task がセットされること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    # セッション作成（キャラなし）
    start = client.post("/api/session/start", json={"character_ids": []})
    d = start.json()
    sid = d["session_id"]
    host_token = d["host_token"]

    # 最初のキャラを人間にする（initiative が空なので手動でセット）
    sess = _sessions[sid]
    sess["initiative"] = ["char_human"]
    sess["turn"] = 0
    sess["human_char_ids"] = ["char_human"]
    sess["name_map"]["char_human"] = "Human"
    sess["counters"] = {}

    resp = client.post(
        f"/api/session/{sid}/human_turn",
        json={"action": "send", "text": "Hello world"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["action"] == "send"
    # ai_task が作成されていること（まだ done かもしれないが None ではない）
    assert sess["ai_task"] is not None


# ── keeper_skip 競合修正（_skip_gen）─────────────────────────────────

@pytest.mark.asyncio
async def test_skip_turn_increments_skip_gen():
    """skip_turn が _skip_gen をインクリメントすること（競合検出フラグ）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": []})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    sess = _sessions[sid]
    sess["initiative"] = ["char_ai", "char_human"]
    sess["turn"] = 0
    sess["human_char_ids"] = ["char_human"]
    sess["name_map"] = {"char_ai": "AI", "char_human": "Human"}
    sess["counters"] = {}

    assert sess.get("_skip_gen", 0) == 0
    resp = client.post(
        f"/api/session/{sid}/skip",
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 200
    assert sess.get("_skip_gen", 0) == 1


@pytest.mark.asyncio
async def test_run_ai_turns_discards_stale_result_on_skip():
    """executor 実行中に _skip_gen が変わったら AI 結果を捨てて continue すること。"""
    from def_kari.api.routes.session import _run_ai_turns, _sessions
    import asyncio

    sid = "test-skip-gen-discard"
    _sessions[sid] = {
        "initiative": ["char_ai", "char_human"],
        "turn": 0,
        "human_char_ids": ["char_human"],
        "guest_chars": {},
        "ai_task": None,
        "idle_shutdown_task": None,
        "name_map": {"char_ai": "AI", "char_human": "Human"},
        "counters": {},
        "_skip_gen": 0,
        "ai_paused": False,
    }
    sess = _sessions[sid]
    emitted = []

    def _fake_execute(s):
        # LLM 実行中にスキップが来たシミュレーション
        sess["_skip_gen"] += 1
        sess["turn"] = 1  # スキップ後は human ターン
        return {"character_id": "char_ai", "character_name": "AI", "text": "hello"}

    with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=_fake_execute):
        with patch("def_kari.api.routes.session._game_event_bus") as mock_bus:
            mock_bus.emit.side_effect = lambda *a, **kw: emitted.append(a)
            await _run_ai_turns(sid)

    # AI_TURN_COMPLETED は emit されていない（stale 結果は捨てる）
    ai_completed = [e for e in emitted if len(e) > 1 and e[1] == "AI_TURN_COMPLETED"]
    assert ai_completed == [], f"stale result should be discarded, got: {ai_completed}"
    del _sessions[sid]


def test_lobby_config_preserves_observer_host_keeper_mode():
    """観戦者ホストが lobby_config を呼んでも host_keeper_mode が False のまま保たれること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]

    # 観戦者モードに設定（is_keeper=false）
    client.patch(
        f"/api/session/{sid}/host_role?is_keeper=false",
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert _sessions[sid]["host_keeper_mode"] is False

    # lobby_config を host_char_id="" で呼ぶ（observer / keeper 両方が空文字を送る）
    resp = client.post(
        f"/api/session/{sid}/lobby_config",
        json={"max_players": 4, "host_char_id": ""},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 200
    # host_keeper_mode は False のまま（上書きされていない）
    assert _sessions[sid]["host_keeper_mode"] is False


# ── PATCH /lobby/mode & /lobby/keeper_source ─────────────────────────

def test_lobby_set_trpg_mode():
    """PATCH /lobby/mode でセッションの trpg_mode が更新されること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    assert _sessions[sid].get("lobby_active") is True

    resp = client.patch(
        f"/api/session/{sid}/lobby/mode",
        json={"trpg_mode": False},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["trpg_mode"] is False
    assert _sessions[sid]["trpg_mode"] is False

    resp2 = client.patch(
        f"/api/session/{sid}/lobby/mode",
        json={"trpg_mode": True},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp2.status_code == 200
    assert _sessions[sid]["trpg_mode"] is True


def test_lobby_set_keeper_source():
    """PATCH /lobby/keeper_source で waiting_for_gm が更新されること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]

    resp = client.patch(
        f"/api/session/{sid}/lobby/keeper_source",
        json={"waiting_for_gm": True},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["waiting_for_gm"] is True
    assert _sessions[sid]["waiting_for_gm"] is True

    resp2 = client.patch(
        f"/api/session/{sid}/lobby/keeper_source",
        json={"waiting_for_gm": False},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp2.status_code == 200
    assert _sessions[sid]["waiting_for_gm"] is False


def test_lobby_mode_after_start_returns_409():
    """セッション開始後に /lobby/mode を呼ぶと 409 が返ること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]

    # lobby_active を False にしてセッション開始済みをシミュレート
    _sessions[sid]["lobby_active"] = False

    resp = client.patch(
        f"/api/session/{sid}/lobby/mode",
        json={"trpg_mode": True},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_run_ai_turns_emits_waiting_for_human_after_ai_turn():
    """AIターン完了後、次が人間ターンなら ai_resume の往復を待たずに
    WAITING_FOR_HUMAN が emit されること（プレイヤーターン到達で進行が止まるバグの回帰テスト）。"""
    from def_kari.api.routes.session import _run_ai_turns, _sessions

    sid = "test-emit-waiting-after-ai"
    _sessions[sid] = {
        "initiative": ["char_ai", "char_human"],
        "turn": 0,
        "human_char_ids": ["char_human"],
        "guest_chars": {},
        "ai_task": None,
        "idle_shutdown_task": None,
        "name_map": {"char_ai": "AI", "char_human": "Human"},
        "counters": {},
        "_skip_gen": 0,
        "ai_paused": False,
        "round": 1,
    }
    sess = _sessions[sid]
    emitted = []

    def _fake_execute(s):
        sess["turn"] = 1  # AIターン完了 → 次は human
        return {"character_id": "char_ai", "character_name": "AI", "text": "hello"}

    with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=_fake_execute):
        with patch("def_kari.api.routes.session._game_event_bus") as mock_bus:
            mock_bus.emit.side_effect = lambda *a, **kw: emitted.append(a)
            await _run_ai_turns(sid)

    types = [e[1] for e in emitted if len(e) > 1]
    assert types == ["AI_TURN_COMPLETED", "WAITING_FOR_HUMAN"], f"got: {types}"
    wfh = [e for e in emitted if len(e) > 1 and e[1] == "WAITING_FOR_HUMAN"][0]
    assert wfh[2]["character_id"] == "char_human"
    del _sessions[sid]


@pytest.mark.asyncio
async def test_run_ai_turns_no_waiting_emit_when_next_is_ai():
    """AIターン完了後、次もAIターンなら WAITING_FOR_HUMAN は emit されないこと。"""
    from def_kari.api.routes.session import _run_ai_turns, _sessions

    sid = "test-no-waiting-next-ai"
    _sessions[sid] = {
        "initiative": ["char_ai1", "char_ai2", "char_human"],
        "turn": 0,
        "human_char_ids": ["char_human"],
        "guest_chars": {},
        "ai_task": None,
        "idle_shutdown_task": None,
        "name_map": {"char_ai1": "AI1", "char_ai2": "AI2", "char_human": "Human"},
        "counters": {},
        "_skip_gen": 0,
        "ai_paused": False,
        "round": 1,
    }
    sess = _sessions[sid]
    emitted = []

    def _fake_execute(s):
        sess["turn"] = 1  # AIターン完了 → 次も AI
        return {"character_id": "char_ai1", "character_name": "AI1", "text": "hi"}

    with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=_fake_execute):
        with patch("def_kari.api.routes.session._game_event_bus") as mock_bus:
            mock_bus.emit.side_effect = lambda *a, **kw: emitted.append(a)
            await _run_ai_turns(sid)

    types = [e[1] for e in emitted if len(e) > 1]
    assert types == ["AI_TURN_COMPLETED"], f"got: {types}"
    del _sessions[sid]


# ── PATCH /auto_advance（セッション状態としての自動進行）──────────────

def test_auto_advance_patch_and_broadcast():
    """PATCH /auto_advance がセッション状態を更新し AUTO_ADVANCE_CHANGED を emit すること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    headers = {"Authorization": f"Bearer {host_token}"}

    emitted = []
    with patch("def_kari.api.routes.session._game_event_bus") as mock_bus:
        mock_bus.emit.side_effect = lambda *a, **kw: emitted.append(a)

        # ロビー中: フラグは更新されるが ai_task は起動しない
        resp = client.patch(f"/api/session/{sid}/auto_advance", json={"enabled": True}, headers=headers)
        assert resp.status_code == 200
        assert _sessions[sid]["auto_advance"] is True
        assert _sessions[sid].get("ai_task") is None

        # OFF: ai_paused が立つ
        resp2 = client.patch(f"/api/session/{sid}/auto_advance", json={"enabled": False}, headers=headers)
        assert resp2.status_code == 200
        assert _sessions[sid]["auto_advance"] is False
        assert _sessions[sid]["ai_paused"] is True

        # セッション開始後・AIターン: ai_task が起動する
        _sessions[sid]["lobby_active"] = False
        _sessions[sid]["initiative"] = ["char_ai"]
        _sessions[sid]["turn"] = 0
        _sessions[sid]["human_char_ids"] = []
        resp3 = client.patch(f"/api/session/{sid}/auto_advance", json={"enabled": True}, headers=headers)
        assert resp3.status_code == 200
        assert _sessions[sid]["ai_paused"] is False
        assert _sessions[sid]["ai_task"] is not None

    changed = [e for e in emitted if len(e) > 1 and e[1] == "AUTO_ADVANCE_CHANGED"]
    assert [e[2]["enabled"] for e in changed] == [True, False, True]


def test_auto_advance_host_forbidden_when_gm_joined():
    """人間キーパー（gm）参加中はホストの PATCH /auto_advance が 403 になること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    _sessions[sid]["invited_gm_token"] = "dummy-gm-token"

    resp = client.patch(
        f"/api/session/{sid}/auto_advance",
        json={"enabled": True},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 403
    assert _sessions[sid].get("auto_advance", False) is False


@pytest.mark.asyncio
async def test_run_ai_turns_error_clears_auto_advance():
    """生成エラー時に auto_advance が落ち AUTO_ADVANCE_CHANGED → AI_ERROR の順で emit されること。"""
    from def_kari.api.routes.session import _run_ai_turns, _sessions

    sid = "test-error-clears-auto"
    _sessions[sid] = {
        "initiative": ["char_ai"],
        "turn": 0,
        "human_char_ids": [],
        "guest_chars": {},
        "ai_task": None,
        "idle_shutdown_task": None,
        "name_map": {"char_ai": "AI"},
        "counters": {},
        "_skip_gen": 0,
        "ai_paused": False,
        "auto_advance": True,
    }
    emitted = []

    with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=lambda s: {"error": "backend down"}):
        with patch("def_kari.api.routes.session._game_event_bus") as mock_bus:
            mock_bus.emit.side_effect = lambda *a, **kw: emitted.append(a)
            await _run_ai_turns(sid)

    types = [e[1] for e in emitted if len(e) > 1]
    assert types == ["AUTO_ADVANCE_CHANGED", "AI_ERROR"], f"got: {types}"
    assert _sessions[sid]["auto_advance"] is False
    del _sessions[sid]


# ── PATCH /lobby/settings（ロビー中のセッション設定変更）─────────────

def test_lobby_set_settings_updates_and_rebuilds():
    """PATCH /lobby/settings がお題・ルール・シナリオを更新し派生データも再構築すること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    headers = {"Authorization": f"Bearer {host_token}"}

    resp = client.patch(
        f"/api/session/{sid}/lobby/settings",
        json={"topic": "深夜の怪談", "rule_set": "default"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert _sessions[sid]["topic"] == "深夜の怪談"
    assert _sessions[sid]["rule_set"] == "default"
    assert isinstance(_sessions[sid]["rules"], list)  # rule_set 変更で rules が再構築される

    # 省略フィールドは変更されない
    resp2 = client.patch(
        f"/api/session/{sid}/lobby/settings",
        json={"trpg_scenario": ""},
        headers=headers,
    )
    assert resp2.status_code == 200
    assert _sessions[sid]["topic"] == "深夜の怪談"
    assert _sessions[sid]["npc_state"] == {}  # シナリオ変更で npc_state が再構築される

    # セッション開始後は 409
    _sessions[sid]["lobby_active"] = False
    resp3 = client.patch(
        f"/api/session/{sid}/lobby/settings",
        json={"topic": "x"},
        headers=headers,
    )
    assert resp3.status_code == 409
    _sessions.pop(sid, None)


def test_join_rejects_over_capacity():
    """ロビー中でも定員（max_players）を超えるプレイヤー参加が409で拒否されること。

    max_players がセッション開始時（lobby_config）まで保存されず、ロビー待機中は
    定員チェックが素通りして無制限に参加できたバグの回帰テスト。
    """
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    invite_code = d.get("invite_code") or next(iter(_sessions[sid]["invite_codes"]))
    assert _sessions[sid]["max_players"] == 4  # オンライン作成時のデフォルト

    # 定員2に変更
    client.patch(
        f"/api/session/{sid}/lobby/settings",
        json={"max_players": 2},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert _sessions[sid]["max_players"] == 2

    char_json = {"name": "わたし", "player_type": "human"}
    r1 = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": char_json})
    assert r1.status_code == 200
    r2 = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": char_json})
    assert r2.status_code == 200
    # 3人目は定員オーバー
    r3 = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": char_json})
    assert r3.status_code == 409

    # 観戦者は定員の対象外
    r4 = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": {}})
    assert r4.status_code == 200
    assert r4.json().get("role") == "observer"
    _sessions.pop(sid, None)


# ── POST /leave（非ホスト参加者の明示的退室）───────────────────────

def test_leave_removes_participant_and_emits_player_left():
    """非ホストが /leave すると players・joined_participants から除去され PLAYER_LEFT が emit されること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    invite_code = d.get("invite_code") or next(iter(_sessions[sid]["invite_codes"]))

    char_json = {"name": "わたし", "player_type": "human"}
    join_res = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": char_json})
    player_token = join_res.json()["player_token"]
    char_id = join_res.json()["character_id"]

    assert player_token in _sessions[sid]["players"]
    assert any(p["participant_id"] == char_id for p in _sessions[sid]["joined_participants"])

    emitted = []
    with patch("def_kari.api.routes.session._game_event_bus") as mock_bus:
        mock_bus.emit.side_effect = lambda *a, **kw: emitted.append(a)
        resp = client.post(f"/api/session/{sid}/leave", headers={"Authorization": f"Bearer {player_token}"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    assert player_token not in _sessions[sid]["players"]
    assert not any(p["participant_id"] == char_id for p in _sessions[sid]["joined_participants"])
    assert player_token not in _sessions[sid].get("token_to_participant", {})

    left_events = [e for e in emitted if len(e) > 1 and e[1] == "PLAYER_LEFT"]
    assert len(left_events) == 1
    assert left_events[0][2]["participant_id"] == char_id
    assert left_events[0][2]["character_id"] == char_id
    _sessions.pop(sid, None)


def test_leave_is_idempotent():
    """/leave を連打しても2回目以降は already_left を返し PLAYER_LEFT を再emitしないこと。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid = d["session_id"]
    invite_code = d.get("invite_code") or next(iter(_sessions[sid]["invite_codes"]))

    join_res = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": {}})
    player_token = join_res.json()["player_token"]
    headers = {"Authorization": f"Bearer {player_token}"}

    r1 = client.post(f"/api/session/{sid}/leave", headers=headers)
    assert r1.status_code == 200
    assert r1.json()["status"] == "ok"

    r2 = client.post(f"/api/session/{sid}/leave", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "already_left"
    _sessions.pop(sid, None)


def test_leave_rejects_host():
    """ホストトークンで /leave すると 400 が返ること（ホストは /end を使う）。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]

    resp = client.post(f"/api/session/{sid}/leave", headers={"Authorization": f"Bearer {host_token}"})
    assert resp.status_code == 400
    _sessions.pop(sid, None)


def test_leave_distinguishes_multiple_char_id_empty_participants():
    """char_id="" の観戦者が複数いても、leave した本人の participant_id だけが除去されること。

    以前はフロント側が char_id で PLAYER_LEFT を判定しており、observer が複数いると
    全員巻き添えになるバグがあった。participant_id ベースならこの問題は起きない。
    """
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid = d["session_id"]
    invite_code = d.get("invite_code") or next(iter(_sessions[sid]["invite_codes"]))

    obs1 = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": {}}).json()
    obs2 = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": {}}).json()
    assert obs1["character_id"] == "" and obs2["character_id"] == ""

    participant_ids_before = {p["participant_id"] for p in _sessions[sid]["joined_participants"]}
    assert len(participant_ids_before) == 2  # char_id="" でも participant_id は別々

    client.post(f"/api/session/{sid}/leave", headers={"Authorization": f"Bearer {obs1['player_token']}"})

    remaining = _sessions[sid]["joined_participants"]
    assert len(remaining) == 1  # obs2 のみ残る
    assert obs2["player_token"] in _sessions[sid]["players"]
    _sessions.pop(sid, None)


# ── WS切断/再接続イベント（PLAYER_DISCONNECTED / PLAYER_RECONNECTED）──

def test_ws_disconnect_emits_player_disconnected_but_keeps_participant():
    """WS切断時、players/joined_participants は保持したまま PLAYER_DISCONNECTED が emit されること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid = d["session_id"]
    invite_code = d.get("invite_code") or next(iter(_sessions[sid]["invite_codes"]))
    join_res = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": {}}).json()
    player_token = join_res["player_token"]

    emitted = []
    with patch("def_kari.api.routes.session._game_event_bus") as mock_bus:
        mock_bus.emit.side_effect = lambda *a, **kw: emitted.append(a)
        with client.websocket_connect(f"/api/session/{sid}/ws") as ws:
            ws.send_json({"type": "auth", "token": player_token})
        # with ブロックを抜けると切断される

    # 切断後も参加者データは残っている
    assert player_token in _sessions[sid]["players"]
    disconnected = [e for e in emitted if len(e) > 1 and e[1] == "PLAYER_DISCONNECTED"]
    assert len(disconnected) == 1
    assert disconnected[0][2]["participant_id"] == join_res["character_id"] or disconnected[0][2]["participant_id"].startswith("_")
    _sessions.pop(sid, None)


# ── POST /end の冪等性（episodic memory 多重書き込み防止）──────────

def test_end_session_idempotent_episodic_write():
    """/end を連打しても _save_session_episodic が1回しか実行されないこと。

    SESSION_ENDED ブロードキャスト受信でクライアントが /end を再POSTするループにより、
    キャラの episodic memory が同一セッション分だけ多重書き込みされるバグの回帰テスト。
    """
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": []})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    headers = {"Authorization": f"Bearer {host_token}"}

    calls = []
    with patch("def_kari.api.routes.session._save_session_episodic", side_effect=lambda s, sess: calls.append(s)):
        r1 = client.post(f"/api/session/{sid}/end", headers=headers)
        assert r1.status_code == 200
        # _end_session の猶予期間中の再POSTをシミュレート（セッションはまだ残っている想定）
        if sid in _sessions:
            r2 = client.post(f"/api/session/{sid}/end", headers=headers)
            assert r2.status_code == 200
            assert r2.json().get("status") == "ending"

    assert calls == [sid], f"episodic write should happen exactly once, got: {calls}"
    _sessions.pop(sid, None)


def test_available_slots_includes_waiting_for_gm():
    """available-slots レスポンスに waiting_for_gm と trpg_mode が含まれること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    invite_code = d.get("invite_code") or next(iter(_sessions[sid]["invite_codes"]))

    # waiting_for_gm を True に設定
    client.patch(
        f"/api/session/{sid}/lobby/keeper_source",
        json={"waiting_for_gm": True},
        headers={"Authorization": f"Bearer {host_token}"},
    )

    resp = client.post("/api/session/available-slots", json={"invite_code": invite_code})
    assert resp.status_code == 200
    data = resp.json()
    assert "waiting_for_gm" in data
    assert data["waiting_for_gm"] is True
    assert "trpg_mode" in data
