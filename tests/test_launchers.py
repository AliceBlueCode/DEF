"""起動の手順（Windows のバッチ）の改行と中身。

2026-11-22: start_def_public.bat の改行が LF だったため、cmd が `goto wait_backend` のラベルを見つけられず、
画面（DEF-React）の窓を開く前にバッチが終わっていた。`.gitattributes` で CRLF にし、ここで確かめる。
"""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LAUNCHERS = ["start_def.bat", "start_def_public.bat"]


def _tracked_batches() -> list[str]:
    out = subprocess.run(["git", "ls-files", "*.bat", "*.cmd"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return [p for p in out.stdout.splitlines() if p]


def test_gitattributes_keeps_batches_crlf():
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.bat text eol=crlf" in text and "*.cmd text eol=crlf" in text


@pytest.mark.parametrize("name", LAUNCHERS)
def test_launchers_are_crlf_only(name):
    data = (ROOT / name).read_bytes()
    assert b"\r\n" in data
    assert data.count(b"\n") == data.count(b"\r\n"), f"{name} has LF-only lines; cmd cannot find its labels"


def test_every_tracked_batch_is_crlf():
    for name in _tracked_batches():
        data = (ROOT / name).read_bytes()
        assert data.count(b"\n") == data.count(b"\r\n"), name


@pytest.mark.parametrize("name", LAUNCHERS)
def test_launchers_check_commands_log_steps_and_bound_the_health_wait(name):
    text = (ROOT / name).read_text(encoding="ascii")
    assert "for %%C in (curl timeout netstat findstr npm)" in text
    assert "def_launcher.log" in text and ":log" in text
    assert "curl -sf -m 5 http://127.0.0.1:8511/api/health" in text
    # 使うラベルがすべてある
    for label in ("wait_backend", "start_frontend", "log"):
        assert f"\n:{label}\r\n" in text or f"\r\n:{label}\r\n" in text, label
