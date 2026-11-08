"""GET /{session_id} の情報境界のテスト（機密フィールド除外 + 参加者認証）。

以前は`_session_for_json`（autosave用に「全部残す」設計）をGETレスポンスにも
そのまま流用しており、host_token・invited_gm_token・players（{token: char_id}、
キーが全参加者の認証トークン）・invite_codes・token_to_participantが無認証で
丸見えになっていた。session_idさえ知っていれば（＝招待コードで参加した時点で
必ず知っている）GETリクエスト1発でセッション内の全員に完全になりすませる状態
だった（DEF_kari_セキュリティ設計書_内部用.md 8.1参照）。

さらに2026-08-11、エンドポイント自体を無認証から参加者認証（require_participant、
observer含む全ロール）に変更した。それまでは退室・追放済みの元参加者や
session_idを知った第三者が、セッション全体（history・npc_state・skill_values等）を
読み続けられた（expelの実効性を損なう）。機密フィールドの除外は「正規参加者にも
見せてはいけないもの」の防御として引き続き必要（多層防御）。
"""

from fastapi.testclient import TestClient
from def_kari.api.main import app

client = TestClient(app)

_SECRET_KEYS = {"host_token", "invited_gm_token", "players", "invite_codes", "token_to_participant"}


def _start_with_token():
    start = client.post("/api/session/start", json={"character_ids": []})
    assert start.status_code == 200
    return start.json()["session_id"], start.json()["host_token"]


def test_get_session_requires_participant_token():
    """無認証（ヘッダーなし）・不正トークン・他セッションのトークンをすべて拒否すること。"""
    sid, host_token = _start_with_token()
    other_sid, other_token = _start_with_token()

    # ヘッダーなし → FastAPIの必須Headerバリデーションで422
    assert client.get(f"/api/session/{sid}").status_code == 422
    # でたらめなトークン → 401
    assert client.get(
        f"/api/session/{sid}", headers={"Authorization": "Bearer not-a-jwt"}
    ).status_code == 401
    # 別セッション用の正規トークン → 403（BOLA対策のセッションスコープ検証）
    assert client.get(
        f"/api/session/{sid}", headers={"Authorization": f"Bearer {other_token}"}
    ).status_code == 403
    # 自セッションのトークン → 200
    assert client.get(
        f"/api/session/{sid}", headers={"Authorization": f"Bearer {host_token}"}
    ).status_code == 200


def test_get_session_rejects_revoked_token():
    """退室・追放でrevokeされたトークンでは読めなくなること（expelの実効性）。"""
    from def_kari.api.routes.session import revoke_token, _revoked_jtis, _get_jwt_secret
    import jwt as _jwt

    sid, host_token = _start_with_token()
    assert client.get(
        f"/api/session/{sid}", headers={"Authorization": f"Bearer {host_token}"}
    ).status_code == 200

    revoke_token(host_token)
    try:
        assert client.get(
            f"/api/session/{sid}", headers={"Authorization": f"Bearer {host_token}"}
        ).status_code == 401
    finally:
        p = _jwt.decode(host_token, _get_jwt_secret(), algorithms=["HS256"])
        _revoked_jtis.pop(p["jti"], None)


def test_get_session_does_not_leak_tokens_or_invite_codes():
    sid, host_token = _start_with_token()

    inv = client.post(
        f"/api/session/{sid}/invite",
        json={"rating": "SFW"},
        headers={"Authorization": f"Bearer {host_token}"},
    )
    assert inv.status_code == 200

    resp = client.get(f"/api/session/{sid}", headers={"Authorization": f"Bearer {host_token}"})
    assert resp.status_code == 200
    session = resp.json()["session"]

    leaked = _SECRET_KEYS & session.keys()
    assert not leaked, f"GET /{{session_id}} leaked secret fields: {leaked}"

    body_str = str(session)
    assert host_token not in body_str, "host_token value must not appear anywhere in the public response"


def test_get_session_still_exposes_gameplay_fields():
    """機密フィールドの除外が過剰になっていないこと（initiative等は引き続き見える）の回帰確認。"""
    sid, host_token = _start_with_token()

    resp = client.get(f"/api/session/{sid}", headers={"Authorization": f"Bearer {host_token}"})
    session = resp.json()["session"]
    assert "initiative" in session
    assert "name_map" in session


