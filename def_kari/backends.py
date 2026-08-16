"""バックエンド(TGW/VOICEVOX/A1111)の自動起動・状態管理"""

import os
import subprocess
import time

import requests

# --- TGW ---
TEXTGEN_WEBUI_DIR = os.environ.get("TEXTGEN_WEBUI_DIR", "")
TEXTGEN_WEBUI_URL = os.environ.get("TEXTGEN_WEBUI_URL", "http://127.0.0.1:5000/v1")

# --- VOICEVOX ---
VOICEVOX_DIR = os.environ.get("VOICEVOX_DIR", "")
VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")

# --- A1111 ---
A1111_DIR = os.environ.get("A1111_DIR", "")
A1111_URL = os.environ.get("A1111_URL", "http://localhost:7860")

# --- PIDファイル ---
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _pid_path(name: str) -> str:
    os.makedirs(_DATA_DIR, exist_ok=True)
    return os.path.join(_DATA_DIR, f"{name}.pid")


# 起動から十分な時間（どのバックエンドも通常この時間内に起動し終わる想定）が
# 経っても.pidファイルが残っている場合、記録されたPIDが別プロセスに再利用
# されている可能性を疑い、生存確認（os.kill(pid, 0)）だけでは信用しない
# （2026-08-16、TODO.md「起動直後のバックエンド多重起動」対応）。
_STALE_AFTER_SEC = 600.0


def _read_pid(pid_path: str) -> str:
    """.pidファイルからPID部分のみを取り出す。`_try_claim_pid_slot`が書き込む
    `{pid}:{起動時刻}`形式・本対応以前の裸PIDのみの形式のどちらも読める。"""
    with open(pid_path) as f:
        content = f.read().strip()
    return content.split(":", 1)[0]


