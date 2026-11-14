"""ルールシステムのレジストリ（マルチルールブック基盤 B-001〜B-004）。

ルールブックの JSON の `rule_system` から、そのルールシステムの実装（`RuleSystem`）を引く。
`rule_system` が無いルールブックは `def_original` として扱う（B-001）。登録されていない
`rule_system` のルールブックは、読み込まず、一覧にも出さない（B-002）。

差し替えるのは、ルールシステムごとに実際に違う判定まわりの5つだけ（B-003）。片方のルールに
しか無い機能（戦闘マップなど）は、ここに足さず、`capabilities`（対応の印・プラグインの口の名前）と
ルールシステムの側のモジュールで持つ（B-004）。形は基本設計書 11.3・11.4。
"""

from typing import Protocol

DEFAULT_RULE_SYSTEM = "def_original"


class RuleSystem(Protocol):
    id: str
    capabilities: frozenset[str]

    def validate_rulebook(self, data: dict) -> list[str]: ...

    def general_check(self, roll_total: int, value: int, rulebook: dict, **options) -> dict: ...

    def allowed_skills(self, rulebook: dict) -> frozenset[str]: ...

    def dice_notation(self, rulebook: dict) -> str: ...

    def build_rule_context(self, rulebook: dict, scenario: dict | None, lang: str) -> str: ...


_REGISTRY: dict[str, RuleSystem] = {}
_BUILTIN_LOADED = False


def _ensure_builtin() -> None:
    """DEF の本体のルールシステムと、プラグインのルールシステムを登録する（最初に使うときに1回だけ。
    DEF の起動のときに `load_all()` で呼ぶ）。プラグインは `TRPG_PLUGIN_PATHS` から読む（B-006）。"""
    global _BUILTIN_LOADED
    if _BUILTIN_LOADED:
        return
    _BUILTIN_LOADED = True
    from def_kari.trpg.systems.def_original import DefOriginal
    register(DefOriginal())
    from def_kari.trpg import plugins
    plugins.load_all(register, lambda sid: sid in _REGISTRY)


def load_all() -> None:
    """起動のときに呼ぶ。本体とプラグインのルールシステムを登録し、読み込めなかったものをログに残す。"""
    _ensure_builtin()


def register(system: RuleSystem) -> None:
    if not system.id or system.id in _REGISTRY:
        raise ValueError(f"rule system id is empty or already registered: {system.id!r}")
    _REGISTRY[system.id] = system


def get(rule_system_id: str) -> RuleSystem | None:
    _ensure_builtin()
    return _REGISTRY.get(rule_system_id)


def registered_ids() -> list[str]:
    _ensure_builtin()
    return sorted(_REGISTRY)


def rule_system_of(rulebook: dict) -> str:
    """ルールブックの `rule_system`。無ければ（空も）`def_original`（B-001）。"""
    value = rulebook.get("rule_system") if isinstance(rulebook, dict) else None
    return value if isinstance(value, str) and value else DEFAULT_RULE_SYSTEM


def for_rulebook(rulebook: dict) -> RuleSystem | None:
    """ルールブックのルールシステムの実装。登録されていなければ None。"""
    return get(rule_system_of(rulebook))


def is_known(rulebook: dict) -> bool:
    return for_rulebook(rulebook) is not None


# ── 卓のルールシステムの固定（B-002。実装レビューの🟡2） ───────────────────

def _loaded_plugin_version(rule_system_id: str) -> str:
    from def_kari.trpg import plugins
    for p in plugins.loaded_plugins():
        if rule_system_id in p.rule_systems:
            return p.plugin_version
    return ""


def pin_for(rulebook: dict) -> tuple[str, str]:
    """卓を作るとき（とルールブックを変えるとき）にセッションへ書く (rule_system, プラグインの版)。
    本体のルールシステム（def_original）の版は空。"""
    rule_system = rule_system_of(rulebook)
    return rule_system, _loaded_plugin_version(rule_system)


def resolve_pinned(rule_system_id: str, plugin_version: str = "") -> tuple["RuleSystem | None", str | None]:
    """固定したルールシステムを引く。引けない（プラグインが無い、版が変わった）なら (None, 理由)。

    卓の途中でルールブックのファイルが消えた・入れ替わったときに、別のルールシステムや口の無い
    既定の処理に倒れないよう、卓はルールブックからではなく、固定した値から引く。
    """
    system = get(rule_system_id)
    if system is None:
        return None, f"rule system {rule_system_id!r} of this table is not available (its plugin is not loaded)"
    current = _loaded_plugin_version(rule_system_id)
    if plugin_version and current != plugin_version:
        return None, (f"the plugin of rule system {rule_system_id!r} changed from {plugin_version} to "
                      f"{current or 'none'} since this table was created")
    return system, None


# ── ルールシステムの関数を呼ぶ入口（B-027。実装レビューの🟡3） ───────────────────

class RuleSystemError(ValueError):
    """ルールシステム（プラグイン）の判定まわりの関数が失敗した。"""


# 本体の拡張: 片方のルールにしか無い、口ではない機能（B-004）。名前で探すのは、ここに書いたものだけ。
#   damage_roll(rulebook) -> dict: ダメージ表を振る（def_original の `/api/trpg/damage`）
RULE_EXTENSIONS = frozenset({"damage_roll"})


def extension(system: "RuleSystem | None", name: str):
    """本体の拡張 `name` の関数。持っていなければ None。"""
    if name not in RULE_EXTENSIONS:
        raise ValueError(f"unknown rule extension: {name!r}")
    fn = getattr(system, name, None) if system is not None else None
    return fn if callable(fn) else None


def call_rule(system: "RuleSystem", method: str, *args, **kwargs):
    """ルールシステムの判定まわりの関数（B-003 の5つと、本体の拡張）を呼ぶ。失敗したら
    `RuleSystemError` にする（500 にしない。卓があれば、呼ぶ側が止める）。"""
    fn = getattr(system, method)
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # プラグインの不具合で、サーバーを落とさない（B-027）
        import logging
        logging.getLogger("def.trpg").error("[trpg] rule system %s.%s failed: %s: %s",
                                            getattr(system, "id", "?"), method, type(e).__name__, e)
        raise RuleSystemError(f"the rule system {getattr(system, 'id', '?')!r} failed in {method}: "
                              f"{type(e).__name__}: {e}") from e
