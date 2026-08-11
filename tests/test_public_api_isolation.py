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

from unittest.mock import patch

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from def_kari.api.public_main import public_app

client = TestClient(public_app)

# 公開してよいパスプレフィックス（これ以外が現れたらテスト失敗）
# /openapi.json・/docs・/redocは8.13対策でdocs_url等をNoneにして無効化したため
# 登録されず、このリストにも含めない（test_docs_endpoints_not_reachableで別途確認）。
_ALLOWED_PREFIXES = (
    "/api/session",
    "/api/characters",  # characters_public のみマウントされている前提（下のテストで別途検証）
    "/api/t2i",         # t2i_public のみ
    "/api/tts",         # tts_public のみ
    "/api/health",
    "/assets",          # frontend/dist/assets のビルド済みJS/CSS（下記参照）
)

# "/" のような短い文字列を_ALLOWED_PREFIXESにprefixマッチで加えると、全パスが
# 何にでもstartswith("/")してしまい許可リストが事実上無効化される。フロントエンド
# ビルド成果物（index.html・favicon.svg・icons.svg）配信用の個別ルートは
# 完全一致でのみ許可する（2026-08-10、Cloudflare Tunnel動作確認でゲストがUIを
# 読み込めない不具合を発見・追加。当初"/"にStaticFiles(html=True)を丸ごとマウント
# する案を試したが、他のAPIパスの404/405判定まで巻き込んで壊れたため、
# individual routesに絞り直した）。
_ALLOWED_EXACT_PATHS = ("/", "/favicon.svg", "/icons.svg")


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
    offenders = [
        p for p in all_paths
        if not p.startswith(_ALLOWED_PREFIXES) and p not in _ALLOWED_EXACT_PATHS
    ]
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


def test_characters_public_icon_excludes_private_dir(tmp_path):
    """8.18対策: characters_public.py（public_app、無認証）はdata/private/charactersを
    検索対象にしないこと。以前はcharacters_commonの_CHAR_DIRSをそのまま共有しており、
    character_idさえ分かればレーティングゲートを無視してprivate/NSFW画像を取得できた。
    """
    from def_kari.api.routes import characters_common

    private_dir = tmp_path / "private"
    public_dir = tmp_path / "public"
    private_dir.mkdir()
    public_dir.mkdir()

    char_id = "secret_char_001"
    char_dir = private_dir / char_id
    char_dir.mkdir()
    (char_dir / "icon.png").write_bytes(b"fake-png-bytes")

    with patch.object(characters_common, "_PUBLIC_CHAR_DIRS", [public_dir]), \
         patch.object(characters_common, "_CHAR_DIRS", [public_dir, private_dir]):
        # public_only=True（characters_public.py相当）: privateディレクトリは見えない
        assert characters_common.find_char_dir(char_id, public_only=True) is None
        # public_only=False（characters.py相当、ローカル専用）: 従来どおり見える
        assert characters_common.find_char_dir(char_id, public_only=False) == char_dir

        # HTTPレベルでも確認: public_appでは画像が見つからない
        resp = client.get(f"/api/characters/{char_id}/icon")
        assert resp.status_code == 200
        assert resp.json() == {"error": "Icon not found"}


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


def test_session_local_only_endpoints_not_reachable():
    """8.8対策: debug/saved/load（session.local_router）がpublic_appから機密情報を
    返さないこと。

    以前はsession.router丸ごとマウントに巻き込まれて公開されており、直近のセッションの
    LLM生応答（/debug）・保存済みセッションの全履歴（/load）を認証なしで読めていた。
    local_routerはpublic_appにマウントされていないため、これらのパスはGET /{session_id}
    （session.router側、GETのみ登録）のワイルドカードにフォールバックする。
    GET /{session_id}は参加者認証必須（require_participant、2026-08-11）になったため、
    単一セグメントのパス（/debug・/saved）はAuthorizationヘッダー必須の422で止まる
    （それ以前は200+{"error": "Session not found"}という無害なフォールバックだった。
    現在はさらに手前で遮断される）。複数セグメントのパス（/saved/{filename}）や
    GET以外のメソッド（POST /load）はどのパターンにもマッチせず404/405になる。
    いずれの場合も本来のdebug情報・セッション一覧・履歴は一切返らない。
    """
    r_debug = client.get("/api/session/debug")
    assert r_debug.status_code == 422  # Authorizationヘッダー必須（_last_session_debugの中身は漏れない）

    r_saved = client.get("/api/session/saved")
    assert r_saved.status_code == 422  # 同上（保存済みセッション一覧は漏れない）

    assert client.delete("/api/session/saved/nonexistent.json").status_code == 404
    assert client.post("/api/session/load", json={"filename": "nonexistent.json"}).status_code == 405


