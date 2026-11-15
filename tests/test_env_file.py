""".env の読み込み（def_kari/env_file.py）と、読み込む順番。

2026-11-15: main.py が .env をルートの import の後に読んでいたため、自動保存の復元が TRPG のルールシステムの
登録を先に始め、`TRPG_PLUGIN_PATHS` が空のままプラグインを0件で読み込み済みにしていた。.env を
def_kari のほかのモジュールより前に読むことを、ここで固定する。
"""

import ast
from pathlib import Path

from def_kari import env_file

ROOT = Path(__file__).resolve().parent.parent


def test_reads_settings_without_overriding(monkeypatch, tmp_path):
    p = tmp_path / ".env"
    p.write_text("﻿# comment\n\nDEF_T_A=1\nDEF_T_B = two words \nDEF_T_C=already\nnot a setting\n", encoding="utf-8")
    monkeypatch.delenv("DEF_SKIP_DOTENV", raising=False)
    monkeypatch.delenv("DEF_T_A", raising=False)
    monkeypatch.delenv("DEF_T_B", raising=False)
    monkeypatch.setenv("DEF_T_C", "shell")
    added = env_file.load_env_file(p)
    import os
    assert sorted(added) == ["DEF_T_A", "DEF_T_B"]   # BOM があっても最初の名前を読める
    assert os.environ["DEF_T_A"] == "1" and os.environ["DEF_T_B"] == "two words"
    assert os.environ["DEF_T_C"] == "shell"           # シェルの値を上書きしない
    for k in ("DEF_T_A", "DEF_T_B"):
        monkeypatch.delenv(k)


def test_skip_flag_and_missing_file(monkeypatch, tmp_path):
    p = tmp_path / ".env"
    p.write_text("DEF_T_SKIPPED=1\n", encoding="utf-8")
    monkeypatch.setenv("DEF_SKIP_DOTENV", "1")
    assert env_file.load_env_file(p) == []
    monkeypatch.delenv("DEF_SKIP_DOTENV")
    assert env_file.load_env_file(tmp_path / "nothing") == []


def test_tests_do_not_read_the_dev_env():
    import os
    assert os.environ.get("DEF_SKIP_DOTENV") == "1"


def test_main_reads_env_before_any_other_def_kari_module():
    """main.py で、.env を読む行が、def_kari のほかのモジュールのどの import よりも前にあること。"""
    tree = ast.parse((ROOT / "def_kari" / "api" / "main.py").read_text(encoding="utf-8"))
    order = []
    for node in tree.body:  # モジュールの直下だけ（関数の中の遅い import は対象外）
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("def_kari"):
            order.append(("import", node.module, node.lineno))
        elif isinstance(node, ast.Import) and any(a.name.startswith("def_kari") for a in node.names):
            order.append(("import", node.names[0].name, node.lineno))
        elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
              and getattr(node.value.func, "id", "") == "_load_env_file"):
            order.append(("load", "", node.lineno))
    assert order[0][:2] == ("import", "def_kari.env_file"), order[:3]
    assert order[1][0] == "load", order[:3]


def test_entry_points_import_main_first():
    """dual_run.py・public_main.py は、def_kari のモジュールのうち main を（tunnel_state を除いて）最初に読む。"""
    for name in ("dual_run.py", "public_main.py"):
        tree = ast.parse((ROOT / "def_kari" / "api" / name).read_text(encoding="utf-8"))
        mods = [n.module for n in tree.body if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("def_kari")]
        mods = [m for m in mods if m != "def_kari.api"]  # tunnel_state（設定もほかのモジュールも読まない）
        assert mods[0] == "def_kari.api.main", (name, mods[:3])
