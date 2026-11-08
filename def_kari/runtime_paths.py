"""実行中に書き込むデータの置き場所（テストで実データを汚さないための切り替え口）。

DEF のデータはパッケージからの相対パス（リポジトリ直下の `data/`）にある。テストはセッションを
作るたびに自動保存・持ち込みキャラ・設定・会話の履歴・ログを書くため、以前は pytest を流す
だけで、本物の `data/private/session_autosave`（1回で200件超）や `data/mvp_settings.json`
（DEF の設定そのもの）を書き換えていた。さらに自動保存の復元は import 時に走るので、テストの
プロセスが本物の自動保存（data/private の中身）を読み込んでいた（2026-11-08、全体レビューの
指摘をきっかけに、写したコピーで pytest を流して確認）。

環境変数 `DEF_ISOLATED_DATA_DIR` があるときだけ、実行中に書き込むデータをその下に置く。
リポジトリ直下の conftest.py が、どのモジュールよりも先に一時ディレクトリを設定する。
普段の起動（環境変数なし）では、従来どおりリポジトリ直下の `data/` を使う。
読み取り専用の同梱データ（キャラクター・ルール・プロファイル等）は対象外。
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def writable_data_dir() -> Path:
    """実行中に書き込むデータの根（通常はリポジトリ直下の data/）。"""
    isolated = os.environ.get("DEF_ISOLATED_DATA_DIR")
    return Path(isolated) if isolated else REPO_DATA_DIR
