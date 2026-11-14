"""TRPG のルールブックとシナリオの置き場所と読み込み（マルチルールブック基盤 B-010〜B-013、B-020、B-029）。

置き場所は、次の順に探す（B-011、基本設計書 11.1）。同じ ID は先に見つかった方を使い、重なりを警告に残す。

1. プラグインのデータ（`TRPG_PLUGIN_PATHS` で読み込んだプラグインのフォルダ。ほかの出どころが、
   同じ ID でプラグインのルールブックを上書きできないよう、いちばん先に読む）
2. ルールブックのデータのリポジトリ（`.env` の `TRPG_RULEBOOK_REPO_PATHS`、`;` 区切り）。形は2通り:
   - 単体型: 直下に `manifest.json`。1つのリポジトリが1つのまとまり
   - 集約型: 直下に `manifest.json` が無ければ、1階層下のフォルダをそれぞれ1つのまとまりとして読む
   まとまりの中は `rulebooks/<ID>.json`・`scenarios/<ID>.json`
3. `data/public/trpg_rules/`・`data/public/trpg_scenarios/`
4. `data/private/trpg_rules/`・`data/private/trpg_scenarios/`

決まり:

- ID の正本はファイル名（拡張子を除く）。JSON の `id` がファイル名と違えば警告を残し、ファイル名を使う（B-029）。
- どの読み方でも、パスを解決した後に置き場所の内側にある普通のファイルだけを読む（`safe_file`、B-012）。
- オンラインの卓・公開のポートからの読み込み（`public_only`）は、今は `data/public` だけ。manifest の
  `online_sessions` に従って広げるのは B-013・B-022（手順4b）。
- manifest（B-020）はまとまりごとに1つ。卓が外部に送ってよいか・オンラインで使ってよいかは
  `table_permissions()` で、使うものすべての manifest が許すときだけ許す。

`RULEBOOK_DIRS` などは `data/` の2か所（3・4）。テストはこれと `_external_sources` を差し替える。
"""

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from def_kari.trpg import registry

_log = logging.getLogger("def.trpg")

_BASE = Path(__file__).parent.parent.parent

RULEBOOK_DIRS: list[Path] = [
    _BASE / "data" / "public" / "trpg_rules",
    _BASE / "data" / "private" / "trpg_rules",
]
PUBLIC_RULEBOOK_DIRS: list[Path] = [_BASE / "data" / "public" / "trpg_rules"]
SCENARIO_DIRS: list[Path] = [
    _BASE / "data" / "public" / "trpg_scenarios",
    _BASE / "data" / "private" / "trpg_scenarios",
]
PUBLIC_SCENARIO_DIRS: list[Path] = [_BASE / "data" / "public" / "trpg_scenarios"]

# 8.26対策: rulebook_id / scenario_id は、クライアントの入力をそのままファイル名に使う。
# ID の許可リストと、パスを解決した後に置き場所の内側にあるかの確認の二重で、パストラバーサルと
# 絶対パスの注入を防ぐ。
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def is_safe_id(resource_id: str) -> bool:
    return bool(resource_id) and bool(SAFE_ID_RE.match(resource_id))


def safe_file(d: Path, name: str, root: Path | None = None) -> Path | None:
    """置き場所 `d` の中のファイル `name` のパスを、安全なときだけ返す（B-012）。

    パスを解決した後（シンボリックリンクやジャンクションをたどった後）も、基準のフォルダの内側にあり、
    普通のファイルであるときだけ、解決した後のパスを返す。それ以外は None。基準は `root`（外部の
    まとまりの根。リポジトリ、集約型のサブフォルダ、プラグインのフォルダ）で、無ければ `d`。
    読み込み・一覧・個別の取得・保存先の検索は、すべてこの関数を通す。

    - 2026-11-13: 一覧と個別の取得が確かめずに読んでいて、ファイルのリンクから外を読めた（一次レビュー）。
    - 2026-11-14: 基準が `d` だったので、`rulebooks/` そのものが外を指すリンク（Windows のジャンクション
      なら権限なしで作れる）だと、外のフォルダ全体が「内側」になっていた（実装レビューの🔴1）。
    """
    try:
        base = (root if root is not None else d).resolve()
        candidate = (d / name).resolve()
        if not candidate.is_relative_to(base):
            if (d / name).exists() or (d / name).is_symlink():
                _log.warning("[trpg] %s points outside %s; ignored", d / name, root if root is not None else d)
            return None
        return candidate if candidate.is_file() else None
    except (OSError, ValueError):
        return None