def test_session_rule_write_not_reachable_but_read_is():
    """8.3対策: PUT /rules/{rule_id}（無認証書き込み）はpublic_appから到達不能であること。
    GET /rules・GET /rules/{rule_id}（読み取り専用、ゲストのルール一覧表示に必要）は
    引き続き到達可能であること。

    以前はGET/PUTとも無認証のままsession.routerに残っており、rule_idの名前空間内なら
    誰でもdata/public/session_rules/{rule_id}.jsonを新規作成・上書きできた
    （全ユーザー共有のグローバルなルール定義ライブラリの汚染・改ざん）。
    """
    r_put = client.put("/api/session/rules/test_rule_id", json={"content": "{}"})
    assert r_put.status_code == 405  # GET /rules/{rule_id}と同じパスパターンだがPUTは未登録

    assert client.get("/api/session/rules").status_code == 200
    assert client.get("/api/session/rules/nonexistent").status_code == 200  # {"error": "..."}を返す通常の応答


def test_full_app_can_still_write_rules():
    """回帰確認: main.py側ではPUT /rules/{rule_id}が引き続き機能すること（ホストの
    ローカルUIでのセッションルール編集機能を壊していないか）。"""
    from def_kari.api.main import app
    from def_kari.api.routes.session import _RULE_DIRS
    full_client = TestClient(app)
    rule_id = "_isolation_test_rule"
    try:
        resp = full_client.put(f"/api/session/rules/{rule_id}", json={"content": f'{{"id": "{rule_id}"}}'})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
    finally:
        for d in _RULE_DIRS:
            (d / f"{rule_id}.json").unlink(missing_ok=True)


def test_session_rules_and_directives_exclude_private_over_public_app(tmp_path):
    """private session_rules / action_directives が public_app（無認証）から読めないこと。

    以前はGET /rules・/rules/{rule_id}・/action-directivesがdata/public・data/privateの
    両方を無差別にマージして返しており、招待コードで参加しただけの第三者・第三者一般が
    NSFW/私有のルールセット・アクションディレクティブのフルコンテンツを無認証で読めた
    （8.18のprivateキャラクター画像露出と同じ構造の穴）。session.routerはmain.pyと
    public_main.pyの両方に同一インスタンスがマウントされているため、request.app.state
    のフラグでポートを判別し、public_app経由の場合のみdata/private/を除外する。
    """
    from def_kari.api.routes import session as session_module

    public_dir = tmp_path / "public_rules"
    private_dir = tmp_path / "private_rules"
    public_dir.mkdir()
    private_dir.mkdir()
    (public_dir / "standard.json").write_text('{"id": "standard", "label": "Standard"}', encoding="utf-8")
    (private_dir / "nsfw_secret.json").write_text('{"id": "nsfw_secret", "label": "NSFW Secret"}', encoding="utf-8")

    public_dir_d = tmp_path / "public_directives"
    private_dir_d = tmp_path / "private_directives"
    public_dir_d.mkdir()
    private_dir_d.mkdir()
    (public_dir_d / "standard.json").write_text('{"id": "standard", "label": "Standard"}', encoding="utf-8")
    (private_dir_d / "nsfw_directive.json").write_text('{"id": "nsfw_directive", "label": "NSFW Directive"}', encoding="utf-8")

    with patch.object(session_module, "_RULE_DIRS", [public_dir, private_dir]), \
         patch.object(session_module, "_PUBLIC_RULE_DIRS", [public_dir]), \
         patch.object(session_module, "_DIRECTIVE_DIRS", [public_dir_d, private_dir_d]), \
         patch.object(session_module, "_PUBLIC_DIRECTIVE_DIRS", [public_dir_d]):

        # public_app（無認証・外部公開）: privateは一切見えない
        r_list = client.get("/api/session/rules")
        rule_ids = [r["id"] for r in r_list.json()["rules"]]
        assert "nsfw_secret" not in rule_ids
        assert "standard" in rule_ids

        r_detail_public = client.get("/api/session/rules/standard")
        assert "Standard" in r_detail_public.json()["content"]
        r_detail_private = client.get("/api/session/rules/nsfw_secret")
        assert r_detail_private.json() == {"error": "Rule 'nsfw_secret' not found"}

        r_directives = client.get("/api/session/action-directives")
        directive_ids = [d["id"] for d in r_directives.json()["directives"]]
        assert "nsfw_directive" not in directive_ids
        assert "standard" in directive_ids

        # main.py（ローカル専用・フル機能）: 従来どおりprivateも見える
        from def_kari.api.main import app
        full_client = TestClient(app)
        r_full = full_client.get("/api/session/rules")
        full_rule_ids = [r["id"] for r in r_full.json()["rules"]]
        assert "nsfw_secret" in full_rule_ids

        r_full_directives = full_client.get("/api/session/action-directives")
        full_directive_ids = [d["id"] for d in r_full_directives.json()["directives"]]
        assert "nsfw_directive" in full_directive_ids


