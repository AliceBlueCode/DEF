"""E2Eを、手元で動いているDEFとは別の環境で流す（CIと同じ条件）。

なぜ別環境か:
- E2Eは設定（切断タイムアウト・投票強制賛成・LLMバックエンド等）を書き換え、セッションを作る。
  DEFのデータはパッケージからの相対パス（`data/`）なので、同じ作業ツリーで流すと実データが荒れる。
- 手元のDEF（8511/8512/3000）と本物のTGW（5000）がポートを使っている。

やること:
1. gitが管理しているファイル（未コミットの変更・未追跡の新規ファイルを含み、.gitignore の対象は
   含まない）だけを、一時ディレクトリへ写す。`.env`・`data/private` の私物は写らない（CIと同じ）。
   `frontend/node_modules` はジャンクション（Windows）またはシンボリックリンクで共有する。
2. 別のポートで、モックLLM・DEF（dual_run）・Viteの開発サーバーを立てる。
3. 指定したシナリオ（frontend/e2e/*.js）を順に流し、終わったら全部止める。

シナリオの途中でバックエンドを再起動する（サーバーの再起動からの復元を確かめる）ため、
制御用の窓口 `POST http://127.0.0.1:5199/restart-backend` を開く。シナリオからは
helpers.js の restartBackend() で呼ぶ。止めて起動し直し、/api/health が返るまで待ってから応答する。

使い方（リポジトリの直下で）:
    venv/Scripts/python scripts/e2e_local.py generation_failure vote_flow
    venv/Scripts/python scripts/e2e_local.py --build guest_onboarding   # frontend/dist が要るもの
    venv/Scripts/python scripts/e2e_local.py --keep ...                 # 失敗の調査用に環境を残す
シナリオ名は frontend/e2e/<名前>.js の <名前>。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MOCK_PORT = 5100
LOCAL_PORT = 8611
PUBLIC_PORT = 8612
DEV_PORT = 3100
CONTROL_PORT = 5199


def _git_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=REPO, check=True, capture_output=True,
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def _copy_tree(dest: Path) -> None:
    for rel in _git_files():
        src = REPO / rel
        if not src.is_file():  # 削除済み（まだコミットしていない）
            continue
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    nm_src = REPO / "frontend" / "node_modules"
    nm_dst = dest / "frontend" / "node_modules"
    if not nm_src.is_dir():
        sys.exit("frontend/node_modules がありません。先に frontend で npm ci を実行してください。")
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(nm_dst), str(nm_src)], check=True, capture_output=True)
    else:
        nm_dst.symlink_to(nm_src, target_is_directory=True)


def _wait(url: str, name: str, timeout: float = 60) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"{name} が起動しませんでした（{url}）")


def _start(cmd: list[str], cwd: Path, log: Path, env: dict) -> subprocess.Popen:
    f = open(log, "w", encoding="utf-8")
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    return subprocess.Popen(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, env=env, **kwargs)


def _stop(p: subprocess.Popen) -> None:
    if p.poll() is not None:
        return
    if os.name == "nt":  # npm → node のように子を持つので、プロセスツリーごと止める
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        import signal
        os.killpg(p.pid, signal.SIGTERM)
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            p.kill()
        else:  # グループの先頭だけでなく、子（node 等）まで止める
            import signal
            os.killpg(p.pid, signal.SIGKILL)


class _Backend:
    """DEF（dual_run）のプロセス。シナリオの求めで止めて起動し直せるようにする。"""

    def __init__(self, work: Path, logs: Path, env: dict):
        self.work, self.logs, self.env = work, logs, env
        self.proc: subprocess.Popen | None = None
        self.starts = 0

    def start(self) -> None:
        self.starts += 1
        log = self.logs / ("backend.log" if self.starts == 1 else f"backend_{self.starts}.log")
        self.proc = _start([sys.executable, "-m", "def_kari.api.dual_run", "--local-port", str(LOCAL_PORT),
                            "--public-port", str(PUBLIC_PORT), "--no-trust-cloudflare-tunnel"],
                           self.work, log, self.env)
        _wait(f"http://127.0.0.1:{LOCAL_PORT}/api/health", "DEF（ローカルポート）")
        _wait(f"http://127.0.0.1:{PUBLIC_PORT}/api/health", "DEF（公開ポート）")

    def stop(self) -> None:
        if self.proc:
            _stop(self.proc)

    def restart(self) -> None:
        self.stop()
        self.start()


def _serve_control(backend: _Backend):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401
            pass

        def do_POST(self):
            if self.path != "/restart-backend":
                self.send_response(404)
                self.end_headers()
                return
            try:
                with lock:
                    print("[e2e_local] バックエンドを再起動します", flush=True)
                    backend.restart()
                self.send_response(200)
            except Exception as e:  # 起動しなかった等
                print(f"[e2e_local] 再起動に失敗: {e}", flush=True)
                self.send_response(500)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", CONTROL_PORT), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows のコンソール（cp932）でも落ちないように
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scenarios", nargs="+", help="frontend/e2e/<名前>.js の <名前>")
    ap.add_argument("--build", action="store_true", help="先に frontend で npm run build する（公開ポートの画面を使うシナリオ用）")
    ap.add_argument("--keep", action="store_true", help="終わった後も環境（一時ディレクトリ）を消さない")
    args = ap.parse_args()

    for name in args.scenarios:
        if not (REPO / "frontend" / "e2e" / f"{name}.js").is_file():
            sys.exit(f"シナリオがありません: frontend/e2e/{name}.js")

    # 置き場所は E2E_WORK_ROOT で変えられる（CI では失敗時のログを拾うため runner.temp を使う）
    work = Path(tempfile.mkdtemp(prefix="def_e2e_", dir=os.environ.get("E2E_WORK_ROOT") or None))
    print(f"[e2e_local] 環境: {work}")
    _copy_tree(work)
    logs = work / "_logs"
    logs.mkdir()

    npm = "npm.cmd" if os.name == "nt" else "npm"
    env = dict(os.environ)
    env.pop("DEF_BEHIND_CLOUDFLARE_TUNNEL", None)
    # 守り: シェルに入っている本物のAPIキーを渡さない。E2Eはモックだけを使う想定で、
    # 何かの経路で外部のLLM（課金あり）を呼んでしまわないようにする。
    for key in [k for k in env if k.endswith("_API_KEY") or k.endswith("_TOKEN")]:
        env.pop(key)
    env.update({
        # 依存の事前バンドルを本物の node_modules/.vite に書かない（vite.config.ts の cacheDir）
        "DEF_VITE_CACHE_DIR": str(work / ".vite_cache"),
        "TEXTGEN_WEBUI_URL": f"http://127.0.0.1:{MOCK_PORT}/v1",
        "DEF_DEV_PORT": str(DEV_PORT),
        "DEF_API_TARGET": f"http://127.0.0.1:{LOCAL_PORT}",
        "E2E_BASE_URL": f"http://localhost:{DEV_PORT}",
        "E2E_GUEST_BASE_URL": f"http://127.0.0.1:{PUBLIC_PORT}",
        "E2E_WS_URL": f"ws://127.0.0.1:{LOCAL_PORT}",
        "MOCK_LLM_URL": f"http://127.0.0.1:{MOCK_PORT}",
        "E2E_CONTROL_URL": f"http://127.0.0.1:{CONTROL_PORT}",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",  # [LLM] 等の print がログに即座に出るように（調査用）
    })

    if args.build:
        subprocess.run([npm, "run", "build"], cwd=work / "frontend", env=env, check=True)

    procs: list[subprocess.Popen] = []
    results: list[tuple[str, int]] = []
    backend = _Backend(work, logs, env)
    control = None
    try:
        procs.append(_start([sys.executable, "-I", str(work / "scripts" / "e2e_mock_llm.py"), "--port", str(MOCK_PORT)],
                            work, logs / "mock_llm.log", env))
        procs.append(_start([npm, "run", "dev"], work / "frontend", logs / "frontend.log", env))
        _wait(f"http://127.0.0.1:{MOCK_PORT}/v1/models", "モックLLM")
        backend.start()
        _wait(f"http://localhost:{DEV_PORT}", "Vite")
        control = _serve_control(backend)

        for name in args.scenarios:
            print(f"\n[e2e_local] ===== {name} =====", flush=True)
            rc = subprocess.run(["node", f"e2e/{name}.js"], cwd=work / "frontend", env=env).returncode
            results.append((name, rc))
    finally:
        if control:
            control.shutdown()
        backend.stop()
        for p in reversed(procs):
            _stop(p)

    print("\n[e2e_local] 結果:")
    for name, rc in results:
        print(f"  {'OK  ' if rc == 0 else 'FAIL'} {name}")
    failed = [n for n, rc in results if rc != 0] or ([] if len(results) == len(args.scenarios) else ["(起動前に中断)"])
    if failed:
        print(f"\n[e2e_local] ログ: {logs}")
        for log in sorted(logs.glob("*.log")):
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
            print(f"--- {log.name}（末尾）---")
            print("\n".join(tail))
    if args.keep or failed:
        print(f"[e2e_local] 環境は残しています: {work}")
        print("[e2e_local] 消すときは、先に frontend/node_modules（本物へのリンク）だけを外すこと:")
        if os.name == "nt":
            print(f'            rmdir "{work / "frontend" / "node_modules"}"  （/s を付けない）')
        else:
            print(f'            rm "{work / "frontend" / "node_modules"}"  （-r を付けない）')
    else:
        # ジャンクションの先（本物の node_modules）を消さないよう、先にリンクだけ外す
        nm = work / "frontend" / "node_modules"
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "rmdir", str(nm)], capture_output=True)
        else:
            nm.unlink(missing_ok=True)
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
