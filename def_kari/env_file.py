"""リポジトリ直下の `.env` を環境変数に読み込む。

起動の入口（`def_kari/api/main.py`。`dual_run.py`・`public_main.py` も最初にこれを読む）の**いちばん最初**、
def_kari のほかのモジュールを import する前に呼ぶ。import のときに環境変数を読むモジュール（バックエンドの
場所・URL、TRPG のプラグインの場所など）が、`.env` の値を見られるようにするため。

以前は main.py の後ろの方（ルートを import した後）で読んでいた。そのため、ルートの import のときに
自動保存のセッションを復元する処理が TRPG のルールシステムの登録を始めてしまい、`TRPG_PLUGIN_PATHS` が
まだ空のままプラグインを0件で読み込み済みにしていた（2026-11-15、手元のプラグインが画面に出ないことで
気づいた）。

- シェルなどで既に設定されている値は上書きしない（`setdefault`。以前と同じ）。
- `#` で始まる行と空の行は読み飛ばす。値の前後の空白は取る。引用符は外さない（以前と同じ）。
- 先頭の BOM は無視する。
- 環境変数 `DEF_SKIP_DOTENV=1` のときは読まない。テストは開発機の `.env` を読まず、CI（`.env` が無い）と
  同じ条件で流す（リポジトリ直下の conftest.py が設定する）。
"""

import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env_file(path: Path = ENV_PATH) -> list[str]:
    """`path` の設定を環境変数に入れる。入れた（まだ無かった）設定の名前を返す。"""
    if os.environ.get("DEF_SKIP_DOTENV") == "1" or not path.is_file():
        return []
    added = []
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                if k and k not in os.environ:
                    os.environ[k] = v.strip()
                    added.append(k)
    return added
