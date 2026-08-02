"""Phase 4: サーバー自律AIターン（_run_ai_turns / _execute_ai_turn / _end_session）のテスト。"""

import asyncio
import json
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
    """POST /{session_id}/human_turn (send) で ai_task がセットされ、完了まで実行されること。

    `with TestClient(app) as client:` を使い、TestClientのイベントループ（portal）を
    リクエスト間で共有することで、asyncio.create_task で起動される ai_task の完了を
    `client.portal.call()` で明示的に待てるようにする。単純な `client = TestClient(app)`
    だとリクエストごとに使い捨てのイベントループが作られるため、ai_task が実際に
    実行されるタイミングが不定になり、`with patch(...)` のスコープを抜けた後に実行されて
    未モックのLLM呼び出しが走ってしまう事故が実際に起きた（2026-08-02、後続テストが
    vram_lock を取ろうとしてハングした）。
    `_auto_start` は `with TestClient(...) as client:` にした際に lifespan 経由で
    実行されてしまう副作用（実バックエンド起動）を防ぐためモックする。
    """
    import asyncio
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions

    with patch("def_kari.api.main._auto_start"):
        with TestClient(app) as client:
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

            # _start_background_tts は human_turn_action が _execute_ai_turn の成否と無関係に
            # 無条件で呼ぶ別経路（人間プレイヤー自身の発言読み上げ）。これをモックし忘れると
            # threading.Thread が実際にVOICEVOXへの接続を試み、vram_lockを握ったまま
            # ブロックし続ける（asyncioのai_taskとは別物なのでportal.callでは待てない）。
            with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=lambda s: {}), \
                 patch("def_kari.api.routes.session._start_background_tts", return_value=""):
                resp = client.post(
                    f"/api/session/{sid}/human_turn",
                    json={"action": "send", "text": "Hello world"},
                    headers={"Authorization": f"Bearer {host_token}"},
                )
                assert resp.status_code == 200
                assert resp.json()["action"] == "send"
                # ai_task が作成されていること
                assert sess["ai_task"] is not None
                # モックのスコープを抜ける前にタスクの完了を待つ（同じportalのイベントループ上で実行される）
                client.portal.call(lambda: asyncio.wait_for(sess["ai_task"], timeout=2))


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

    # _execute_ai_turn が非空の text を返すため、_maybe_generate_turn_media が
    # 呼ばれるとTTS/T2I生成のバックグラウンドスレッドが実際に起動されてしまう
    # （本テストの検証対象はWAITING_FOR_HUMANのemit有無であり、TTS/T2I生成の
    # 副作用は想定外）。vram_lockを握ったまま後続テストとデッドロックする
    # 事故が実際に起きたため、この副作用そのものをモックで止める（2026-08-02）。
    with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=_fake_execute), \
         patch("def_kari.api.routes.session._maybe_generate_turn_media"):
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

    # 理由は test_run_ai_turns_emits_waiting_for_human_after_ai_turn のコメント参照
    with patch("def_kari.api.routes.session._execute_ai_turn", side_effect=_fake_execute), \
         patch("def_kari.api.routes.session._maybe_generate_turn_media"):
        with patch("def_kari.api.routes.session._game_event_bus") as mock_bus:
            mock_bus.emit.side_effect = lambda *a, **kw: emitted.append(a)
            await _run_ai_turns(sid)

    types = [e[1] for e in emitted if len(e) > 1]
    assert types == ["AI_TURN_COMPLETED"], f"got: {types}"
    del _sessions[sid]


# ── PATCH /auto_advance（セッション状態としての自動進行）──────────────

