"""pytest 全体の設定（リポジトリ直下。def_kari/ と tests/ のどちらのテストより先に読まれる）。

テスト中に書き込むデータ（自動保存・持ち込みキャラ・設定・会話の履歴・ログ）を、一時ディレクトリへ
向ける。以前は pytest を流すだけで、本物の data/private/session_autosave（1回で200件超）や
DEF の設定ファイル data/mvp_settings.json を書き換え、自動保存の復元（import 時）で本物の
自動保存を読み込んでいた（2026-11-08）。置き場所の切り替えは def_kari.runtime_paths を参照。

モジュールの import 時にパスが決まるため、def_kari をどこからも import する前の、ここで設定する。
"""

import os
import shutil
import tempfile

_ISOLATED = tempfile.mkdtemp(prefix="def_pytest_data_")
os.environ["DEF_ISOLATED_DATA_DIR"] = _ISOLATED


def pytest_sessionfinish(session, exitstatus):
    # ログのファイル（def.log・audit.log）が開いたままだと、Windows では消せずに残る
    import logging
    logging.shutdown()
    shutil.rmtree(_ISOLATED, ignore_errors=True)
