"""TGW(Text Generation WebUI)の起動状態管理・モデル自動ロード"""

import os
import subprocess
import threading

import requests

from def_kari.llm.adapters.tgw import TEXTGEN_WEBUI_URL

TEXTGEN_WEBUI_DIR = os.environ.get(
    "TEXTGEN_WEBUI_DIR", ""
)


def is_running() -> bool:
    try:
        resp = requests.get(f"{TEXTGEN_WEBUI_URL}/models", timeout=2)
        return resp.status_code == 200
    except requests.RequestException:
        return False


def is_model_loaded() -> bool:
    try:
        resp = requests.get(f"{TEXTGEN_WEBUI_URL}/internal/model/info", timeout=2)
        model_name = resp.json().get("model_name")
        return bool(model_name) and model_name != "None"
    except Exception:
        return False


def get_loaded_model_name() -> str | None:
    try:
        resp = requests.get(f"{TEXTGEN_WEBUI_URL}/internal/model/info", timeout=2)
        name = resp.json().get("model_name")
        if name and name != "None":
            return name
    except Exception:
        pass
    return None


def list_available_models() -> list[str]:
    try:
        resp = requests.get(f"{TEXTGEN_WEBUI_URL}/internal/model/list", timeout=5)
        resp.raise_for_status()
        return resp.json().get("model_names", [])
    except Exception:
        return []


def load_model_async(model_name: str) -> None:
    def _do_load():
        try:
            requests.post(
                f"{TEXTGEN_WEBUI_URL}/internal/model/load",
                json={"model_name": model_name},
                timeout=600,
            )
        except requests.RequestException:
            pass
    threading.Thread(target=_do_load, daemon=True).start()


def start_tgw() -> str | None:
    """TGWをバックグラウンドで起動する。成功時None、失敗時エラーメッセージ。"""
    if is_running():
        return None

    conda_python = os.path.join(TEXTGEN_WEBUI_DIR, "installer_files", "env", "python.exe")
    server_py = os.path.join(TEXTGEN_WEBUI_DIR, "server.py")

    if not os.path.isfile(conda_python):
        return f"TGWのPython実行ファイルが見つかりません: {conda_python}"
    if not os.path.isfile(server_py):
        return f"TGWのserver.pyが見つかりません: {server_py}"

    try:
        subprocess.Popen(
            [conda_python, server_py],
            cwd=TEXTGEN_WEBUI_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return None
    except Exception as exc:
        return str(exc)


def stop_tgw() -> str | None:
    """TGWを停止する。成功時None、失敗時エラーメッセージ。"""
    try:
        requests.post(f"{TEXTGEN_WEBUI_URL}/internal/stop-server", timeout=5)
        return None
    except Exception as exc:
        return str(exc)
