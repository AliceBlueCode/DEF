"""プラグインの口を呼ぶ入口（マルチルールブック基盤 B-009・B-027、基本設計書 11.4・11.6）。

DEF の差し込み口は、ここを通してだけプラグインの口を呼ぶ。プラグインの中身を名前で呼ばない（B-007）。

- セッションのルールブックの `rule_system` をレジストリで引き、そのルールシステムが口を持っていれば呼ぶ。
- 口を持っていなければ `NOT_HANDLED` を返す。呼ぶ側は、DEF の今の処理をそのまま動かす
  （def_original は口を1つも持たない）。
- 口が例外を出したら、その呼び出しの結果は「閉じる側の値」（`CLOSED_VALUES`）にする。口が無いときの
  DEF の処理には逃がさない。そのうえで、呼ぶ側が渡した `on_failure`（差し込み口では、セッションの
  進行の持ち主 `session_turn_engine._pause_for_plugin_error`）で卓の進行を止め、ログに書く。
  サーバーと他の卓は動き続ける（B-027）。この層（`def_kari/trpg`）はセッションのキーを直接書かない
  （`tests/test_session_key_ownership.py`）。

口を実際に呼ぶ差し込み口は、まだ無い（1つ目のプラグインを作るときに足す）。
"""

import copy
import logging

from def_kari.trpg import registry, resources

_log = logging.getLogger("def.trpg")


class _NotHandled:
    def __repr__(self) -> str:
        return "NOT_HANDLED"


NOT_HANDLED = _NotHandled()

# 口の関数ごとの「失敗したときの値」（閉じる側に倒す。基本設計書 11.6）。
CLOSED_VALUES: dict[str, object] = {
    # turn_driver
    "handle_request": {"accepted": False, "reason": "plugin_error"},
    "allows_vote": False,
    # gm_driver: GM を呼ばない
    "run_gm": None,
    # visibility: 配らない・返さない
    "session_view": {"plugin_error": True},
    "event_view": None,
    "history_view": [],
    # prompt_context: LLM を呼ばない
    "gm_context": None,
    "player_context": None,
    # image_prompt: 画像を作らない
    "image_prompt_source": None,
    # memory_policy: 書き込まない
    "should_save_memory": False,
    # persistence: 卓を作らない・DEF の自動保存に載せない・戻さない
    "check_create": "plugin_error",
    "uses_def_autosave": False,
    "restore_sessions": [],
    # ui: 部品を描かない・操作は断る
    "ui_state": {"ui_schema": 1, "components": []},
    "ui_action": {"accepted": False, "reason": "plugin_error"},
}


def resolve_for_session(session: dict) -> tuple[object | None, str | None]:
    """卓のルールシステムと、引けないときの理由。

    卓を作ったときに固定した `trpg_rule_system`（とプラグインの版）から引く（B-002）。固定した
    値の無い古い卓は、ルールブックから引く。ルールブックの無い卓は (None, None)。
    """
    if not isinstance(session, dict):
        return None, None
    if session.get("trpg_rule_system"):
        return registry.resolve_pinned(session["trpg_rule_system"], session.get("trpg_plugin_version", ""))
    rulebook_id = session.get("trpg_rulebook", "")
    rulebook = resources.load_rulebook(rulebook_id) if rulebook_id else {}
    return (registry.for_rulebook(rulebook) if rulebook else None), None


def system_for_session(session: dict):
    """卓のルールシステム。引けない・ルールブックが無いときは None。"""
    return resolve_for_session(session)[0]


def has_capability(session: dict, capability: str) -> bool:
    """口を持っているか。固定したルールシステムが引けない卓は True（呼ぶ側を `call` に回し、閉じる側に倒す）。"""
    system, reason = resolve_for_session(session)
    if reason:
        return True
    return system is not None and capability in getattr(system, "capabilities", frozenset())


def call(session: dict | None, capability: str, method: str, *args, system=None, on_failure=None, **kwargs):
    """口 `capability` の関数 `method` を呼ぶ。口が無ければ `NOT_HANDLED`。

    `system` を渡せば、そのルールシステムを使う（起動のときの `restore_sessions` のように、
    まだセッションが無いとき用）。`on_failure(session, info)` は、口が失敗したときに呼ぶ
    （卓を止める）。
    """
    if method not in CLOSED_VALUES:
        raise ValueError(f"unknown hook method: {method!r}")
    reason = None
    if system is None and session:
        system, reason = resolve_for_session(session)
    if reason:
        # 固定したルールシステムが引けない卓: 口があったはずなので、口が無いときの DEF の処理には
        # 逃がさず、閉じる側に倒して卓を止める（B-002・B-027。実装レビューの🟡2）
        _log.error("[trpg] table rule system is unavailable: %s", reason)
        if on_failure is not None and isinstance(session, dict):
            on_failure(session, {"capability": capability, "method": method, "error": reason})
        return copy.deepcopy(CLOSED_VALUES[method])
    if system is None or capability not in getattr(system, "capabilities", frozenset()):
        return NOT_HANDLED
    try:
        return getattr(system, method)(*args, **kwargs)
    except Exception as e:  # プラグインの不具合で、サーバーと他の卓を止めない（B-027）
        _log.error("[trpg] plugin hook %s.%s of %s failed: %s: %s",
                   capability, method, getattr(system, "id", "?"), type(e).__name__, e)
        if on_failure is not None and isinstance(session, dict):
            on_failure(session, {"capability": capability, "method": method,
                                 "error": f"{type(e).__name__}: {e}"})
        return copy.deepcopy(CLOSED_VALUES[method])
