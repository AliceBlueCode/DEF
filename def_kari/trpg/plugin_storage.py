"""プラグインが書き込む置き場（マルチルールブック基盤 B-006・B-007）。

プラグインは、自分でパスを組み立てたりファイルを直接開いたりせず、この口を通して書き読みする。
口が ID を確かめ（B-012 と同じ許可リスト）、置き場の内側にだけパスを作る。

- 置き場: 書き込み用のデータの置き場（`runtime_paths.writable_data_dir()`）の
  `private/plugin_data/<plugin_id>/<kind>/`。git で管理しない（data/private の下）。
- ファイルの名前: ID を `.` でつないだもの ＋ 拡張子（`.json` か `.jsonl`）。例: `("c1",)` → `c1.json`、
  `("c1", "s1", "archive")` → `c1.s1.archive.json`。
- `write_json` は、一時ファイルに書いてディスクへの書き込みを確定させてから置き換える（落ちても直前の
  正しい中身が残る）。置き換える前の中身は `<名前>.prev.json` に控える（S-366）。
- `append_line` は、1行に1件の JSON を足し、ディスクへの書き込みを確定させる。`read_lines` は、最後の
  壊れた1行を読み飛ばす（追記の途中で落ちた場合。S-371）。
- Windows では、ほかのプロセスがファイルを開いていると置き換えが失敗することがあるので、少し待って
  試し直す。
"""

import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from def_kari.runtime_paths import writable_data_dir
from def_kari.trpg.resources import is_safe_id

_log = logging.getLogger("def.trpg")

_REPLACE_RETRIES = 5
_REPLACE_WAIT_SEC = 0.05


class StorageError(ValueError):
    """置き場の口に渡した ID が正しくない、または置き場の外を指した。"""


class PluginStorage:
    def __init__(self, plugin_id: str):
        if not is_safe_id(plugin_id):
            raise StorageError(f"invalid plugin id: {plugin_id!r}")
        self.plugin_id = plugin_id

    # ── パス ──
    def _root(self) -> Path:
        return writable_data_dir() / "private" / "plugin_data" / self.plugin_id

    def _path(self, kind: str, ids: tuple, suffix: str) -> Path:
        if not is_safe_id(kind):
            raise StorageError(f"invalid kind: {kind!r}")
        if not ids or not all(isinstance(i, str) and is_safe_id(i) for i in ids):
            raise StorageError(f"invalid id: {ids!r}")
        root = self._root().resolve()
        path = (root / kind / (".".join(ids) + suffix)).resolve()
        # ID は許可リストで確かめてあるが、置き場の中のフォルダが外へのリンク（ジャンクション）なら、resolve した
        # パスは外を指す（tests/test_plugin_storage_failures.py）
        if not path.is_relative_to(root):
            raise StorageError(f"path outside the storage: {path}")
        return path

    # ── JSON（1ファイル1件） ──
    def read_json(self, kind: str, *ids: str) -> dict | None:
        """中身（dict）。無い・壊れている・いちばん外側が object でないなら None。"""
        return self._read_object(self._path(kind, ids, ".json"))

    def read_prev_json(self, kind: str, *ids: str) -> dict | None:
        """1つ前に書いた中身（控え）。"""
        return self._read_object(self._path(kind, ids, ".prev.json"))

    def write_json(self, kind: str, *ids: str, data: dict) -> None:
        if not isinstance(data, dict):
            raise StorageError("data must be a JSON object")
        path = self._path(kind, ids, ".json")
        prev = self._path(kind, ids, ".prev.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            if path.exists():
                shutil.copy2(path, prev)
            self._replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def exists(self, kind: str, *ids: str) -> bool:
        return self._path(kind, ids, ".json").is_file()

    def list_ids(self, kind: str) -> list[str]:
        """その種類の `.json` の名前（拡張子を除く。控えと一時ファイルは除く）。"""
        if not is_safe_id(kind):
            raise StorageError(f"invalid kind: {kind!r}")
        d = self._root() / kind
        if not d.is_dir():
            return []
        return sorted(p.name[:-len(".json")] for p in d.iterdir()
                      if p.is_file() and p.name.endswith(".json") and not p.name.endswith(".prev.json"))

    # ── 1行に1件の JSON（追記だけ） ──
    def append_line(self, kind: str, *ids: str, record: dict) -> None:
        if not isinstance(record, dict):
            raise StorageError("record must be a JSON object")
        path = self._path(kind, ids, ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        # 追記の途中で落ちて、最後の行が改行で終わっていなければ、先に改行を足す。足さないと、新しい行が
        # 壊れた行とつながり、新しい行まで「壊れた最後の行」として読み飛ばされる（S-371）
        if path.is_file() and path.stat().st_size > 0:
            with open(path, "rb") as f:
                f.seek(-1, os.SEEK_END)
                if f.read(1) != b"\n":
                    line = "\n" + line
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def read_lines(self, kind: str, *ids: str) -> list[dict]:
        """全部の行。最後の壊れた1行は読み飛ばす。途中の壊れた行も読み飛ばし、警告を残す。

        バイトのまま改行で分けて、1行ずつ decode する。日本語の文字の途中で切れた行（追記の途中で落ちた）が
        あると、ファイル全体を文字として読む形では UnicodeDecodeError になり、その後のすべての行が読めなくなって
        いた（レビュー 2026-11-22 の🟡A-1）。decode できない行も、壊れた行として読み飛ばす。
        """
        path = self._path(kind, ids, ".jsonl")
        if not path.is_file():
            return []
        raw = path.read_bytes().split(b"\n")
        if raw and raw[-1] == b"":
            raw.pop()
        out = []
        for i, line in enumerate(raw):
            try:
                rec = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                if i != len(raw) - 1:
                    _log.warning("[plugin %s] %s: broken line %d skipped", self.plugin_id, path.name, i + 1)
                continue
            if isinstance(rec, dict):
                out.append(rec)
        return out

    # ── 内部 ──
    @staticmethod
    def _read_object(path: Path) -> dict | None:
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _replace(src: str, dst: Path) -> None:
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(_REPLACE_WAIT_SEC * (attempt + 1))
