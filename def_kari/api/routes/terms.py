"""利用規約(TERMS.md)の読み取り専用配信。

ローカル専用アプリ(main.py)・公開アプリ(public_main.py)の両方にマウントする
(ゲスト向けオンボーディング画面のTERMS同意ステップが公開ポート経由で読む必要があるため)。
内容の二重管理を避けるため、リポジトリルートのTERMS.mdをそのまま読み込んで返す
(フロント側にコピーを持たない)。
"""

from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

_TERMS_PATH = (Path(__file__).parent.parent.parent.parent / "TERMS.md").resolve()


@router.get("")
def get_terms():
    return {"content": _TERMS_PATH.read_text(encoding="utf-8")}
