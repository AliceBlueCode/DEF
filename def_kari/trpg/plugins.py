"""ルールシステムのプラグインの読み込み（マルチルールブック基盤 B-006〜B-009、B-026・B-027）。

形は基本設計書 11.3（プラグインの形と API の版）・11.4（口とそのそろい方）・11.6（失敗の扱い）。

- 読み込むのは、`.env` の `TRPG_PLUGIN_PATHS`（`;` 区切り）に書いた手元のフォルダからだけ。
  ルールブックのデータの設定（`TRPG_RULEBOOK_REPO_PATHS`）からはコードを読まない（B-006）。
- 読み込みは1回だけ（レジストリを最初に使うとき、つまり DEF の起動のとき）。セッションの操作や
  参加者の入力をきっかけに読み込まない。
- 版が合わない、宣言が壊れている、口のそろい方を満たさない、`register` が失敗した、のどれでも、
  そのプラグインだけを読み込まず、理由を `load_errors()` に残し、起動は続ける（B-026・B-027）。
- プラグインは DEF と同じプロセスで動く手元のコードで、隔離はしない（B-027）。

口の中身（手番の進行など）を呼ぶ所は、まだ DEF に無い。今は口の名前とそろい方の確かめだけを持つ。
口を呼ぶ入口は `def_kari/trpg/plugin_hooks.py`。
"""

import importlib.util
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger("def.trpg")

# DEF が対応するプラグインAPIの版（基本設計書 11.3）。口の形・画面のデータの形を、互換の無い形で
# 変えたら 1 上げる。
SUPPORTED_PLUGIN_API = frozenset({1})

# 口の名前（基本設計書 11.4）。DEF の知らない名前を宣言したプラグインは読み込まない。
KNOWN_CAPABILITIES = frozenset({
    "turn_driver", "gm_driver", "visibility", "prompt_context",
    "image_prompt", "memory_policy", "persistence", "ui",
})

# 口のそろい方: この口を持つなら、これらの口も持たなければならない（基本設計書 11.4）。
REQUIRED_WITH = {
    "visibility": frozenset({"prompt_context", "image_prompt"}),
    "gm_driver": frozenset({"turn_driver"}),
    "turn_driver": frozenset({"persistence"}),
}

_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_PACKAGE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REQUIRED_METHODS = ("validate_rulebook", "general_check", "allowed_skills", "dice_notation", "build_rule_context")


def check_capabilities(capabilities) -> list[str]:
    """口の名前とそろい方の誤りを返す（空なら問題なし）。"""
    caps = frozenset(capabilities)
    errors = [f"unknown capability: {c!r}" for c in sorted(caps - KNOWN_CAPABILITIES)]
    for cap, needs in REQUIRED_WITH.items():
        if cap in caps:
            for missing in sorted(needs - caps):
                errors.append(f"capability {cap!r} requires {missing!r}")
    return errors


class PluginApi:
    """プラグインに渡す、DEF の中で使ってよいものだけの入れ物（基本設計書 11.3、対応表 2.2）。

    LLM への送信・読み上げ・画像生成は、外部への送信の確かめ（B-021、手順4）と一緒に足す。
    それまでは渡さない。
    """

    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id

    @staticmethod
    def roll_dice(notation: str) -> dict:
        from def_kari.trpg.rule_engine import roll_dice
        return roll_dice(notation)

    @staticmethod
    def load_rulebook(rulebook_id: str) -> dict:
        from def_kari.trpg import resources
        return resources.load_rulebook(rulebook_id)

    @staticmethod
    def load_scenario(scenario_id: str) -> dict:
        from def_kari.trpg import resources
        return resources.load_scenario(scenario_id)

    @staticmethod
    def vram_lock():
        from def_kari.resources.vram_lock import get_vram_lock
        return get_vram_lock()


@dataclass
class LoadedPlugin:
    plugin_id: str
    plugin_version: str
    path: Path
    rule_systems: list[str] = field(default_factory=list)


_loaded: list[LoadedPlugin] = []
_errors: list[dict] = []


def plugin_paths() -> list[Path]:
    raw = os.environ.get("TRPG_PLUGIN_PATHS", "")
    return [Path(p.strip()) for p in raw.split(";") if p.strip()]


def loaded_plugins() -> list[LoadedPlugin]:
    return list(_loaded)


def load_errors() -> list[dict]:
    """読み込まなかったプラグインと理由（{"path", "plugin_id", "reason"}）。画面とログで知らせる用。"""
    return list(_errors)


def _fail(path: Path, plugin_id: str, reason: str) -> None:
    _errors.append({"path": str(path), "plugin_id": plugin_id, "reason": reason})
    _log.warning("[trpg] plugin %s (%s) not loaded: %s", plugin_id or "?", path, reason)


