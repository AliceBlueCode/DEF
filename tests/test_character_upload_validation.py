"""キャラクター画像アップロード（icon/standing）のContent-Type検証（8.14対策）のテスト。

以前はファイルサイズ上限のみでファイル種別を検証していなかった。PILが開けなければ
例外で落ちるため実害は限定的だったが、防御としては薄かった（DEF_kari_セキュリティ
設計書_内部用.md 8.14参照）。Content-Typeヘッダーによる早期フィルタと、実体検証
（Image.open(...).convert("RGB")）の多層防御になっていることを確認する。
"""

import io

from fastapi.testclient import TestClient
from def_kari.api.main import app
from def_kari.api.routes.characters_common import _CHAR_DIRS

client = TestClient(app)


def _tiny_png_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), color="red").save(buf, "PNG")
    return buf.getvalue()


def test_upload_icon_accepts_valid_png():
    char_id = "_upload_test_valid_png"
    try:
        resp = client.post(
            f"/api/characters/{char_id}/icon",
            files={"file": ("icon.png", _tiny_png_bytes(), "image/png")},
        )
        assert resp.status_code == 200
        assert (_CHAR_DIRS[0] / char_id / "icon.png").exists()
    finally:
        import shutil
        shutil.rmtree(_CHAR_DIRS[0] / char_id, ignore_errors=True)


def test_upload_icon_rejects_non_image_content_type():
    """Content-Typeがimage/*でなければ415で即座に拒否されること（PILを呼ぶ前に弾く）。"""
    char_id = "_upload_test_bad_content_type"
    try:
        resp = client.post(
            f"/api/characters/{char_id}/icon",
            files={"file": ("evil.txt", b"not an image at all", "text/plain")},
        )
        assert resp.status_code == 415
        assert not (_CHAR_DIRS[0] / char_id / "icon.png").exists()
    finally:
        import shutil
        shutil.rmtree(_CHAR_DIRS[0] / char_id, ignore_errors=True)


def test_upload_icon_spoofed_content_type_still_rejected_by_pil():
    """Content-Typeをimage/pngと偽装しても、中身が画像でなければPIL側で例外になり
    保存されないこと（Content-Type検証だけに頼らない多層防御の確認）。
    TestClientはデフォルトでハンドルされない例外をそのまま再送出するため
    （raise_server_exceptions=True、本番環境ではFastAPIが500化する）、ここでは
    PIL.UnidentifiedImageErrorが実際に飛ぶこと自体を確認する。
    """
    from PIL import UnidentifiedImageError
    import pytest

    char_id = "_upload_test_spoofed"
    try:
        with pytest.raises(UnidentifiedImageError):
            client.post(
                f"/api/characters/{char_id}/icon",
                files={"file": ("fake.png", b"this is not really a png file", "image/png")},
            )
        assert not (_CHAR_DIRS[0] / char_id / "icon.png").exists()
    finally:
        import shutil
        shutil.rmtree(_CHAR_DIRS[0] / char_id, ignore_errors=True)
