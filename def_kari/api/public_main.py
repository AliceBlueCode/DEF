"""DEF(kari) 公開用（Cloudflare Tunnel等でリモート公開する）軽量FastAPIアプリ。

`session.router`（オンラインセッション機能、JWT認証済み）と、キャラクター画像・
T2I画像・TTS音声の読み取り専用配信ルーターのみをマウントする。
`settings`/`chat`/`novel`/`t2i`(生成)/`tts`(生成)/`thought`/`trpg`/`characters`(フル機能)
等、ホスト管理・ローカル専用機能は意図的に一切importしない（誤って追加しないよう、
フル機能アプリ `main.py` とは別ファイルに分離している。allowlistテストで到達可能な
パスを検証する: `tests/test_public_api_isolation.py`）。

起動は `def_kari/api/dual_run.py` から行う。単体で `uvicorn def_kari.api.public_main:public_app`
として起動することも可能だが、その場合 `_sessions` 等のシングルトンは `main.py` 側の
プロセスとは別インスタンスになり整合性が壊れるため、本番運用では必ず dual_run 経由で
同一プロセス内に同居させること。
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from def_kari.api.main import (
    SessionBodySizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from def_kari import __version__
from def_kari.api.routes import session
from def_kari.api.routes.characters_public import router as characters_public_router
from def_kari.api.routes.t2i_public import router as t2i_public_router
from def_kari.api.routes.tts_public import router as tts_public_router

_FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"


@asynccontextmanager
async def _public_lifespan(app: FastAPI):
    import asyncio as _asyncio
    from def_kari.api.routes.session import set_main_loop as _set_session_loop
    # main.py 側のlifespanと同じ呼び出し。同一プロセス・同一イベントループなので
    # 起動順に関わらず冪等（asyncio.get_running_loop() は常に同じループを返す）。
    _set_session_loop(_asyncio.get_running_loop())
    yield


public_app = FastAPI(
    title="DEF(kari) Public API",
    version=__version__,
    description="DEF(kari) — オンラインセッション公開用エンドポイントのみ",
    lifespan=_public_lifespan,
    # 8.13対策: 攻撃対象の全エンドポイント一覧・リクエスト/レスポンススキーマを
    # 認証なしで閲覧できる状態になっていた（攻撃の下調べを容易にするだけで実害は
    # 無いが、無料で塞げる項目のため対応）。main.py（ローカル専用）側は開発時の
    # 利便性のため引き続き有効のまま。
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

public_app.add_middleware(SessionBodySizeLimitMiddleware)
public_app.add_middleware(SecurityHeadersMiddleware)
public_app.add_middleware(
    CORSMiddleware,
    # Tunnel URLは起動のたびに変わりうるため事前に許可リストを組めない。
    # JWTはAuthorizationヘッダーで送るためCookie不要（allow_credentials=Falseで両立可能）。
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

public_app.include_router(session.router, prefix="/api/session", tags=["session"])
public_app.include_router(characters_public_router, prefix="/api/characters", tags=["characters-public"])
public_app.include_router(t2i_public_router, prefix="/api/t2i", tags=["t2i-public"])
public_app.include_router(tts_public_router, prefix="/api/tts", tags=["tts-public"])


@public_app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


# ゲストがCloudflare Tunnel経由でDEFのUI自体を読み込めるよう、本番ビルド成果物
# （frontend/dist、npm run buildで生成）を配信する。未ビルドの環境（新規clone・CI等）
# ではdist/自体が存在しないため、その場合は静かにスキップする（StaticFilesは存在しない
# ディレクトリを渡すと起動時に例外を出すため）。
#
# "/"にStaticFiles(html=True)を丸ごとマウントする案は一度試して破棄した:
# Starletteはそのマウントを「/配下の全パスに対する経路の1つ」として扱うため、
# 他のAPIパスへの本来405になるべき誤メソッドリクエスト等まで巻き込んで挙動が変わり、
# 複数の到達不能性テストが壊れた（2026-08-10）。frontend/dist/内の実ファイル
# （index.html・favicon.svg・icons.svg・assets/配下）だけをそれぞれ狭く公開する。
if _FRONTEND_DIST.is_dir():
    public_app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="frontend-assets")

    @public_app.get("/", include_in_schema=False)
    def _serve_frontend_index():
        return FileResponse(_FRONTEND_DIST / "index.html")

    @public_app.get("/favicon.svg", include_in_schema=False)
    def _serve_frontend_favicon():
        return FileResponse(_FRONTEND_DIST / "favicon.svg")

    @public_app.get("/icons.svg", include_in_schema=False)
    def _serve_frontend_icons():
        return FileResponse(_FRONTEND_DIST / "icons.svg")