def _try_claim_pid_slot(name: str) -> int | None:
    """バックエンド起動権を排他的に獲得する。

    従来は「.pidファイルの存在確認 → 生存確認 → 新規プロセス起動 → .pid書き込み」を
    別々のステップで行っており、(1) ほぼ同時に2箇所から呼ばれた場合に両方とも
    「起動していない」と判定して二重起動しうるTOCTOUレースと、(2) 死んだプロセスの
    .pidファイルが残ったまま、OSが同じPID番号を無関係な別プロセスに再利用すると
    `os.kill(pid, 0)`が誤って「生存している」と判定してしまう問題の、2つの構造的な
    弱点を抱えていた。

    `os.open(..., O_CREAT | O_EXCL)`はOSレベルで原子的な排他新規作成のため、
    ほぼ同時に呼ばれても片方だけが確実にfdを獲得できる（TOCTOU解消）。既に
    ファイルが存在する場合は生存確認に加えて経過時間もチェックし、
    `_STALE_AFTER_SEC`を超えていれば古いとみなして道を譲らず起動権を奪い直す
    （PID再利用の誤検知を無期限には信用しない）。

    戻り値: 起動権を獲得できればファイルディスクリプタ（呼び出し元が
    `os.write`→`os.close`する）、既に他プロセスが正当に起動中/起動済みとみなす
    場合はNone。
    """
    pid_path = _pid_path(name)
    try:
        return os.open(pid_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        pass

    is_stale = True
    try:
        with open(pid_path) as f:
            content = f.read().strip()
        parts = content.split(":", 1)
        old_pid = int(parts[0])
        launched_at = float(parts[1]) if len(parts) > 1 else 0.0
        is_alive = True
        try:
            os.kill(old_pid, 0)
        except (OSError, SystemError):
            is_alive = False
        is_stale = (not launched_at) or (time.time() - launched_at) > _STALE_AFTER_SEC
        if is_alive and not is_stale:
            return None  # 他プロセスが正当に起動中/起動済みとみなし道を譲る
    except (ValueError, OSError):
        pass  # 壊れた内容のファイル → 古いものとして扱う

    try:
        os.remove(pid_path)
    except OSError:
        pass
    try:
        return os.open(pid_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None  # 削除〜再作成の間に他プロセスが取得した（稀）


# ===== TGW =====

def is_tgw_running() -> bool:
    try:
        return requests.get(f"{TEXTGEN_WEBUI_URL}/models", timeout=5).status_code == 200
    except requests.RequestException:
        return False


def start_tgw() -> str | None:
    if not TEXTGEN_WEBUI_DIR:
        return "TEXTGEN_WEBUI_DIRが未設定です。.envファイルを確認してください。"
    if is_tgw_running():
        return None
    fd = _try_claim_pid_slot("tgw")
    if fd is None:
        return None
    conda_python = os.path.join(TEXTGEN_WEBUI_DIR, "installer_files", "env", "python.exe")
    server_py = os.path.join(TEXTGEN_WEBUI_DIR, "server.py")
    if not os.path.isfile(conda_python):
        os.close(fd)
        os.remove(_pid_path("tgw"))
        return f"TGWのPython実行ファイルが見つかりません: {conda_python}"
    if not os.path.isfile(server_py):
        os.close(fd)
        os.remove(_pid_path("tgw"))
        return f"TGWのserver.pyが見つかりません: {server_py}"
    try:
        _env = os.environ.copy()
        _env["PYTHONUTF8"] = "1"
        _env["PYTHONIOENCODING"] = "utf-8"
        _bat = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_start_tgw.bat")
        _cmd = [_bat]
        _flags_path = os.path.join(TEXTGEN_WEBUI_DIR, "user_data", "CMD_FLAGS.txt")
        if os.path.isfile(_flags_path):
            with open(_flags_path, encoding="utf-8") as _ff:
                for _line in _ff:
                    _line = _line.strip()
                    if _line and not _line.startswith("#"):
                        _cmd.extend(_line.split())
        print(f"[TGW] Starting with: {' '.join(_cmd)}")
        proc = subprocess.Popen(
            _cmd,
            cwd=TEXTGEN_WEBUI_DIR,
            env=_env,
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )
        os.write(fd, f"{proc.pid}:{time.time()}".encode())
        os.close(fd)
        return None
    except Exception as exc:
        os.close(fd)
        try:
            os.remove(_pid_path("tgw"))
        except OSError:
            pass
        return str(exc)


def stop_tgw() -> str | None:
    pid_path = _pid_path("tgw")
    if not os.path.exists(pid_path):
        return None
    try:
        pid = _read_pid(pid_path)
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, check=True)
        os.remove(pid_path)
        return None
    except Exception as exc:
        return str(exc)


# ===== VOICEVOX =====

def is_voicevox_running() -> bool:
    url = os.environ.get("VOICEVOX_URL", VOICEVOX_URL)
    try:
        return requests.get(f"{url}/version", timeout=2).status_code == 200
    except requests.RequestException:
        return False


def start_voicevox() -> str | None:
    vv_dir = os.environ.get("VOICEVOX_DIR", VOICEVOX_DIR)
    if not vv_dir:
        return "VOICEVOX_DIRが未設定です。バックエンド設定で場所を指定してください。"
    if is_voicevox_running():
        return None
    fd = _try_claim_pid_slot("voicevox")
    if fd is None:
        return None
    exe_path = os.path.join(vv_dir, "vv-engine", "run.exe")
    if not os.path.isfile(exe_path):
        exe_path = os.path.join(vv_dir, "VOICEVOX.exe")
    if not os.path.isfile(exe_path):
        os.close(fd)
        os.remove(_pid_path("voicevox"))
        return f"VOICEVOXが見つかりません: {vv_dir}"
    try:
        from def_kari.settings import load_settings as _ls
        _cpu_mode = _ls().get("tts_voicevox_cpu_mode", False)
        _args = [exe_path] if _cpu_mode else [exe_path, "--use_gpu"]
        proc = subprocess.Popen(
            _args,
            cwd=os.path.dirname(exe_path),
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )
        os.write(fd, f"{proc.pid}:{time.time()}".encode())
        os.close(fd)
        return None
    except Exception as exc:
        os.close(fd)
        try:
            os.remove(_pid_path("voicevox"))
        except OSError:
            pass
        return str(exc)


def stop_voicevox() -> str | None:
    pid_path = _pid_path("voicevox")
    if not os.path.exists(pid_path):
        return None
    try:
        pid = _read_pid(pid_path)
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, check=True)
        os.remove(pid_path)
        return None
    except Exception as exc:
        return str(exc)


# ===== A1111 =====

def is_a1111_running() -> bool:
    try:
        return requests.get(f"{A1111_URL}/sdapi/v1/sd-models", timeout=2).status_code == 200
    except requests.RequestException:
        return False


def start_a1111() -> str | None:
    if not A1111_DIR:
        return "A1111_DIRが未設定です。.envファイルを確認してください。"
    if is_a1111_running():
        return None
    fd = _try_claim_pid_slot("a1111")
    if fd is None:
        return None
    bat_path = os.path.join(A1111_DIR, "webui-user.bat")
    if not os.path.isfile(bat_path):
        os.close(fd)
        os.remove(_pid_path("a1111"))
        return f"webui-user.batが見つかりません: {bat_path}"
    env = os.environ.copy()
    env["NoDefaultCurrentDirectoryInExePath"] = "0"
    env["PATH"] = ".;" + env.get("PATH", "")
    try:
        proc = subprocess.Popen(
            ["cmd", "/k", "webui-user.bat"],
            cwd=A1111_DIR,
            env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )
        os.write(fd, f"{proc.pid}:{time.time()}".encode())
        os.close(fd)
        return None
    except Exception as exc:
        os.close(fd)
        try:
            os.remove(_pid_path("a1111"))
        except OSError:
            pass
        return str(exc)