def test_get_session_excludes_gm_only_and_internal_fields():
    """8.27対策: blacklist方式（host_token等5フィールドのみ除外）からallowlist方式に
    変更したこと自体の回帰確認。npc_state（require_keeper保護の/npc/{id}/stateが
    「GM専用情報」と明記しているのと同じデータ）・player_knowledge・rules/scene
    （private ruleset本文が入りうる）・char_game_sheets・skill_pool/skill_values・
    guest_chars等、frontendが実際に使っていない/GM専用のフィールドは
    GET /{session_id} のレスポンスに一切含まれないこと。
    """
    sid, host_token = _start_with_token()

    resp = client.get(f"/api/session/{sid}", headers={"Authorization": f"Bearer {host_token}"})
    session = resp.json()["session"]

    must_not_leak = {
        "npc_state", "player_knowledge", "rules", "scene",
        "char_game_sheets", "skill_pool", "skill_values",
        "guest_chars", "guest_char_ratings", "runtime_stats", "counters",
        "expelled_char_fingerprints", "circuit_broken",
        "daily_gen_count", "daily_gen_date", "backend", "char_backends",
    }
    leaked = must_not_leak & session.keys()
    assert not leaked, f"GET /{{session_id}} leaked GM-only/internal fields: {leaked}"


def test_autosave_serialization_still_keeps_tokens_for_restore():
    """`_session_for_json`（autosave用）は引き続きhost_token等を保持すること
    （復元に必要なため、公開用の除外を適用してはいけない）。"""
    from def_kari.api.routes.session import _session_for_json, _sessions

    sid = "_redaction_autosave_test"
    _sessions[sid] = {
        "id": sid,
        "host_token": "secret_host_token_value",
        "invite_codes": {"SFW-ABC-123": {"rating": "SFW", "used": False}},
        "initiative": [],
    }
    try:
        serialized = _session_for_json(_sessions[sid])
        assert serialized.get("host_token") == "secret_host_token_value"
        assert "SFW-ABC-123" in serialized.get("invite_codes", {})
    finally:
        _sessions.pop(sid, None)


def test_get_session_returns_only_callers_own_game_sheet_id():
    """再読み込みで復帰したプレイヤーが自分のキャラシートを読み込み直せるよう、本人のキャラの
    シートIDだけを返す。他人の対応（char_game_sheets全体）は引き続き返さない（2026-11-08）。"""
    from def_kari.api.routes.session import _sessions, issue_player_jwt

    sid, host_token = _start_with_token()
    sess = _sessions[sid]
    sess["char_game_sheets"] = {"char_a": "sheet_a", "char_b": "sheet_b"}
    tok_a = issue_player_jwt(sid, "player", "char_a")
    sess["players"][tok_a] = "char_a"

    resp = client.get(f"/api/session/{sid}", headers={"Authorization": f"Bearer {tok_a}"})
    body = resp.json()
    assert body["my_game_sheet_id"] == "sheet_a"
    assert "char_game_sheets" not in body["session"]
    assert "sheet_b" not in resp.text

    host_body = client.get(f"/api/session/{sid}", headers={"Authorization": f"Bearer {host_token}"}).json()
    assert "my_game_sheet_id" not in host_body


def test_get_session_returns_participants_snapshot_with_connection_state():
    """再読み込みしたタブが参加者の一覧と接続状況を復元できること（2026-11-08）。

    キーパーのタブは、この一覧で「接続中のプレイヤーが自分で振るキャラ」を決める。以前は
    イベントでしか一覧が作られず、再読み込みの後は空になり、プレイヤーのキャラの判定まで
    振って判定が二重になっていた。トークンと game_sheet_id（8.27）は返さない。
    """
    from def_kari.api.routes.session import _sessions, issue_player_jwt

    sid, host_token = _start_with_token()
    sess = _sessions[sid]
    tok_a = issue_player_jwt(sid, "player", "char_a")
    tok_b = issue_player_jwt(sid, "player", "char_b")
    sess["players"][tok_a] = "char_a"
    sess["players"][tok_b] = "char_b"
    sess["token_to_participant"] = {tok_a: "char_a", tok_b: "char_b"}
    sess["joined_participants"] = [
        {"character_id": "char_a", "participant_id": "char_a", "display_name": "A",
         "role": "player", "claimed_char_id": "", "game_sheet_id": "sheet_a"},
        {"character_id": "char_b", "participant_id": "char_b", "display_name": "B",
         "role": "player", "claimed_char_id": "", "game_sheet_id": "sheet_b"},
    ]
    sess["ws_connections"] = {tok_a: object()}  # A だけ接続中

    resp = client.get(f"/api/session/{sid}", headers={"Authorization": f"Bearer {host_token}"})
    body = resp.json()
    by_id = {p["participant_id"]: p for p in body["participants"]}
    assert by_id["char_a"]["connected"] is True
    assert by_id["char_b"]["connected"] is False
    assert by_id["char_a"]["character_id"] == "char_a"
    assert "game_sheet_id" not in by_id["char_a"]
    assert "sheet_a" not in resp.text and "sheet_b" not in resp.text
    assert tok_a not in resp.text and tok_b not in resp.text