# ── manifest（B-020、基本設計書 11.2） ─────────────────────────────

_MANIFEST_TYPES = {
    "manifest_version": int, "id": str, "title": str, "license": str, "credit": str,
    "external_services_allowed": bool, "online_sessions": bool,
}


def read_manifest(folder: Path) -> tuple[dict | None, str]:
    """`folder/manifest.json` を読む。無ければ (None, "")。壊れている・型が違うなら (None, 理由)。"""
    path = safe_file(folder, "manifest.json")
    if path is None:
        return None, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return None, f"manifest.json is broken: {e}"
    if not isinstance(data, dict):
        return None, "manifest.json must be an object"
    for key, typ in _MANIFEST_TYPES.items():
        if key in data and not (isinstance(data[key], typ) and not (typ is int and isinstance(data[key], bool))):
            return None, f"manifest.json: {key} must be {typ.__name__}"
    return data, ""


@dataclass(frozen=True)
class Source:
    """ルールブックとシナリオの、1つのまとまり（置き場所）。"""
    kind: str                  # "plugin" | "repo" | "local"
    label: str                 # ログと案内に出す名前
    rules_dir: Path
    scenarios_dir: Path
    manifest: dict | None      # manifest.json の中身。無い・壊れているなら None
    manifest_error: str = ""   # 壊れていたときの理由
    plugin_rule_systems: tuple = ()  # プラグインのまとまりなら、そのプラグインのルールシステム
    root: Path | None = None   # 外部のまとまりの根。中のファイルは、この内側にあるものだけを読む（B-012）


def _repo_sources(root: Path) -> list[Source]:
    if not root.is_dir():
        _log.warning("[trpg] rulebook repository not found: %s", root)
        return []
    manifest, err = read_manifest(root)
    if manifest is not None or err or (root / "rulebooks").is_dir() or (root / "scenarios").is_dir():
        if err:
            _log.warning("[trpg] %s: %s", root, err)
        return [Source("repo", str(root), root / "rulebooks", root / "scenarios", manifest, err, (), root)]
    found = []
    for sub in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if not is_safe_id(sub.name):
            _log.warning("[trpg] %s: folder name is not a valid id; ignored", sub)
            continue
        try:
            if not sub.resolve().is_relative_to(root.resolve()):
                _log.warning("[trpg] %s points outside %s; ignored", sub, root)
                continue
        except (OSError, ValueError):
            continue
        m, e = read_manifest(sub)
        if e:
            _log.warning("[trpg] %s: %s", sub, e)
        found.append(Source("repo", str(sub), sub / "rulebooks", sub / "scenarios", m, e, (), sub))
    return found


def _external_sources() -> list[Source]:
    """プラグインのデータ → ルールブックのリポジトリ の順のまとまり（`data/` の分は含まない）。"""
    registry.registered_ids()  # プラグインを読み込んでおく（起動のときに1回だけ）
    from def_kari.trpg import plugins
    sources = []
    for p in plugins.loaded_plugins():
        m, e = read_manifest(p.path)
        sources.append(Source("plugin", f"plugin {p.plugin_id}", p.path / "rulebooks", p.path / "scenarios",
                              m, e, tuple(p.rule_systems), p.path))
    for raw in os.environ.get("TRPG_RULEBOOK_REPO_PATHS", "").split(";"):
        if raw.strip():
            sources.extend(_repo_sources(Path(raw.strip())))
    return sources


def _local_sources(public_only: bool) -> list[Source]:
    pairs = (list(zip(PUBLIC_RULEBOOK_DIRS, PUBLIC_SCENARIO_DIRS)) if public_only
             else list(zip(RULEBOOK_DIRS, SCENARIO_DIRS)))
    return [Source("local", str(r.parent), r, s, None) for r, s in pairs]


def sources(public_only: bool = False) -> list[Source]:
    """探す順のまとまり。

    `public_only`（オンラインの卓・公開のポートからの読み込み）では、manifest で `online_sessions` を
    はっきり許した外部のまとまりと、DEF に同梱の `data/public` だけを読む（B-013）。manifest の無い
    外部のまとまりは読まない。卓として使ってよいかは、さらに `online_refusal()` で確かめる（B-022）。
    """
    if public_only:
        allowed = [s for s in _external_sources()
                   if not s.manifest_error and (s.manifest or {}).get("online_sessions") is True]
        return allowed + _local_sources(True)
    return _external_sources() + _local_sources(False)


