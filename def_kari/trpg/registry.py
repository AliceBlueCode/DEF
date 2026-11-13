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
