"""require_host/require_player/require_keeperのsession_idスコープ検証（BOLA/IDOR対策）のテスト。

以前は3つのDependencyがJWTペイロードの`role`だけをチェックし、そのJWTが
どのsession_id用に発行されたかを検証していなかった。`POST /start`は無認証
なので、誰でも自分専用のダミーセッションでrole:hostのJWTを取得し、そのトークンで
他人の任意のsession_idに対して全操作を実行できていた
（DEF_kari_セキュリティ設計書_内部用.md 8.2「BOLA/IDOR」参照）。
"""

from fastapi.testclient import TestClient
from def_kari.api.main import app

client = TestClient(app)


def _start_session():
    """セッションを新規作成して (session_id, host_token) を返す。"""
    resp = client.post("/api/session/start", json={"character_ids": []})
    assert resp.status_code == 200
    d = resp.json()
    return d["session_id"], d["host_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_host_token_from_other_session_rejected():
    """require_host: セッションAのhost_tokenでセッションBの/inviteは叩けないこと。"""
    _sid_a, token_a = _start_session()
    sid_b, _token_b = _start_session()

    resp = client.post(f"/api/session/{sid_b}/invite", json={"rating": "SFW"}, headers=_auth(token_a))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Token session mismatch"


def test_host_token_on_own_session_still_works():
    """回帰確認: 自分自身のセッションに対しては引き続き成功すること。"""
    sid, token = _start_session()
    resp = client.post(f"/api/session/{sid}/invite", json={"rating": "SFW"}, headers=_auth(token))
    assert resp.status_code == 200
    assert "invite_code" in resp.json()


def test_player_token_from_other_session_rejected():
    """require_player: セッションAのplayer_tokenでセッションBの/diceは叩けないこと。"""
    from def_kari.api.routes.session import issue_player_jwt

    sid_a, _token_a = _start_session()
    sid_b, _token_b = _start_session()
    player_token_a = issue_player_jwt(sid_a, "player", "char_a")

    resp = client.post(f"/api/session/{sid_b}/dice", json={"notation": "1d100"}, headers=_auth(player_token_a))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Token session mismatch"


def test_keeper_token_from_other_session_rejected():
    """require_keeper: セッションAのhost_token（host/gm扱い）でセッションBの/retakeは叩けないこと。"""
    _sid_a, token_a = _start_session()
    sid_b, _token_b = _start_session()

    resp = client.post(f"/api/session/{sid_b}/retake", headers=_auth(token_a))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Token session mismatch"


def test_dummy_session_host_token_cannot_hijack_real_session():
    """`/start`が無認証であることを悪用し、自分専用のダミーセッションで得たhost_tokenを
    使って他人の実セッションを操作できてしまう、8.2で説明された具体的な攻撃シナリオの再現。"""
    real_sid, _real_host_token = _start_session()
    _dummy_sid, attacker_token = _start_session()  # 攻撃者が勝手に作った自分専用セッション

    resp = client.post(f"/api/session/{real_sid}/end", headers=_auth(attacker_token))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Token session mismatch"


def test_vote_commit_requires_keeper_not_just_player():
    """8.19: vote/commitはrequire_keeperで保護され、一般プレイヤーのトークンでは
    呼べないこと（以前はrequire_playerだったため、一般プレイヤー1人がセッション内の
    全人間キャラの投票結果を単独で確定できてしまっていた）。"""
    from def_kari.api.routes.session import issue_player_jwt

    sid, _host_token = _start_session()
    player_token = issue_player_jwt(sid, "player", "char_a")

    resp = client.post(f"/api/session/{sid}/vote/commit", json={"keeper_vote": True}, headers=_auth(player_token))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Keeper role required"