def stop_a1111() -> str | None:
    pid_path = _pid_path("a1111")
    if not os.path.exists(pid_path):
        return None
    try:
        pid = _read_pid(pid_path)
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, check=True)
        os.remove(pid_path)
        return None
    except Exception as exc:
        return str(exc)


# ===== Irodori-TTS =====

IRODORI_DIR = os.environ.get("IRODORI_TTS_DIR", "")
IRODORI_URL = os.environ.get("IRODORI_TTS_URL", "http://127.0.0.1:8088")


def is_irodori_running() -> bool:
    url = os.environ.get("IRODORI_TTS_URL", IRODORI_URL)
    try:
        return requests.get(f"{url}/health", timeout=2).status_code == 200
    except requests.RequestException:
        return False


def start_irodori() -> str | None:
    IRODORI_DIR = os.environ.get("IRODORI_TTS_DIR", "")
    if not IRODORI_DIR:
        return "IRODORI_TTS_DIRが未設定です。バックエンド設定で場所を指定してください。"
    if is_irodori_running():
        return None
    pid_path = _pid_path("irodori")
    fd = _try_claim_pid_slot("irodori")
    if fd is None:
        return None
    if not os.path.isdir(IRODORI_DIR):
        os.close(fd)
        os.remove(pid_path)
        return f"Irodori-TTS-Serverが見つかりません: {IRODORI_DIR}"
    _venv_python = os.path.join(IRODORI_DIR, ".venv", "Scripts", "python.exe")
    if not os.path.isfile(_venv_python):
        os.close(fd)
        os.remove(pid_path)
        return f"Irodori-TTS-Serverのvenvが見つかりません: {_venv_python}"
    try:
        proc = subprocess.Popen(
            [_venv_python, "-m", "irodori_openai_tts",
             "--host", "0.0.0.0", "--port", "8088"],
            cwd=IRODORI_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )
        os.write(fd, f"{proc.pid}:{time.time()}".encode())
        os.close(fd)
        return None
    except Exception as exc:
        os.close(fd)
        try:
            os.remove(pid_path)
        except OSError:
            pass
        return str(exc)


def stop_irodori() -> str | None:
    pid_path = _pid_path("irodori")
    if not os.path.exists(pid_path):
        return None
    try:
        pid = _read_pid(pid_path)
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, check=True)
        os.remove(pid_path)
        return None
    except Exception as exc:
        return str(exc)


# ===== Kokoro TTS =====

KOKORO_DIR = os.environ.get("KOKORO_TTS_DIR", "")
KOKORO_URL = os.environ.get("KOKORO_TTS_URL", "http://127.0.0.1:8766")


def is_kokoro_running() -> bool:
    url = os.environ.get("KOKORO_TTS_URL", KOKORO_URL)
    try:
        return requests.get(f"{url}/health", timeout=2).status_code == 200
    except requests.RequestException:
        return False


def start_kokoro() -> str | None:
    KOKORO_DIR = os.environ.get("KOKORO_TTS_DIR", "")
    if not KOKORO_DIR:
        return "KOKORO_TTS_DIRが未設定です。バックエンド設定で場所を指定してください。"
    if is_kokoro_running():
        return None
    pid_path = _pid_path("kokoro")
    fd = _try_claim_pid_slot("kokoro")
    if fd is None:
        return None
    _venv_python = os.path.join(KOKORO_DIR, "venv", "Scripts", "python.exe")
    _server_py = os.path.join(KOKORO_DIR, "server.py")
    if not os.path.isfile(_venv_python):
        os.close(fd)
        os.remove(pid_path)
        return f"Kokoro TTSのvenvが見つかりません: {_venv_python}"
    if not os.path.isfile(_server_py):
        os.close(fd)
        os.remove(pid_path)
        return f"Kokoro TTSのserver.pyが見つかりません: {_server_py}"
    try:
        _env = os.environ.copy()
        _env["PYTHONUTF8"] = "1"
        _env["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        proc = subprocess.Popen(
            [_venv_python, _server_py],
            cwd=KOKORO_DIR,
            env=_env,
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )
        os.write(fd, f"{proc.pid}:{time.time()}".encode())
        os.close(fd)
        return None
    except Exception as exc:
        os.close(fd)
        try:
            os.remove(pid_path)
        except OSError:
            pass
        return str(exc)


