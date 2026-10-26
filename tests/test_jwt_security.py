"""verify_jwt が不正なトークンを拒否することの回帰テスト。

JWTライブラリ（python-jose → PyJWT）を入れ替えても検証の強度が落ちていないことを
保証するため、トークンはライブラリを使わずHMACで直接組み立てる。テスト自体が
入れ替え対象のライブラリに依存していると、ライブラリ側の欠陥をテストが見逃すため。
"""

import base64
import hashlib
import hmac
import json
import time

import pytest


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_token(payload: dict, secret: str, alg: str = "HS256") -> str:
    header = {"alg": alg, "typ": "JWT"}
    signing_input = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(payload).encode())}"
    if alg == "none":
        return signing_input + "."
    digest = {"HS256": hashlib.sha256, "HS512": hashlib.sha512}[alg]
    sig = hmac.new(secret.encode(), signing_input.encode(), digest).digest()
    return f"{signing_input}.{_b64(sig)}"


def _payload(**overrides) -> dict:
    payload = {
        "session_id": "sess-jwt-sec",
        "role": "player",
        "jti": "jti-jwt-sec",
        "exp": int(time.time()) + 3600,
    }
    payload.update(overrides)
    return payload


def test_handcrafted_valid_token_is_accepted():
    """前提確認: 手組みのトークン自体が正しい形式であること（以降の拒否テストの対照）。"""
    from def_kari.api.routes.session import verify_jwt, _get_jwt_secret
    payload = verify_jwt(_make_token(_payload(), _get_jwt_secret()))
    assert payload["session_id"] == "sess-jwt-sec"
    assert payload["role"] == "player"


def test_expired_token_is_rejected():
    from def_kari.api.routes.session import verify_jwt, _get_jwt_secret
    from def_kari.api.routes.session_auth import _JWTError
    token = _make_token(_payload(exp=int(time.time()) - 60), _get_jwt_secret())
    with pytest.raises(_JWTError):
        verify_jwt(token)


def test_token_signed_with_other_secret_is_rejected():
    from def_kari.api.routes.session import verify_jwt
    from def_kari.api.routes.session_auth import _JWTError
    token = _make_token(_payload(), "attacker-chosen-secret-" + "x" * 40)
    with pytest.raises(_JWTError):
        verify_jwt(token)


def test_alg_none_token_is_rejected():
    """署名なし（alg=none）のトークンで任意のpayloadを通せないこと。"""
    from def_kari.api.routes.session import verify_jwt
    from def_kari.api.routes.session_auth import _JWTError
    token = _make_token(_payload(role="host"), "", alg="none")
    with pytest.raises(_JWTError):
        verify_jwt(token)


def test_tampered_payload_is_rejected():
    """正規の署名を流用してpayloadだけ書き換えた（player→hostへの権限昇格）トークン。"""
    from def_kari.api.routes.session import verify_jwt, _get_jwt_secret
    from def_kari.api.routes.session_auth import _JWTError
    header_b64, _, sig_b64 = _make_token(_payload(), _get_jwt_secret()).split(".")
    forged_payload_b64 = _b64(json.dumps(_payload(role="host")).encode())
    with pytest.raises(_JWTError):
        verify_jwt(f"{header_b64}.{forged_payload_b64}.{sig_b64}")


def test_algorithm_other_than_hs256_is_rejected():
    """正しい秘密鍵で署名されていても、HS256以外のアルゴリズムは受け付けない
    （アルゴリズムをHS256に固定していることの確認）。"""
    from def_kari.api.routes.session import verify_jwt, _get_jwt_secret
    from def_kari.api.routes.session_auth import _JWTError
    token = _make_token(_payload(), _get_jwt_secret(), alg="HS512")
    with pytest.raises(_JWTError):
        verify_jwt(token)
