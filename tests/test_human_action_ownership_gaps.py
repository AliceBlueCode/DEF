"""8.34/8.35対策のテスト。

8.34: human_turn_actionのオーナーシップチェック（2026-08-08修正）がsend/extend/skip
限定になっており、interrupt/generate_imageには適用されていなかった。任意のplayer
トークンが他人のcharacter_idを指定するだけで、なりすまし発言・他人の発言力を
勝手に消費できた。designate_next（次発言者指名）も自治規約（-1コスト、自分の
ターンのみ）を無視し、role区別なく誰でも無条件・無償で呼べていた
（キーパー(host/gm)がターン不問・無償で指名できるのは既存の管理者特権として維持）。

8.35: 8.28と同型の穴。POST /start・POST /lobby/add_aiのcharacter_id/character_idsが
load_profiles()（public/private無差別）をそのまま使っており、公開ポート経由で
私有キャラクターのIDを直接指定すればAIがそのキャラのpersona_descriptionで実際に
喋り出し、historyを通じて間接的にペルソナ内容が漏れる経路が成立していた。
"""

import json

from fastapi.testclient import TestClient
from def_kari.api.main import app
from def_kari.api.public_main import public_app
from def_kari.api.routes.session import _sessions, issue_player_jwt

client = TestClient(app)
public_client = TestClient(public_app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _start_session_with_two_humans():
    resp = client.post("/api/session/start", json={"character_ids": []})
    d = resp.json()
    sid = d["session_id"]
    host_token = d["host_token"]
    sess = _sessions[sid]
    sess["initiative"] = ["char_a", "char_b"]
    sess["turn"] = 0
    sess["human_char_ids"] = ["char_a", "char_b"]
    sess["name_map"]["char_a"] = "Alice"
    sess["name_map"]["char_b"] = "Bob"
    sess["counters"] = {"char_a": 5, "char_b": 5}
    token_a = issue_player_jwt(sid, "player", "char_a")
    token_b = issue_player_jwt(sid, "player", "char_b")
    sess["players"][token_a] = "char_a"
    sess["players"][token_b] = "char_b"
    return sid, host_token, token_a, token_b


# ── interrupt/generate_image ownership (8.34) ──────────────────────────

def test_interrupt_rejects_other_players_character():
    sid, _host, token_a, _token_b = _start_session_with_two_humans()
    try:
        resp = client.post(
            f"/api/session/{sid}/human_turn",
            json={"action": "interrupt", "text": "hi", "character_id": "char_b"},
            headers=_auth(token_a),
        )
        assert resp.status_code == 409
        # なりすまし発言が履歴に残っていないこと
        assert _sessions[sid]["history"] == []
        assert _sessions[sid]["counters"]["char_b"] == 5
    finally:
        _sessions.pop(sid, None)


def test_interrupt_allows_own_character():
    sid, _host, token_a, _token_b = _start_session_with_two_humans()
    try:
        resp = client.post(
            f"/api/session/{sid}/human_turn",
            json={"action": "interrupt", "text": "hi", "character_id": "char_a"},
            headers=_auth(token_a),
        )
        assert resp.status_code == 200
        assert _sessions[sid]["counters"]["char_a"] == 3  # interruptは-2
    finally:
        _sessions.pop(sid, None)


def test_generate_image_rejects_other_players_character():
    sid, _host, token_a, _token_b = _start_session_with_two_humans()
    try:
        resp = client.post(
            f"/api/session/{sid}/human_turn",
            json={"action": "generate_image", "text": "", "character_id": "char_b"},
            headers=_auth(token_a),
        )
        assert resp.status_code == 409
        assert _sessions[sid]["counters"]["char_b"] == 5
    finally:
        _sessions.pop(sid, None)


def test_generate_image_allows_own_character():
    sid, _host, token_a, _token_b = _start_session_with_two_humans()
    try:
        resp = client.post(
            f"/api/session/{sid}/human_turn",
            json={"action": "generate_image", "text": "", "character_id": "char_a"},
            headers=_auth(token_a),
        )
        assert resp.status_code == 200
        assert _sessions[sid]["counters"]["char_a"] == 4
    finally:
        _sessions.pop(sid, None)


def test_host_interrupt_as_any_character_still_allowed():
    """host/gmトークンはchar_id claimを持たないため対象外のまま
    （既知の残課題、Finding #5と同系統でTODO.mdに記録済み）。"""
    sid, host_token, _token_a, _token_b = _start_session_with_two_humans()
    try:
        resp = client.post(
            f"/api/session/{sid}/human_turn",
            json={"action": "generate_image", "text": "", "character_id": "char_a"},
            headers=_auth(host_token),
        )
        assert resp.status_code == 200
    finally:
        _sessions.pop(sid, None)


# ── designate_next: player turn+cost, keeper free (8.34) ──────────────

def test_designate_by_player_not_on_turn_rejected():
    sid, _host, token_a, token_b = _start_session_with_two_humans()
    try:
        # turn=0（char_aの番）なのにchar_bのトークンで指名しようとする
        resp = client.post(
            f"/api/session/{sid}/designate",
            json={"target_id": "char_a"},
            headers=_auth(token_b),
        )
        assert resp.status_code == 409
        assert _sessions[sid]["designated_next"] is None
    finally:
        _sessions.pop(sid, None)


def test_designate_by_player_on_turn_succeeds_and_costs_one():
    sid, _host, token_a, _token_b = _start_session_with_two_humans()
    try:
        resp = client.post(
            f"/api/session/{sid}/designate",
            json={"target_id": "char_b"},
            headers=_auth(token_a),
        )
        assert resp.status_code == 200
        assert _sessions[sid]["counters"]["char_a"] == 4
        assert _sessions[sid]["designated_next"] == "char_b"
    finally:
        _sessions.pop(sid, None)


def test_designate_by_player_without_enough_speech_power_rejected():
    sid, _host, token_a, _token_b = _start_session_with_two_humans()
    try:
        _sessions[sid]["counters"]["char_a"] = 0
        resp = client.post(
            f"/api/session/{sid}/designate",
            json={"target_id": "char_b"},
            headers=_auth(token_a),
        )
        assert resp.status_code == 409
        assert _sessions[sid]["designated_next"] is None
    finally:
        _sessions.pop(sid, None)


def test_designate_by_keeper_is_free_and_unrestricted():
    """host（キーパー）はターン不問・コスト不問で指名できる（既存の管理者特権、維持）。"""
    sid, host_token, _token_a, _token_b = _start_session_with_two_humans()
    try:
        resp = client.post(
            f"/api/session/{sid}/designate",
            json={"target_id": "char_b"},
            headers=_auth(host_token),
        )
        assert resp.status_code == 200
        assert _sessions[sid]["designated_next"] == "char_b"
        # host自身のcounterエントリは存在しない・変化しない
        assert "host" not in _sessions[sid]["counters"]
    finally:
        _sessions.pop(sid, None)


# ── private character injection via public /start and lobby/add_ai (8.35) ──

def _patch_char_dirs(monkeypatch, public_dir, private_dir):
    import def_kari.characters as characters_module
    from def_kari.api.routes import characters_common
    monkeypatch.setattr(characters_module, "CHARACTERS_DIR", public_dir)
    monkeypatch.setattr(characters_module, "PRIVATE_CHARACTERS_DIR", private_dir)
    monkeypatch.setattr(characters_common, "_CHAR_DIRS", [public_dir, private_dir])
    monkeypatch.setattr(characters_common, "_PUBLIC_CHAR_DIRS", [public_dir])


def _write_private_character(private_dir, char_id="secret_char"):
    d = private_dir / char_id
    d.mkdir(parents=True)
    (d / "profile.json").write_text(
        json.dumps({"v1": {"base_profile": {"name": "Secret Persona"}}}), encoding="utf-8",
    )


def test_start_via_public_app_excludes_private_character(tmp_path, monkeypatch):
    public_dir, private_dir = tmp_path / "public", tmp_path / "private"
    public_dir.mkdir(); private_dir.mkdir()
    _write_private_character(private_dir)
    _patch_char_dirs(monkeypatch, public_dir, private_dir)

    r = public_client.post("/api/session/start", json={"character_ids": ["secret_char"]})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    try:
        sess = _sessions[sid]
        assert "secret_char" not in sess["initiative"]
        assert "secret_char" not in sess["name_map"]
    finally:
        _sessions.pop(sid, None)


def test_start_via_local_app_still_allows_private_character(tmp_path, monkeypatch):
    """回帰確認: ローカル専用ポート経由では従来どおりprivateキャラも使える。"""
    public_dir, private_dir = tmp_path / "public", tmp_path / "private"
    public_dir.mkdir(); private_dir.mkdir()
    _write_private_character(private_dir)
    _patch_char_dirs(monkeypatch, public_dir, private_dir)

    r = client.post("/api/session/start", json={"character_ids": ["secret_char"]})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    try:
        sess = _sessions[sid]
        assert "secret_char" in sess["initiative"]
        assert sess["name_map"]["secret_char"] == "Secret Persona"
    finally:
        _sessions.pop(sid, None)


def test_lobby_add_ai_via_public_app_rejects_private_character(tmp_path, monkeypatch):
    public_dir, private_dir = tmp_path / "public", tmp_path / "private"
    public_dir.mkdir(); private_dir.mkdir()
    _write_private_character(private_dir)
    _patch_char_dirs(monkeypatch, public_dir, private_dir)

    r = public_client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = r.json()
    sid = d["session_id"]
    host_token = d["host_token"]
    try:
        resp = public_client.post(
            f"/api/session/{sid}/lobby/add_ai",
            json={"character_id": "secret_char"},
            headers=_auth(host_token),
        )
        assert resp.status_code == 404
        assert "secret_char" not in _sessions[sid]["initiative"]
    finally:
        _sessions.pop(sid, None)


def test_lobby_add_ai_via_local_app_still_allows_private_character(tmp_path, monkeypatch):
    """回帰確認: ローカル専用ポート経由では従来どおりprivateキャラも追加できる。"""
    public_dir, private_dir = tmp_path / "public", tmp_path / "private"
    public_dir.mkdir(); private_dir.mkdir()
    _write_private_character(private_dir)
    _patch_char_dirs(monkeypatch, public_dir, private_dir)

    r = client.post("/api/session/start", json={"character_ids": [], "online_mode": True})
    d = r.json()
    sid = d["session_id"]
    host_token = d["host_token"]
    try:
        resp = client.post(
            f"/api/session/{sid}/lobby/add_ai",
            json={"character_id": "secret_char"},
            headers=_auth(host_token),
        )
        assert resp.status_code == 200
        assert "secret_char" in _sessions[sid]["initiative"]
    finally:
        _sessions.pop(sid, None)