def stop_kokoro() -> str | None:
    pid_path = _pid_path("kokoro")
    if not os.path.exists(pid_path):
        return None
    try:
        pid = _read_pid(pid_path)
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, check=True)
        os.remove(pid_path)
        return None
    except Exception as exc:
        return str(exc)


# ===== ComfyUI =====

COMFYUI_DIR = os.environ.get("COMFYUI_DIR", "")
COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")


def is_comfyui_running() -> bool:
    try:
        return requests.get(f"{COMFYUI_URL}/system_stats", timeout=2).status_code == 200
    except requests.RequestException:
        return False


def start_comfyui() -> str | None:
    if not COMFYUI_DIR:
        return "COMFYUI_DIRが未設定です。.envファイルを確認してください。"
    if is_comfyui_running():
        return None
    pid_path = _pid_path("comfyui")
    fd = _try_claim_pid_slot("comfyui")
    if fd is None:
        return None
    _bat = os.path.join(COMFYUI_DIR, "run_nvidia_gpu.bat")
    if not os.path.isfile(_bat):
        os.close(fd)
        os.remove(pid_path)
        return f"ComfyUIの起動スクリプトが見つかりません: {_bat}"
    try:
        proc = subprocess.Popen(
            [_bat],
            cwd=COMFYUI_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )
        os.write(fd, f"{proc.pid}:{time.time()}".encode())
        os.close(fd)
        return None
    except Exception as exc:
        os.close(fd)
        try:
            os.remove(pid_path)
        except OSError:
            pass
        return str(exc)


def stop_comfyui() -> str | None:
    pid_path = _pid_path("comfyui")
    if not os.path.exists(pid_path):
        return None
    try:
        pid = _read_pid(pid_path)
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, check=True)
        os.remove(pid_path)
        return None
    except Exception as exc:
        return str(exc)


# ===== Ollama =====

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


def is_ollama_running() -> bool:
    url = os.environ.get("OLLAMA_URL", OLLAMA_URL)
    try:
        return requests.get(f"{url}/api/tags", timeout=3).status_code == 200
    except requests.RequestException:
        return False


def stop_ollama() -> str | None:
    pid_path = _pid_path("ollama")
    if not os.path.exists(pid_path):
        return None
    try:
        pid = _read_pid(pid_path)
        subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True, check=True)
        os.remove(pid_path)
        return None
    except Exception as exc:
        return str(exc)


def start_ollama() -> str | None:
    # 他バックエンドと異なりpidファイルガードが元々無く、素朴にis_ollama_running()
    # だけで判定していた（2026-08-16、他バックエンドと同じ保護を追加）。
    if is_ollama_running():
        return None
    fd = _try_claim_pid_slot("ollama")
    if fd is None:
        return None
    try:
        proc = subprocess.Popen(
            ["ollama", "serve"],
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )
        os.write(fd, f"{proc.pid}:{time.time()}".encode())
        os.close(fd)
        print(f"[Ollama] Started pid={proc.pid}")
        return None
    except FileNotFoundError:
        os.close(fd)
        try:
            os.remove(_pid_path("ollama"))
        except OSError:
            pass
        return "ollamaコマンドが見つかりません。Ollamaがインストールされているか確認してください。"
    except Exception as exc:
        os.close(fd)
        try:
            os.remove(_pid_path("ollama"))
        except OSError:
            pass
        return str(exc)


# ===== 一括起動 =====

def auto_start_backends(llm_backend: str = "textgen_webui", tts_backend: str = "voicevox", t2i_backend: str = "a1111") -> dict[str, str | None]:
    """設定に応じて必要なバックエンドのみ自動起動する。"""
    results = {}

    if llm_backend == "textgen_webui":
        if is_tgw_running():
            results["tgw"] = None
        else:
            results["tgw"] = start_tgw()

    if tts_backend == "voicevox":
        if is_voicevox_running():
            results["voicevox"] = None
        else:
            results["voicevox"] = start_voicevox()
    elif tts_backend == "irodori":
        if is_irodori_running():
            results["irodori"] = None
        else:
            results["irodori"] = start_irodori()
    elif tts_backend == "kokoro":
        if is_kokoro_running():
            results["kokoro"] = None
        else:
            results["kokoro"] = start_kokoro()

    if t2i_backend == "a1111":
        if is_a1111_running():
            results["a1111"] = None
        else:
            results["a1111"] = start_a1111()
    elif t2i_backend == "comfyui":
        if is_comfyui_running():
            results["comfyui"] = None
        else:
            results["comfyui"] = start_comfyui()

    return results