def test_auto_advance_patch_and_broadcast():
    """PATCH /auto_advance がセッション状態を更新し AUTO_ADVANCE_CHANGED を emit すること。

    最後のPATCHでai_taskが実際に起動される（initiative=["char_ai"]）。
    `with TestClient(app) as client:` でイベントループ（portal）をリクエスト間で共有し、
    `client.portal.call()` でai_taskの完了を明示的に待つことで、`with patch(...)` の
    スコープを抜けた後にモックされていない実LLM呼び出しが走ってしまう事故を防ぐ
    （2026-08-02、単純な `client = TestClient(app)` だとリクエストごとに使い捨ての
    イベントループが作られるため、ai_taskの実行タイミングが不定になっていた）。
    `_auto_start` は `with TestClient(...) as client:` にした際に lifespan 経由で
    実行されてしまう副作用（実バックエンド起動）を防ぐためモックする。
    """
    import asyncio
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions

    emitted = []
    with patch("def_kari.api.main._auto_start"):
        with TestClient(app) as client:
            start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
            d = start.json()
            sid, host_token = d["session_id"], d["host_token"]
            headers = {"Authorization": f"Bearer {host_token}"}

            with patch("def_kari.api.routes.session._game_event_bus") as mock_bus, \
                 patch("def_kari.api.routes.session._execute_ai_turn", side_effect=lambda s: {}):
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
                # モックのスコープを抜ける前にタスクの完了を待つ
                client.portal.call(lambda: asyncio.wait_for(_sessions[sid]["ai_task"], timeout=2))

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


# ── 持ち込みキャラの受け入れパイプライン（LLM審査 + visitor永続化） ──────────

def test_join_character_json_persists_visitor_file_on_audit_pass(tmp_path, _stub_character_audit):
    """審査通過時、visitors/{char_id}/profile.json が書かれること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    with patch("def_kari.api.routes.session._VISITORS_DIR", tmp_path):
        start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
        d = start.json()
        sid = d["session_id"]
        invite_code = d.get("invite_code") or next(iter(_sessions[sid]["invite_codes"]))

        char_json = {"name": "わたし", "player_type": "human"}
        join_res = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": char_json})
        assert join_res.status_code == 200
        char_id = join_res.json()["character_id"]

        profile_path = tmp_path / char_id / "profile.json"
        assert profile_path.exists()
        saved = json.loads(profile_path.read_text(encoding="utf-8"))
        assert saved["id"] == char_id
        assert saved["player_type"] == "human"
    _sessions.pop(sid, None)


def test_join_rejected_when_audit_fails(_stub_character_audit):
    """審査で拒否されたら400になり、guest_chars/initiative/players に一切書き込まれないこと。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    from def_kari.safety.character_audit import AuditResult
    client = TestClient(app)

    _stub_character_audit.return_value = AuditResult(passed=False, reason="prompt injection detected")

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid = d["session_id"]
    invite_code = d.get("invite_code") or next(iter(_sessions[sid]["invite_codes"]))

    char_json = {"name": "怪しいキャラ", "player_type": "human"}
    resp = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": char_json})
    assert resp.status_code == 400
    assert "prompt injection detected" in resp.json()["detail"]

    assert _sessions[sid].get("guest_chars", {}) == {}
    assert _sessions[sid]["initiative"] == []
    assert _sessions[sid]["players"] == {d["host_token"]: ""}
    _sessions.pop(sid, None)


def test_join_visitor_dir_named_by_server_char_id_not_client_supplied(tmp_path, _stub_character_audit):
    """visitorディレクトリ名はクライアント指定の id フィールドではなく、サーバー生成の guest_xxxx になること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    with patch("def_kari.api.routes.session._VISITORS_DIR", tmp_path):
        start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
        d = start.json()
        sid = d["session_id"]
        invite_code = d.get("invite_code") or next(iter(_sessions[sid]["invite_codes"]))

        char_json = {"id": "../../etc/passwd", "name": "evil", "player_type": "human"}
        join_res = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": char_json})
        assert join_res.status_code == 200
        char_id = join_res.json()["character_id"]
        assert char_id.startswith("guest_")

        created_dirs = [p.name for p in tmp_path.iterdir() if p.is_dir()]
        assert created_dirs == [char_id]
    _sessions.pop(sid, None)


def test_autosave_refreshes_visitor_snapshot_with_skill_values(tmp_path, _stub_character_audit):
    """_autosave() が skill_values の更新を visitor profile.json に反映すること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions, _autosave
    client = TestClient(app)

    with patch("def_kari.api.routes.session._VISITORS_DIR", tmp_path):
        start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
        d = start.json()
        sid = d["session_id"]
        invite_code = d.get("invite_code") or next(iter(_sessions[sid]["invite_codes"]))

        char_json = {"name": "わたし", "player_type": "human"}
        join_res = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": char_json})
        char_id = join_res.json()["character_id"]

        _sessions[sid].setdefault("skill_values", {})[char_id] = {"str": 15}
        _autosave(sid)

        saved = json.loads((tmp_path / char_id / "profile.json").read_text(encoding="utf-8"))
        assert saved["_session_skill_values"] == {"str": 15}
    _sessions.pop(sid, None)