def _read_declaration(path: Path) -> tuple[dict | None, str]:
    decl_path = path / "def_plugin.json"
    if not decl_path.is_file():
        return None, "def_plugin.json not found"
    try:
        decl = json.loads(decl_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return None, f"def_plugin.json is broken: {e}"
    if not isinstance(decl, dict):
        return None, "def_plugin.json must be an object"
    plugin_id = decl.get("plugin_id")
    if not isinstance(plugin_id, str) or not _ID_RE.match(plugin_id):
        return None, "plugin_id is missing or invalid"
    if not isinstance(decl.get("plugin_version"), str) or not decl["plugin_version"]:
        return decl, "plugin_version is missing"
    api = decl.get("def_plugin_api")
    if not isinstance(api, int) or isinstance(api, bool):
        return decl, "def_plugin_api must be an integer"
    if api not in SUPPORTED_PLUGIN_API:
        return decl, f"def_plugin_api {api} is not supported (supported: {sorted(SUPPORTED_PLUGIN_API)})"
    package = decl.get("package")
    if not isinstance(package, str) or not _PACKAGE_RE.match(package):
        return decl, "package is missing or invalid"
    systems = decl.get("rule_systems")
    if not isinstance(systems, list) or not systems or not all(isinstance(s, str) and _ID_RE.match(s) for s in systems):
        return decl, "rule_systems must be a non-empty list of ids"
    return decl, ""


def _module_name(plugin_id: str) -> str:
    # モジュール名は plugin_id から作る（package の名前が同じプラグインが2つあっても、互いを上書きしない）
    return "def_trpg_plugin_" + plugin_id.replace("-", "_")


def _import_package(path: Path, package: str, plugin_id: str):
    pkg_dir = (path / package).resolve()
    if not pkg_dir.is_relative_to(path.resolve()) or not (pkg_dir / "__init__.py").is_file():
        raise ImportError(f"package {package!r} not found in {path}")
    module_name = _module_name(plugin_id)
    spec = importlib.util.spec_from_file_location(
        module_name, pkg_dir / "__init__.py", submodule_search_locations=[str(pkg_dir)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _validate_system(system, declared: list[str]) -> str:
    sid = getattr(system, "id", None)
    if sid not in declared:
        return f"register() returned rule system {sid!r}, which is not in rule_systems"
    for m in _REQUIRED_METHODS:
        if not callable(getattr(system, m, None)):
            return f"rule system {sid!r} has no {m}()"
    caps = getattr(system, "capabilities", None)
    if not isinstance(caps, (set, frozenset)):
        return f"rule system {sid!r} capabilities must be a set"
    errs = check_capabilities(caps)
    return f"rule system {sid!r}: " + "; ".join(errs) if errs else ""


def load_plugin(path: Path, register, is_registered) -> LoadedPlugin | None:
    """1つのプラグインを読み込み、ルールシステムを `register` で登録する。失敗したら None。

    登録は、全部のルールシステムの確かめが済んでから行う（途中まで登録された状態を残さない）。
    """
    decl, err = _read_declaration(path)
    plugin_id = decl.get("plugin_id", "") if isinstance(decl, dict) else ""
    if err:
        _fail(path, plugin_id, err)
        return None
    if any(p.plugin_id == plugin_id for p in _loaded):
        _fail(path, plugin_id, f"plugin_id {plugin_id!r} is already loaded from another folder")
        return None

    def _forget_module() -> None:
        sys.modules.pop(_module_name(plugin_id), None)

    # 読み込み・register()・返したものの確かめのどこで失敗しても、起動を止めず、読み込んだモジュールも
    # 残さない（B-027）。SystemExit も捕まえる（プラグインが sys.exit() を呼んでも DEF は止まらない）。
    try:
        module = _import_package(path, decl["package"], plugin_id)
        entry = getattr(module, "register", None)
        if not callable(entry):
            raise ImportError("package has no register(api)")
        result = entry(PluginApi(plugin_id))
        systems = list(result) if isinstance(result, (list, tuple)) else [result]
        for system in systems:
            problem = _validate_system(system, decl["rule_systems"])
            if problem:
                _fail(path, plugin_id, problem)
                _forget_module()
                return None
        ids = [s.id for s in systems]
    except (Exception, SystemExit) as e:
        _fail(path, plugin_id, f"{type(e).__name__}: {e}")
        _forget_module()
        return None
    taken = [i for i in ids if is_registered(i)]
    if taken or len(set(ids)) != len(ids):
        _fail(path, plugin_id, f"rule system id already registered or duplicated: {taken or ids}")
        _forget_module()
        return None
    for system in systems:
        register(system)
    done = ids
    plugin = LoadedPlugin(plugin_id, decl["plugin_version"], path, done)
    _loaded.append(plugin)
    _log.info("[trpg] plugin %s %s loaded: %s", plugin_id, decl["plugin_version"], ", ".join(done))
    return plugin


def load_all(register, is_registered) -> None:
    """`TRPG_PLUGIN_PATHS` のプラグインをすべて読み込む（レジストリから1回だけ呼ばれる）。"""
    for path in plugin_paths():
        if not path.is_dir():
            _fail(path, "", "folder not found")
            continue
        load_plugin(path, register, is_registered)


def _reset_for_tests() -> None:
    _loaded.clear()
    _errors.clear()
