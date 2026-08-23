"""GET /api/terms のテスト。

ローカル専用アプリ(main.py)・公開アプリ(public_main.py)の両方から到達可能であること、
返却内容がリポジトリルートのTERMS.mdと完全一致すること（内容の二重管理を避ける設計の
ため、ハードコードした固定文字列との比較ではなく実ファイルと突き合わせる）を確認する。
"""

from pathlib import Path

from fastapi.testclient import TestClient

from def_kari.api.main import app
from def_kari.api.public_main import public_app

client = TestClient(app)
public_client = TestClient(public_app)

_TERMS_PATH = Path(__file__).parent.parent / "TERMS.md"


def test_terms_matches_disk_file_on_local_app():
    resp = client.get("/api/terms")
    assert resp.status_code == 200
    assert resp.json()["content"] == _TERMS_PATH.read_text(encoding="utf-8")


def test_terms_matches_disk_file_on_public_app():
    resp = public_client.get("/api/terms")
    assert resp.status_code == 200
    assert resp.json()["content"] == _TERMS_PATH.read_text(encoding="utf-8")


def test_terms_contains_explicit_consent_wording():
    """黙示同意(「参加操作を行った時点で...みなす」)から明示チェックボックス同意への
    文言修正が反映されていること（2026-08-23、TERMS同意オンボーディング画面の実装に
    あわせて第1条を修正）。"""
    content = client.get("/api/terms").json()["content"]
    assert "同意チェックボックスにチェックを入れ" in content