def test_session_dead_code_endpoints_removed_everywhere():
    """8.8対策: フロント未使用だったhuman/judgment/allocate/judgment/rollは
    デッドコードとして削除済みであること（main.py側でも到達不能）。
    next（POST /api/session/next）も同様にルーティングは廃止したが、next_turn関数
    自体はAIターン自動進行の内部実装として_execute_ai_turnから直接呼ばれるため
    session.py内に残しており、他のテストで別途動作確認済み。

    /next・/humanは単一セグメントパスのため、他のGET /{session_id}ワイルドカードに
    フォールバックして405（POSTは許可されていない）になる。/judgment/*は複数セグメントの
    パスなのでどのパターンにもマッチせず404になる。挙動が違うのはFastAPIのルーティング
    仕様上の自然な結果で、どちらも元のロジックには到達しない。
    """
    from def_kari.api.main import app
    full_client = TestClient(app)
    assert full_client.post("/api/session/next", json={"session_id": "x"}).status_code == 405
    assert full_client.post("/api/session/human", json={"session_id": "x", "message": "hi"}).status_code == 405
    assert full_client.post("/api/session/x/judgment/allocate", json={"character_id": "y", "stat": "z"}).status_code == 404
    assert full_client.post("/api/session/x/judgment/roll", json={"character_id": "y", "stat": "z", "roll": 50}).status_code == 404


def test_session_join_flow_reachable():
    """参加フローの主要エンドポイントは到達可能であること（session.router 丸ごとマウント）。"""
    assert client.post("/api/session/available-slots", json={"invite_code": "SFW-AAA-111"}).status_code in (200, 404)
    # 404の場合は「セッションが見つからない」というアプリケーションロジックの404であり、
    # ルーティング不在の404ではないことを separately に確認する
    resp = client.post("/api/session/available-slots", json={"invite_code": "SFW-AAA-111"})
    assert resp.json() != {"detail": "Not Found"}


def test_health_reachable():
    assert client.get("/api/health").status_code == 200


def test_docs_endpoints_not_reachable():
    """8.13対策: /docs・/redoc・/openapi.jsonはpublic_appから到達不能であること。

    以前はFastAPIのデフォルトドキュメント機能が有効なままで、攻撃対象の全エンドポイント
    一覧・リクエスト/レスポンススキーマが認証なしで誰でも閲覧できた（攻撃の下調べを
    容易にする）。main.py（ローカル専用）側は開発時の利便性のため引き続き有効。
    """
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404

    from def_kari.api.main import app
    full_client = TestClient(app)
    assert full_client.get("/docs").status_code == 200


def test_full_app_still_has_all_routers():
    """回帰確認: main.py（フル機能アプリ）側は従来どおり全ルーターにアクセスできること。"""
    from def_kari.api.main import app
    full_client = TestClient(app)
    assert full_client.get("/api/settings/api-keys").status_code == 200
    assert full_client.get("/api/characters/").status_code == 200


def test_full_app_still_has_session_local_router():
    """回帰確認: main.py側ではsession.local_router（debug/saved/load）が引き続き
    到達可能であること（ローカル専用UI: DebugTab.tsx/SessionTab.tsxの機能を壊していないか）。"""
    from def_kari.api.main import app
    full_client = TestClient(app)
    assert full_client.get("/api/session/debug").status_code == 200
    assert full_client.get("/api/session/saved").status_code == 200