# ── 読み込み ─────────────────────────────────────────────────────

def _as_place(d) -> tuple[Path, Path | None]:
    return d if isinstance(d, tuple) else (d, None)


def load_resource(resource_id: str, dirs: list) -> dict:
    """`dirs`（フォルダ、または (フォルダ, 根)）を順に探し、最初に読めた `{resource_id}.json` を返す。"""
    if not is_safe_id(resource_id):
        return {}
    for d in dirs:
        folder, root = _as_place(d)
        path = safe_file(folder, f"{resource_id}.json", root)
        if path is not None:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def _places(kind: str, public_only: bool = False) -> list[tuple[Path, Path | None, Source]]:
    out = []
    for src in sources(public_only):
        out.append((src.rules_dir if kind == "rules" else src.scenarios_dir, src.root, src))
    return out


def _locate(resource_id: str, kind: str, public_only: bool = False) -> tuple[dict, Path | None, Source | None]:
    """最初に読めた `{resource_id}.json` の (中身, パス, まとまり)。読み込み・取得・確かめは、すべて
    この1つの探し方を使う（先のファイルが壊れていれば次を見る。確かめと読み込みで見るものがずれない）。"""
    if not is_safe_id(resource_id):
        return {}, None, None
    for folder, root, src in _places(kind, public_only):
        path = safe_file(folder, f"{resource_id}.json", root)
        if path is None:
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8")), path, src
        except (json.JSONDecodeError, OSError):
            continue
    return {}, None, None


def load_rulebook(rulebook_id: str, public_only: bool = False) -> dict:
    """ルールブックを読む。登録されていない `rule_system` のものは読まない（空の dict。B-002）。"""
    data = _locate(rulebook_id, "rules", public_only)[0]
    if data and not registry.is_known(data):
        _log.warning("[trpg] rulebook %s uses an unknown rule_system %r; not loaded",
                     rulebook_id, registry.rule_system_of(data))
        return {}
    return data


def rulebook_unavailable_reason(rulebook_id: str) -> str | None:
    """ルールブックのファイルはあるのに、その `rule_system` が登録されていない（プラグインが
    読み込まれていない）とき、その理由を返す。それ以外（無い・読める）は None（B-002）。"""
    data = _locate(rulebook_id, "rules")[0]
    if data and not registry.is_known(data):
        return (f"rulebook {rulebook_id!r} needs the rule system {registry.rule_system_of(data)!r}, "
                f"which is not available (its plugin is not loaded)")
    return None


def load_scenario(scenario_id: str, public_only: bool = False) -> dict:
    return _locate(scenario_id, "scenarios", public_only)[0]


def _load_all(places: list) -> dict:
    """置き場所のすべての JSON を読み、ID（ファイル名）→ 中身 の dict を返す。

    同じ ID は先に見つかった方を使い、重なりを警告に残す（B-011）。JSON の `id` がファイル名と
    違えば警告を残し、ファイル名を ID にする（B-029）。読めないファイルは飛ばす。
    """
    found: dict = {}
    where: dict = {}
    for place in places:
        d, root = _as_place(place[:2] if isinstance(place, tuple) else place)
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix != ".json" or f.name == ".gitkeep":
                continue
            path = safe_file(d, f.name, root)
            if path is None:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            rid = f.stem
            if isinstance(data, dict) and data.get("id") not in (None, rid):
                _log.warning("[trpg] %s: id %r differs from the file name; using %r", path, data.get("id"), rid)
            if rid in found:
                _log.warning("[trpg] %s is also in %s; using the one in %s", rid, d, where[rid])
                continue
            found[rid] = data
            where[rid] = d
    return found


def all_rulebooks() -> dict:
    """一覧に出すルールブック。登録されていない `rule_system` のものは除く（B-002）。"""
    return {k: v for k, v in _load_all(_places("rules")).items() if registry.is_known(v)}


def all_scenarios() -> dict:
    return _load_all(_places("scenarios"))


def find_rulebook_file(rulebook_id: str) -> Path | None:
    return _locate(rulebook_id, "rules")[1]


def find_scenario_file(scenario_id: str) -> Path | None:
    return _locate(scenario_id, "scenarios")[1]