def test_visitors_dir_cap_skips_new_dirs_but_not_existing(tmp_path, _stub_character_audit):
    """visitors/ の件数上限に達した場合、joinは成功するが新規ディレクトリは作られないこと。
    既存ディレクトリの更新は上限に関係なく継続すること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions, _autosave
    client = TestClient(app)

    (tmp_path / "existing_guest").mkdir()
    (tmp_path / "existing_guest" / "profile.json").write_text("{}", encoding="utf-8")

    with patch("def_kari.api.routes.session._VISITORS_DIR", tmp_path), \
         patch("def_kari.api.routes.session._VISITORS_MAX_FILES", 1):
        start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
        d = start.json()
        sid = d["session_id"]
        invite_code = d.get("invite_code") or next(iter(_sessions[sid]["invite_codes"]))

        char_json = {"name": "わたし", "player_type": "human"}
        join_res = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": char_json})
        assert join_res.status_code == 200
        char_id = join_res.json()["character_id"]

        assert not (tmp_path / char_id).exists()

        # 既存ディレクトリの更新は上限に関係なく継続する
        _sessions[sid].setdefault("skill_values", {})["existing_guest"] = {"str": 1}
        _sessions[sid].setdefault("guest_chars", {})["existing_guest"] = {"id": "existing_guest"}
        _autosave(sid)
        saved = json.loads((tmp_path / "existing_guest" / "profile.json").read_text(encoding="utf-8"))
        assert saved["_session_skill_values"] == {"str": 1}
    _sessions.pop(sid, None)


# ── 持ち込みキャラのアイコン・立ち絵バックグラウンド生成 ──────────────

def test_extract_appearance_tags_flat_format():
    from def_kari.api.routes.session import _extract_appearance_tags
    assert _extract_appearance_tags({"appearance_tags": "1girl, red hair"}) == "1girl, red hair"


def test_extract_appearance_tags_versioned_format():
    from def_kari.api.routes.session import _extract_appearance_tags
    versioned = {"v1": {"base_profile": {"appearance_tags": "1boy, blue eyes"}}}
    assert _extract_appearance_tags(versioned) == "1boy, blue eyes"


def test_extract_appearance_tags_falls_back_to_visual_references_features():
    from def_kari.api.routes.session import _extract_appearance_tags
    data = {"visual_references": {"features": "tall, dark coat"}}
    assert _extract_appearance_tags(data) == "tall, dark coat"


def test_extract_appearance_tags_empty_when_missing():
    from def_kari.api.routes.session import _extract_appearance_tags
    assert _extract_appearance_tags({"name": "no appearance data"}) == ""


def test_generate_visitor_images_skips_when_no_appearance_tags(tmp_path):
    from def_kari.api.routes.session import _generate_visitor_images
    with patch("def_kari.api.routes.session._VISITORS_DIR", tmp_path), \
         patch("def_kari.api.routes.session._generate_t2i_image") as mock_gen:
        _generate_visitor_images("sid", "guest_x", {"name": "no tags"})
    mock_gen.assert_not_called()


def test_generate_visitor_images_skips_when_no_t2i_backend(tmp_path):
    from def_kari.api.routes.session import _generate_visitor_images
    with patch("def_kari.api.routes.session._VISITORS_DIR", tmp_path), \
         patch("def_kari.api.routes.session._generate_t2i_image") as mock_gen, \
         patch("def_kari.api.routes.session.load_settings", return_value={}):
        _generate_visitor_images("sid", "guest_x", {"appearance_tags": "1girl"})
    mock_gen.assert_not_called()


def test_generate_visitor_images_saves_icon_and_standing_and_emits_ready(tmp_path):
    """T2I生成をモックし、icon.png/standing.pngが正しいサイズ指定で生成・保存され、
    完了時に VISITOR_ICON_READY がemitされること。"""
    from def_kari.api.routes.session import _generate_visitor_images

    fake_icon = tmp_path / "src_icon.png"
    fake_icon.write_bytes(b"icon-bytes")
    fake_standing = tmp_path / "src_standing.png"
    fake_standing.write_bytes(b"standing-bytes")

    visitors_dir = tmp_path / "visitors"
    gen_calls = []

    def _fake_generate(prompt, backend, model=None, width=512, height=768, **kw):
        gen_calls.append((prompt, width, height))
        return str(fake_icon) if width == 512 else str(fake_standing)

    emitted = []
    with patch("def_kari.api.routes.session._VISITORS_DIR", visitors_dir), \
         patch("def_kari.api.routes.session._generate_t2i_image", side_effect=_fake_generate), \
         patch("def_kari.api.routes.session.load_settings", return_value={"t2i_backend": "a1111"}), \
         patch("def_kari.api.routes.session._game_event_bus") as mock_bus:
        mock_bus.emit.side_effect = lambda *a, **kw: emitted.append(a)
        _generate_visitor_images("sid-1", "guest_y", {"appearance_tags": "1girl, glitch"})

    assert (visitors_dir / "guest_y" / "icon.png").read_bytes() == b"icon-bytes"
    assert (visitors_dir / "guest_y" / "standing.png").read_bytes() == b"standing-bytes"
    assert len(gen_calls) == 2
    assert gen_calls[0][1:] == (512, 512)
    assert gen_calls[1][1:] == (832, 1216)
    ready_events = [e for e in emitted if len(e) > 1 and e[1] == "VISITOR_ICON_READY"]
    assert len(ready_events) == 1
    assert ready_events[0][2]["character_id"] == "guest_y"


def test_generate_visitor_images_fails_silently_on_exception(tmp_path):
    """T2Iバックエンドが例外を投げても呼び出し元に伝播しないこと（fail-silent）。"""
    from def_kari.api.routes.session import _generate_visitor_images
    with patch("def_kari.api.routes.session._VISITORS_DIR", tmp_path), \
         patch("def_kari.api.routes.session.load_settings", return_value={"t2i_backend": "a1111"}), \
         patch("def_kari.api.routes.session._generate_t2i_image", side_effect=RuntimeError("t2i backend down")):
        _generate_visitor_images("sid", "guest_z", {"appearance_tags": "1girl"})  # 例外を投げないことがテスト


def test_join_character_json_triggers_background_image_generation(_stub_character_audit):
    """join成功時に _generate_visitor_images がバックグラウンドスレッドから呼ばれること。

    標準ライブラリ threading.Thread 自体をpatchすると TestClient の内部処理と衝突してハングするため、
    _generate_visitor_images 関数だけをpatchし、スレッド完了を待ってから呼び出しを確認する。
    """
    import time
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    with patch("def_kari.api.routes.session._generate_visitor_images") as mock_gen:
        start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
        d = start.json()
        sid = d["session_id"]
        invite_code = d.get("invite_code") or next(iter(_sessions[sid]["invite_codes"]))

        char_json = {"appearance_tags": "1girl, glitch"}
        join_res = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": char_json})
        assert join_res.status_code == 200
        char_id = join_res.json()["character_id"]

        for _ in range(50):  # 最大0.5秒、バックグラウンドスレッドの起動を待つ
            if mock_gen.called:
                break
            time.sleep(0.01)

    mock_gen.assert_called_once_with(sid, char_id, char_json)
    _sessions.pop(sid, None)


# ── POST /lobby/set_keeper_char（ロビー中にAIキーパーへキャラを割付け）──

def test_lobby_set_keeper_char_assigns_and_clears():
    """ロビー中にAIキーパーへキャラを割り付け・解除できること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    headers = {"Authorization": f"Bearer {host_token}"}
    assert _sessions[sid]["keeper_char_id"] == ""

    resp = client.post(
        f"/api/session/{sid}/lobby/set_keeper_char",
        json={"character_id": "character_hanfei_001"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["keeper_char_id"] == "character_hanfei_001"
    assert body["keeper_char_name"]
    assert _sessions[sid]["keeper_char_id"] == "character_hanfei_001"
    assert _sessions[sid]["keeper_char_name"] == body["keeper_char_name"]

    # 解除: 空文字列を送ると無名AIキーパーに戻る
    resp2 = client.post(
        f"/api/session/{sid}/lobby/set_keeper_char",
        json={"character_id": ""},
        headers=headers,
    )
    assert resp2.status_code == 200
    assert resp2.json()["keeper_char_id"] == ""
    assert _sessions[sid]["keeper_char_id"] == ""
    assert _sessions[sid]["keeper_char_name"] == ""
    _sessions.pop(sid, None)


def test_lobby_set_keeper_char_rejects_human_character():
    """player_type=human のキャラはAIキーパーとして割り付けられないこと。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    from def_kari.characters import load_profiles, get_character
    client = TestClient(app)

    profiles = load_profiles()
    human_char_id = next(
        (cid for cid, p in profiles.items() if get_character(cid, profiles).get("player_type") == "human"),
        None,
    )
    if human_char_id is None:
        pytest.skip("no human-type character available in fixture data")

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]

    resp = client.post(
        f"/api/session/{sid}/lobby/set_keeper_char",
        json={"character_id": human_char_id},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 400
    assert _sessions[sid]["keeper_char_id"] == ""
    _sessions.pop(sid, None)


def test_lobby_add_ai_with_game_sheet_and_backend():
    """/lobby/add_ai で game_sheet_id / backend_id を渡すと char_game_sheets / char_backends に反映されること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    headers = {"Authorization": f"Bearer {host_token}"}

    resp = client.post(
        f"/api/session/{sid}/lobby/add_ai",
        json={"character_id": "character_hanfei_001", "game_sheet_id": "sheet_a", "backend_id": "gemini"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert _sessions[sid]["char_game_sheets"]["character_hanfei_001"] == "sheet_a"
    assert _sessions[sid]["char_backends"]["character_hanfei_001"] == "gemini"
    _sessions.pop(sid, None)


def test_lobby_add_ai_without_game_sheet_or_backend_leaves_defaults():
    """/lobby/add_ai で game_sheet_id / backend_id を省略した場合は何も書き込まれないこと。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    headers = {"Authorization": f"Bearer {host_token}"}

    resp = client.post(
        f"/api/session/{sid}/lobby/add_ai",
        json={"character_id": "character_hanfei_001"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert "character_hanfei_001" not in _sessions[sid].get("char_game_sheets", {})
    assert "character_hanfei_001" not in _sessions[sid].get("char_backends", {})
    _sessions.pop(sid, None)


def test_lobby_set_keeper_char_with_backend():
    """/lobby/set_keeper_char で backend_id を渡すと char_backends に反映されること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    headers = {"Authorization": f"Bearer {host_token}"}

    resp = client.post(
        f"/api/session/{sid}/lobby/set_keeper_char",
        json={"character_id": "character_hanfei_001", "backend_id": "claude"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert _sessions[sid]["char_backends"]["character_hanfei_001"] == "claude"
    _sessions.pop(sid, None)


def test_lobby_set_keeper_char_rejects_already_in_initiative():
    """既にプレイヤー/AIスロット(initiative)にいるキャラはキーパーに割り付けられないこと。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    headers = {"Authorization": f"Bearer {host_token}"}

    add_resp = client.post(
        f"/api/session/{sid}/lobby/add_ai",
        json={"character_id": "character_hanfei_001"},
        headers=headers,
    )
    assert add_resp.status_code == 200

    resp = client.post(
        f"/api/session/{sid}/lobby/set_keeper_char",
        json={"character_id": "character_hanfei_001"},
        headers=headers,
    )
    assert resp.status_code == 409
    _sessions.pop(sid, None)


def test_lobby_add_ai_rejects_char_already_keeper():
    """既にキーパーに割り付けられているキャラは /lobby/add_ai で追加できないこと。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    headers = {"Authorization": f"Bearer {host_token}"}

    keeper_resp = client.post(
        f"/api/session/{sid}/lobby/set_keeper_char",
        json={"character_id": "character_hanfei_001"},
        headers=headers,
    )
    assert keeper_resp.status_code == 200

    add_resp = client.post(
        f"/api/session/{sid}/lobby/add_ai",
        json={"character_id": "character_hanfei_001"},
        headers=headers,
    )
    assert add_resp.status_code == 409
    assert "character_hanfei_001" not in _sessions[sid]["initiative"]
    _sessions.pop(sid, None)


def test_lobby_set_keeper_char_after_start_returns_409():
    """セッション開始後は /lobby/set_keeper_char が409を返すこと。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid, host_token = d["session_id"], d["host_token"]
    _sessions[sid]["lobby_active"] = False

    resp = client.post(
        f"/api/session/{sid}/lobby/set_keeper_char",
        json={"character_id": "character_hanfei_001"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert resp.status_code == 409
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


def test_leave_revokes_token():
    """/leave 後、そのトークンは verify_jwt で Token revoked として拒否されること。"""
    from fastapi.testclient import TestClient
    from def_kari.api.main import app
    from def_kari.api.routes.session import _sessions, verify_jwt
    from jose import JWTError
    client = TestClient(app)

    start = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = start.json()
    sid = d["session_id"]
    invite_code = d.get("invite_code") or next(iter(_sessions[sid]["invite_codes"]))

    char_json = {"name": "わたし", "player_type": "human"}
    join_res = client.post("/api/session/join", json={"invite_code": invite_code, "character_json": char_json})
    player_token = join_res.json()["player_token"]

    # leave前は有効
    verify_jwt(player_token)

    resp = client.post(f"/api/session/{sid}/leave", headers={"Authorization": f"Bearer {player_token}"})
    assert resp.status_code == 200

    with pytest.raises(JWTError):
        verify_jwt(player_token)
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


def test_save_session_episodic_writes_visitor_memory_for_guest_chars(tmp_path):
    """_save_session_episodic が guest_chars（訪問者）に対しても episodic memory を書けること。

    def_kari/gm/memory.py の _CHAR_DIRS に data/visitors/ を追加したことで、
    guest_* な char_id でも _char_base_dir が解決できるようになったことの回帰テスト。
    事前に visitors/{char_id}/ ディレクトリが存在している必要がある（_autosave_visitors 相当）。
    """
    from def_kari.api.routes.session import _save_session_episodic

    char_id = "guest_deadbeef"
    (tmp_path / char_id).mkdir(parents=True)

    with patch("def_kari.gm.memory._CHAR_DIRS", [tmp_path]):
        session = {
            "history": [{"role": "assistant", "character_id": char_id, "content": "guest: こんにちは", "emotion": "happy"}],
            "name_map": {char_id: "ゲスト"},
            "topic": "テスト",
            "round": 1,
            "initiative": [char_id],
        }
        _save_session_episodic("test-session-id", session)

    episodic_dir = tmp_path / char_id / "memory" / "episodic"
    assert episodic_dir.exists()
    files = list(episodic_dir.glob("*.json"))
    assert len(files) == 1
    entry = json.loads(files[0].read_text(encoding="utf-8"))
    assert entry["session_id"] == "test-session-id"


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
