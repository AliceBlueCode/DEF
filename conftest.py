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

# TestClient でアプリの起動の処理（lifespan）を通るテストが、開発機の本物のバックエンド（TGW・
# VOICEVOX・A1111 など）を起動しにいかないようにする（2026-11-14。def_kari/api/main.py の lifespan）。
os.environ["DEF_NO_BACKEND_AUTOSTART"] = "1"

# 開発機の .env を読まない（def_kari/env_file.py）。CI には .env が無いので、手元のテストも同じ条件にする。
# 以前は main.py を import したテストに、開発機の .env の一部（キャラのリポジトリの場所など）が混ざっていた。
os.environ["DEF_SKIP_DOTENV"] = "1"

# ルールブックは、DEF-Rulebook の形の固定の写しから読む（要求仕様 C-005・C-006。def_original は 2026-11-14 に
# DEF の本体から DEF-Rulebook へ移した）。開発機の .env に書いた本物のリポジトリは読まない。
_RULEBOOK_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "fixtures", "rulebook_repos", "def_rulebook")
os.environ["TRPG_RULEBOOK_REPO_PATHS"] = _RULEBOOK_FIXTURE
os.environ["TRPG_PLUGIN_PATHS"] = ""


def pytest_sessionfinish(session, exitstatus):
    # ログのファイル（def.log・audit.log）が開いたままだと、Windows では消せずに残る
    import logging
    logging.shutdown()
    shutil.rmtree(_ISOLATED, ignore_errors=True)
