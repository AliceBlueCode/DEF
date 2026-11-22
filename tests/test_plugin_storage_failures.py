"""プラグインの置き場（def_kari/trpg/plugin_storage.py）の、失敗した時の振る舞い。

2026-11-23 にカバレッジを測ったら、書く途中で失敗した時の後始末、Windows で置き換えがはじかれた時の
試し直し、置き場の外を指すリンクを断る所が、一度も動いていなかった。
"""
import json
import os
from unittest.mock import patch

import pytest

from def_kari.trpg import plugin_storage as ps
from def_kari.trpg.plugin_storage import PluginStorage, StorageError


def _tmp_files(st, kind):
    d = st._root() / kind
    return [p.name for p in d.iterdir() if p.name.endswith(".tmp")] if d.is_dir() else []


def test_a_failed_write_leaves_the_old_content_and_no_temporary_file():
    st = PluginStorage("fail_plugin")
    st.write_json("campaigns", "c1", data={"revision": 1})
    with patch.object(ps.json, "dump", side_effect=OSError("disk full")), pytest.raises(OSError):
        st.write_json("campaigns", "c1", data={"revision": 2})
    assert st.read_json("campaigns", "c1") == {"revision": 1}
    assert _tmp_files(st, "campaigns") == []


def test_a_refused_replace_is_tried_again(monkeypatch):
    """Windows では、ほかのプロセスが開いていると置き換えがはじかれる。少し待って試し直す。"""
    st = PluginStorage("fail_plugin")
    real = os.replace
    calls = []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) < 3:
            raise PermissionError("in use")
        real(src, dst)
    monkeypatch.setattr(ps.os, "replace", flaky)
    waits = []
    monkeypatch.setattr(ps.time, "sleep", waits.append)
    st.write_json("campaigns", "c2", data={"revision": 1})
    assert st.read_json("campaigns", "c2") == {"revision": 1}
    assert len(calls) == 3 and waits == [ps._REPLACE_WAIT_SEC * 1, ps._REPLACE_WAIT_SEC * 2]


def test_a_replace_refused_every_time_fails_and_cleans_up(monkeypatch):
    st = PluginStorage("fail_plugin")
    st.write_json("campaigns", "c3", data={"revision": 1})
    calls = []

    def refuse(src, dst):
        calls.append(dst)
        raise PermissionError("in use")
    monkeypatch.setattr(ps.os, "replace", refuse)
    monkeypatch.setattr(ps.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        st.write_json("campaigns", "c3", data={"revision": 2})
    assert len(calls) == ps._REPLACE_RETRIES
    monkeypatch.undo()
    assert st.read_json("campaigns", "c3") == {"revision": 1}
    assert _tmp_files(st, "campaigns") == []


def test_reading_what_is_not_there():
    st = PluginStorage("fail_plugin")
    assert st.read_json("campaigns", "none") is None
    assert st.read_prev_json("campaigns", "none") is None
    assert st.list_ids("never_written") == []
    with pytest.raises(StorageError):
        st.list_ids("../up")


def test_lines_that_are_not_objects_are_skipped():
    st = PluginStorage("fail_plugin")
    st.append_line("logs", "c4", record={"seq": 1})
    with open(st._path("logs", ("c4",), ".jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps([1, 2]) + "\n" + json.dumps("text") + "\n")
    st.append_line("logs", "c4", record={"seq": 2})
    assert [r["seq"] for r in st.read_lines("logs", "c4")] == [1, 2]


def _link_dir(link, target) -> bool:
    """フォルダへのリンクを作る。Windows は権限の要らないジャンクションで。作れない環境なら False。"""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


def test_a_link_out_of_the_storage_is_refused(tmp_path):
    """ID は許可リストで確かめるが、置き場の中のフォルダが外へのリンクなら、パスは外を指す。それも断る。"""
    st = PluginStorage("link_plugin")
    st._root().mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    if not _link_dir(st._root() / "campaigns", outside):
        pytest.skip("cannot make a directory link here")
    with pytest.raises(StorageError, match="outside the storage"):
        st.write_json("campaigns", "c1", data={"x": 1})
    with pytest.raises(StorageError, match="outside the storage"):
        st.read_json("campaigns", "c1")
    assert list(outside.iterdir()) == []
