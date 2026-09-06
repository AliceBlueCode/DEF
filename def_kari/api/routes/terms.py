"""利用規約(TERMS.md)の読み取り専用配信。

ローカル専用アプリ(main.py)・公開アプリ(public_main.py)の両方にマウントする
(ゲスト向けオンボーディング画面のTERMS同意ステップが公開ポート経由で読む必要があるため)。
内容の二重管理を避けるため、リポジトリルートのTERMS.mdをそのまま読み込んで返す
(フロント側にコピーを持たない)。
"""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()
_log = logging.getLogger("def.terms")

_TERMS_PATH = (Path(__file__).parent.parent.parent.parent / "TERMS.md").resolve()


@router.get("")
def get_terms():
    # TERMS.mdはゲスト参加フローの必須ステップ(TermsPanel.tsxの同意チェックボックスが
    # ゲート)上にあるため、読み込み失敗を無防備な例外(素の500)のまま放置すると、
    # 原因(ファイル欠落・権限エラー等)が運用側から見えないまま全ゲストの参加が
    # 詰まる。他の場所と同じ`_log`パターンで診断ログを残し、クライアントには
    # 明確なエラーメッセージを返す（2026-09-06、リリース前レビューで発覚）。
    try:
        content = _TERMS_PATH.read_text(encoding="utf-8")
    except OSError as e:
        _log.error("[terms] TERMS.mdの読み込みに失敗: %s", e)
        raise HTTPException(500, "Failed to load TERMS.md") from e
    return {"content": content}
