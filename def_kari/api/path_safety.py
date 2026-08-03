"""パストラバーサル対策の共通ユーティリティ。

`str(path).startswith(str(base))` によるディレクトリ境界チェックは、
`base` と同一プレフィックスを持つ兄弟ディレクトリ（例: `assets` に対する
`assets_private`）を誤って許可してしまうアンチパターン。
`Path.is_relative_to()`（Python 3.9+）を使い、パス階層としての包含判定に
統一する。

正規化（`resolve()`）は呼び出し側の責務とする。この関数は「既に
正規化済みのパス」を受け取る前提で、二重正規化による責務の曖昧さを避ける。
"""

from pathlib import Path


def is_safe_path(candidate: Path, base: Path) -> bool:
    """`candidate`（resolve()済み）が`base`（resolve()済み）配下にあるかを判定する。"""
    try:
        return candidate.is_relative_to(base)
    except ValueError:
        return False
