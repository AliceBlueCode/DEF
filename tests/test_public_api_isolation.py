"""公開用アプリ（def_kari.api.public_main.public_app）が意図した範囲だけを外部公開していることの検証。

背景: /api/session 以外の全ルーター（settings/chat/tts/novel/t2i/thought/trpg/characters）が
無認証のままFastAPIアプリ全体としてCloudflare Tunnel経由で外部公開されうる問題が見つかった
（外部QAレビュー指摘、2026-08-02）。対策として、session機能＋画像/音声の読み取り専用配信だけを
含む軽量アプリ public_app を新設し、Tunnelにはこちらだけを晒す設計にした
（DEF_kari_マルチプレイ設計書_内部用.md §7「非session系API公開範囲の制御」参照）。

このテストは「将来誰かがうっかり public_main.py に settings.router 等を追加してしまう」
ヒューマンエラーを機械的に検知するための安全網。allowlistテストが最重要で、新しい
ルーターが public_app に追加された際、許可リストに無ければ即座に失敗する。
"""

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from def_kari.api.public_main import public_app

client = TestClient(public_app)

# 公開してよいパスプレフィックス（これ以外が現れたらテスト失敗）
_ALLOWED_PREFIXES = (
    "/api/session",
    "/api/characters",  # characters_public のみマウントされている前提（下のテストで別途検証）
    "/api/t2i",         # t2i_public のみ
    "/api/tts",         # tts_public のみ
    "/api/health",
    "/openapi.json",
    "/docs",
    "/redoc",
)


def _iter_included_paths():
    """public_app に登録された全パスを prefix込みで列挙する（include_router経由の
    _IncludedRouter は original_router.routes がprefix適用前のパスしか持たないため、
    include_context.prefix と結合する）。"""
    for route in public_app.routes:
        if isinstance(route, APIRoute):
            yield route.path
        elif hasattr(route, "include_context"):
            prefix = route.include_context.prefix
            for sub in route.original_router.routes:
                yield prefix + getattr(sub, "path", "")
        else:
            yield getattr(route, "path", "")


def test_allowlist_no_path_outside_allowed_prefixes():
    """public_app の全パスが許可プレフィックスの範囲内であること。"""
    all_paths = list(_iter_included_paths())
    assert all_paths, "public_app にルートが1件も登録されていない（設定ミスの可能性）"
    offenders = [p for p in all_paths if not p.startswith(_ALLOWED_PREFIXES)]
    assert not offenders, f"許可外のパスが public_app に混入している: {offenders}"


def test_dangerous_routers_not_included():
    """settings/chat/novel/thought/trpg ルーターが public_app に一切含まれていないこと。"""
    included_modules = set()
    for route in public_app.routes:
        if hasattr(route, "original_router"):
            for sub in route.original_router.routes:
                included_modules.add(getattr(sub, "endpoint", None).__module__ if getattr(sub, "endpoint", None) else "")
    dangerous_modules = {
        "def_kari.api.routes.settings",
        "def_kari.api.routes.chat",
        "def_kari.api.routes.novel",
        "def_kari.api.routes.thought",
        "def_kari.api.routes.trpg",
        "def_kari.api.routes.characters",  # フル機能版（characters_publicではない）
        "def_kari.api.routes.t2i",  # フル機能版（t2i_publicではない、生成エンドポイント持ち）
        "def_kari.api.routes.tts",  # フル機能版（tts_publicではない、生成エンドポイント持ち）
    }
    leaked = included_modules & dangerous_modules
    assert not leaked, f"危険なルーターのモジュールが public_app に含まれている: {leaked}"


def test_settings_api_keys_not_reachable():
    """APIキー読み書きエンドポイントが到達不能（404）であること。"""
    assert client.get("/api/settings/api-keys").status_code == 404
    assert client.post("/api/settings/api-keys/anthropic", json={"api_key": "x"}).status_code == 404
    assert client.delete("/api/settings/api-keys/anthropic").status_code == 404


def test_settings_backend_control_not_reachable():
    """バックエンド起動・停止・ディレクトリブラウズが到達不能（404）であること。"""
    assert client.get("/api/settings/launch-backend").status_code == 404
    assert client.get("/api/settings/stop-backend").status_code == 404
    assert client.get("/api/settings/browse-dir").status_code == 404


def test_characters_private_endpoints_not_reachable():
    """キャラクター一覧・詳細・raw-profile・アップロード/生成が到達不能（404）であること。

    icon/standing の配信のみ許可（characters_public）。
    """
    assert client.get("/api/characters/").status_code == 404
    assert client.get("/api/characters/foo").status_code == 404
    assert client.get("/api/characters/foo/raw-profile").status_code == 404
    assert client.post("/api/characters/foo/icon/generate", json={}).status_code == 404


def test_characters_icon_and_standing_reachable():
    """アイコン・立ち絵の画像配信は到達可能であること（存在しないIDでも404ではなく200+error body）。"""
    r_icon = client.get("/api/characters/nonexistent/icon")
    r_standing = client.get("/api/characters/nonexistent/standing")
    assert r_icon.status_code == 200
    assert r_standing.status_code == 200


def test_t2i_generation_not_reachable_but_image_delivery_is():
    """T2I生成（POST /）は到達不能、画像配信（GET /image/{filename}）は到達可能であること。"""
    assert client.post("/api/t2i/", json={"prompt": "x"}).status_code == 404
    assert client.get("/api/t2i/debug").status_code == 404
    assert client.get("/api/t2i/image/nonexistent.png").status_code == 200


def test_tts_generation_not_reachable_but_audio_delivery_is():
    """TTS生成（POST /・/save・/test）は到達不能、音声配信（GET /audio/{filename}）は到達可能であること。"""
    assert client.post("/api/tts/", json={"text": "x", "character_id": "y"}).status_code == 404
    assert client.post("/api/tts/save").status_code == 404
    assert client.get("/api/tts/audio/nonexistent.wav").status_code == 200


def test_trpg_dice_not_reachable():
    """無認証の /api/trpg/dice は到達不能であること（セッション連動版は /api/session/{id}/dice に分離済み）。"""
    assert client.post("/api/trpg/dice", json={"notation": "1d100"}).status_code == 404
    assert client.get("/api/trpg/rulebooks").status_code == 404


def test_chat_novel_thought_not_reachable():
    """chat/novel/thought は完全に到達不能であること。"""
    assert client.post("/api/chat/", json={}).status_code == 404
    assert client.get("/api/novel/").status_code == 404
    assert client.get("/api/thought/").status_code == 404


def test_session_join_flow_reachable():
    """参加フローの主要エンドポイントは到達可能であること（session.router 丸ごとマウント）。"""
    assert client.post("/api/session/available-slots", json={"invite_code": "SFW-AAA-111"}).status_code in (200, 404)
    # 404の場合は「セッションが見つからない」というアプリケーションロジックの404であり、
    # ルーティング不在の404ではないことを separately に確認する
    resp = client.post("/api/session/available-slots", json={"invite_code": "SFW-AAA-111"})
    assert resp.json() != {"detail": "Not Found"}


def test_health_reachable():
    assert client.get("/api/health").status_code == 200


def test_full_app_still_has_all_routers():
    """回帰確認: main.py（フル機能アプリ）側は従来どおり全ルーターにアクセスできること。"""
    from def_kari.api.main import app
    full_client = TestClient(app)
    assert full_client.get("/api/settings/api-keys").status_code == 200
    assert full_client.get("/api/characters/").status_code == 200
