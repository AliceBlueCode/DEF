"""バックエンド自動起動の.pidファイルガード（_try_claim_pid_slot / _write_pid /
_read_pid）のテスト。

従来は「存在確認→生存確認→新規プロセス起動→.pid書き込み」を別々のステップで
行っており、(1) ほぼ同時に2箇所から呼ばれるとTOCTOUレースで二重起動しうる、
(2) 死んだプロセスの.pidファイルが残ったままOSが同じPID番号を無関係な別
プロセスに再利用すると誤って「生存している」と判定してしまう、という2つの
構造的な弱点を抱えていた（2026-08-16、TODO.md「起動直後のバックエンド多重起動」対応）。

2026-08-17追記: 最初の修正では排他新規作成→呼び出し元がサブプロセス起動後に
書き込む設計だったため、その間ファイルが一瞬「存在するが空」の状態になり、
別スレッドがそれを「壊れたファイル」と誤認して横取りしてしまう競合がCIの
並行性テストで実際に発覚した（Linux CIランナーでは20スレッド中11〜13個が
獲得に成功してしまっていた）。獲得直後に呼び出し元自身のPID＋時刻を仮の値と
して即座に書き込む設計に変更し、空ファイルのまま置かれる時間を無くした。
"""

import os
import threading
import time

import pytest

from def_kari import backends


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(backends, "_DATA_DIR", str(tmp_path))


def test_claim_fresh_slot_succeeds():
    """.pidファイルが存在しない場合、排他新規作成で起動権を獲得できること。
    獲得直後に自分自身のPID＋時刻が仮の値として書き込まれていること。"""
    assert backends._try_claim_pid_slot("testbackend") is True
    pid_path = backends._pid_path("testbackend")
    assert os.path.exists(pid_path)
    assert backends._read_pid(pid_path) == str(os.getpid())


def test_claim_defers_to_live_recent_process():
    """生存中かつ起動から間もないPIDが記録されている場合、道を譲る（False）こと。"""
    pid_path = backends._pid_path("testbackend")
    with open(pid_path, "w") as f:
        f.write(f"{os.getpid()}:{time.time()}")
    assert backends._try_claim_pid_slot("testbackend") is False


def test_claim_reclaims_when_pid_is_dead():
    """記録されたPIDのプロセスが既に存在しない場合、古いファイルを消して
    起動権を再獲得できること。"""
    pid_path = backends._pid_path("testbackend")
    # 実在しないと考えられる非常に大きいPID番号を使う
    with open(pid_path, "w") as f:
        f.write(f"999999:{time.time()}")
    assert backends._try_claim_pid_slot("testbackend") is True


def test_claim_reclaims_when_timestamp_is_stale():
    """PIDが生存していても、記録された起動時刻がSTALE_AFTER_SECを超えていれば
    再利用されたPIDの可能性を疑い、道を譲らず起動権を奪い直すこと
    （誤検知でいつまでも起動できなくなることの回避）。"""
    pid_path = backends._pid_path("testbackend")
    old_timestamp = time.time() - backends._STALE_AFTER_SEC - 60
    with open(pid_path, "w") as f:
        f.write(f"{os.getpid()}:{old_timestamp}")
    assert backends._try_claim_pid_slot("testbackend") is True


def test_claim_reclaims_legacy_format_without_timestamp():
    """本対応以前の裸PIDのみの.pidファイル（コロン無し）は、起動時刻を
    検証できないため常に古いものとして扱い、起動権を再獲得できること。"""
    pid_path = backends._pid_path("testbackend")
    with open(pid_path, "w") as f:
        f.write(str(os.getpid()))
    assert backends._try_claim_pid_slot("testbackend") is True


def test_claim_reclaims_corrupted_file():
    """壊れた内容（数値でない等）の.pidファイルも古いものとして扱い、
    起動権を再獲得できること。"""
    pid_path = backends._pid_path("testbackend")
    with open(pid_path, "w") as f:
        f.write("not-a-pid")
    assert backends._try_claim_pid_slot("testbackend") is True


def test_claim_is_exclusive_under_concurrency():
    """ほぼ同時に多数のスレッドから呼んでも、起動権を獲得できるのは1つだけ
    であること（TOCTOUレースの解消。os.open(O_CREAT|O_EXCL)のOSレベルの
    原子性に依拠する部分の回帰確認）。"""
    results: list[bool] = [False] * 20
    barrier = threading.Barrier(20)

    def _worker(i: int) -> None:
        barrier.wait()  # 全スレッドを可能な限り同時にスタートさせる
        results[i] = backends._try_claim_pid_slot("testbackend")

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 1


def test_write_pid_overwrites_placeholder():
    """_try_claim_pid_slotが書く仮のPID（呼び出し元自身）を、
    _write_pidで実際のサブプロセスPIDに上書きできること。"""
    assert backends._try_claim_pid_slot("testbackend") is True
    backends._write_pid("testbackend", 424242)
    pid_path = backends._pid_path("testbackend")
    assert backends._read_pid(pid_path) == "424242"


def test_read_pid_new_format():
    pid_path = backends._pid_path("testbackend")
    with open(pid_path, "w") as f:
        f.write("12345:1723800000.5")
    assert backends._read_pid(pid_path) == "12345"


def test_read_pid_legacy_format():
    """コロンを含まない旧形式（本対応以前に書かれた.pidファイル）も
    そのままPIDとして読めること。"""
    pid_path = backends._pid_path("testbackend")
    with open(pid_path, "w") as f:
        f.write("12345")
    assert backends._read_pid(pid_path) == "12345"