def rulebook_source(rulebook_id: str) -> Source | None:
    return _locate(rulebook_id, "rules")[2]


def scenario_source(scenario_id: str) -> Source | None:
    return _locate(scenario_id, "scenarios")[2]


def new_rulebook_file(rulebook_id: str) -> Path:
    """画面から新しく保存するルールブックのパス。git で管理していない置き場（data/private。
    `RULEBOOK_DIRS` の最後）に置く（B-028。2026-11-14 までは data/public に保存していた）。"""
    target_dir = RULEBOOK_DIRS[-1]
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{rulebook_id}.json"


# ── 卓の許可（B-020） ───────────────────────────────────────────────

_PERMISSION_KEYS = ("external_services_allowed", "online_sessions")


def _allowed(source: Source | None, key: str, rule_system: str) -> bool:
    """1つのまとまりが `key` を許すか。manifest が無いときの既定は、ルールシステムで決める
    （def_original は許す。それ以外は許さない）。manifest が壊れていれば許さない。"""
    if source is not None and source.manifest_error:
        return False
    manifest = source.manifest if source is not None else None
    if manifest is not None and key in manifest:
        return bool(manifest[key])
    return rule_system == registry.DEFAULT_RULE_SYSTEM


def table_credits(rulebook_id: str, scenario_id: str = "", rule_system: str | None = None) -> list[str]:
    """卓が使うもの（ルールブック、シナリオ、ルールシステムを登録したプラグイン）の manifest の `credit`（B-023）。"""
    if not rulebook_id and not scenario_id:
        return []
    return table_permissions(rulebook_id, scenario_id, rule_system)["credits"]


def online_refusal(rulebook_id: str, scenario_id: str = "", rule_system: str | None = None) -> str | None:
    """このルールブック・シナリオの卓をオンラインで開けないとき、その理由（B-022）。開けるなら None。"""
    if not rulebook_id and not scenario_id:
        return None
    perms = table_permissions(rulebook_id, scenario_id, rule_system)
    if perms["missing"]:
        return "cannot use in online sessions: " + "; ".join(perms["missing"])
    if perms["online_sessions"]:
        return None
    return (f"rulebook {rulebook_id!r}" + (f" / scenario {scenario_id!r}" if scenario_id else "")
            + " cannot be used in online sessions (not allowed by its manifest)")


def table_permissions(rulebook_id: str, scenario_id: str = "", rule_system: str | None = None) -> dict:
    """卓が外部のサービスに送ってよいか・オンラインで使ってよいか（B-020）。

    卓が使うもの（ルールブック、シナリオ、そのルールブックのルールシステムを登録したプラグイン）の
    manifest の、すべてが許すときだけ許す。クレジット（B-023）も集めて返す。

    - `rule_system` には、卓を作ったときに固定した値（`trpg_rule_system`）を渡す。渡せばルールブックの
      中身より優先し、ルールブックが読めなくてもプラグインの manifest を見る（B-002）。
    - 指定したルールブック・シナリオが読めない（無い、壊れている）ときは、許さない（閉じる側。B-021。
      実装レビュー2の🔴1。以前は「ルールブックの無い卓」と同じに扱い、送ってよいと判断していた）。
      理由は `missing` に入る。
    """
    rulebook, _, rb_source = _locate(rulebook_id, "rules") if rulebook_id else ({}, None, None)
    missing = []
    if rulebook_id and rb_source is None:
        missing.append(f"rulebook {rulebook_id!r} cannot be read")
    rule_system = rule_system or registry.rule_system_of(rulebook)
    involved: list[Source | None] = [rb_source]
    if scenario_id:
        sc_source = _locate(scenario_id, "scenarios")[2]
        if sc_source is None:
            missing.append(f"scenario {scenario_id!r} cannot be read")
        involved.append(sc_source)
    if rule_system != registry.DEFAULT_RULE_SYSTEM:
        plugin_src = next((s for s in _external_sources()
                           if s.kind == "plugin" and rule_system in s.plugin_rule_systems), None)
        involved.append(plugin_src)
    result = {key: (not missing) and all(_allowed(s, key, rule_system) for s in involved) for key in _PERMISSION_KEYS}
    result["missing"] = missing
    credits = []
    for s in involved:
        c = (s.manifest or {}).get("credit", "") if s is not None else ""
        if c and c not in credits:
            credits.append(c)
    result["credits"] = credits
    result["rule_system"] = rule_system
    return result
