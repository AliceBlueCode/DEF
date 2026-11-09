"""セッション辞書のキーの「持ち主」を固定するテスト（2026-11-09、セッション進行のリファクタリング Step 1）。

`_sessions` は dict のまま（自動保存の形式でもあるので分けない）。その代わり、「どのキーを
どのモジュールが書き換えてよいか」をここで決め、決まりの外で書き換えたら落とす。

これまでの不具合の多くは、同じ状態を複数の場所が別々に書き換えていたことから起きた
（手番の巻き戻り、スキップの経路ごとの漏れ、AIの指名だけ戻り先を記録しなかった件など）。
新しく書き換える場所を足したくなったら、まず持ち主のモジュールに関数を用意し、そこを呼ぶ。
どうしても例外が必要なら、理由をコメントに書いて OWNERS に足す。

検出するのは、def_kari 配下の次の形（構文木で走査する）:
- `X["key"] = …` / `X["key"] += …` / `del X["key"]`
- `X["key"][…] = …`、`X.setdefault("key", …)[…] = …`（中身の書き換え）
- `X.pop("key")` / `X.setdefault("key", …)`
- `X["key"].append(…)` などの変更メソッド（`X.get("key", …)`・`X.setdefault("key", …)` 経由も含む）
いったん別の変数に取り出してから書き換える形（`c = s["counters"]; c[x] = 1`）は検出しない。
"""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "def_kari"

_R = "def_kari/api/routes/"
TURN_ENGINE = _R + "session_turn_engine.py"
TURN_STATE = _R + "session_turn_state.py"
LOBBY = _R + "session_lobby.py"
VOTING = _R + "session_voting.py"
PERSISTENCE = _R + "session_persistence.py"
DISCONNECT = _R + "session_turn_disconnect.py"
WS = _R + "session_ws.py"
GAMEPLAY = _R + "session_gameplay.py"

# キー → 書き換えてよいモジュール
OWNERS: dict[str, set[str]] = {
    # 手番の状態: 純粋な状態遷移（session_turn_state.py）と、進行の制御（手番エンジン）だけ。
    # 手番エンジンに残っているのは、AIの手番の始まりと終わり（_resolve_turn_start・
    # _finalize_ai_turn）・やり直し・強制スキップ・人間の発言の処理（Step 2 の A、2026-11-09）
    **{k: {TURN_STATE, TURN_ENGINE} for k in (
        "turn", "round", "_round_seq", "_round_spoken", "action_count",
        "designated_next", "designated_return_turn", "_designated_return_turn", "_skip_gen",
    )},
    # 手番の順: 開始前の準備（参加・AIの追加と削除）はロビー、進行中の除外は手番エンジン
    "initiative": {TURN_STATE, LOBBY},
    # 投票の決定待ち: 投票。起動時の復元は、決定待ちを捨てる（発言力を戻して通知を残す）ので例外
    "_pending_vote": {VOTING, PERSISTENCE},
    "_pending_expel_followup": {VOTING, PERSISTENCE},
    # AIの発議の記録: 行動選択（手番エンジン）が記録し、投票が受け付けで消費する。
    # 受け付けられずに次の手番が始まったときの払い戻しは、復元と同じ関数（persistence）にある
    "_ai_vote_proposal": {TURN_ENGINE, VOTING, PERSISTENCE},
    # 切断の自動スキップのタイマー: 切断モジュールだけ
    "disconnect_skip_tasks": {DISCONNECT},
    # WSの接続: WSモジュールの関数（登録・外す・閉じる）だけ。各所はそれを呼ぶ
    "ws_connections": {WS},
    # AIの手番のタスクと自動進行: 手番エンジン。自動進行の切り替えのエンドポイントは gameplay
    "ai_task": {TURN_ENGINE},
    "ai_paused": {TURN_ENGINE, GAMEPLAY},
    "auto_advance": {TURN_ENGINE, GAMEPLAY},
}

_MUTATORS = {"append", "remove", "clear", "extend", "update", "pop", "insert", "discard", "add", "popitem"}


def _const(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _container_key(node) -> str | None:
    """X["k"] / X.get("k", …) / X.setdefault("k", …) の "k"。"""
    if isinstance(node, ast.Subscript):
        return _const(node.slice)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("get", "setdefault") and node.args):
        return _const(node.args[0])
    return None


def find_key_writes(source: str) -> list[tuple[str, int]]:
    """ソースの中で、文字列キーを書き換えている箇所の (キー, 行) を返す。"""
    found: list[tuple[str, int]] = []
    for n in ast.walk(ast.parse(source)):
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.Delete)):
            targets = n.targets if isinstance(n, (ast.Assign, ast.Delete)) else [n.target]
            for t in targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Subscript) and not isinstance(sub.ctx, ast.Load):
                        if (k := _const(sub.slice)):
                            found.append((k, n.lineno))
                        if (k := _container_key(sub.value)):
                            found.append((k, n.lineno))
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr in ("pop", "setdefault") and n.args and (k := _const(n.args[0])):
                found.append((k, n.lineno))
            if n.func.attr in _MUTATORS and (k := _container_key(n.func.value)):
                found.append((k, n.lineno))
    return found


def _scan_package() -> dict[str, list[str]]:
    writes: dict[str, list[str]] = defaultdict(list)
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        for key, line in find_key_writes(path.read_text(encoding="utf-8")):
            if key in OWNERS:
                writes[key].append(f"{rel}:{line}")
    return writes


def test_scanner_detects_every_write_form():
    """走査が空振りしていないこと（検出できる形を、小さなコードで確かめる）。"""
    src = '''
s["turn"] = 1
s["round"] += 1
del s["action_count"]
s.pop("designated_next", None)
s.setdefault("ws_connections", {})[tok] = ws
s["initiative"].append(c)
s.get("ws_connections", {}).pop(tok, None)
x = s.get("turn")           # 読むだけ
y = s["round"]              # 読むだけ
'''
    keys = [k for k, _ in find_key_writes(src)]
    assert set(keys) == {"turn", "round", "action_count", "designated_next", "ws_connections", "initiative"}
    assert "turn" in keys and keys.count("turn") == 1  # 読むだけの行は数えない


def test_every_owned_key_is_written_somewhere():
    """持ち主の表が古くなっていないこと（どこからも書かれないキーが残っていたら、表を見直す）。"""
    writes = _scan_package()
    missing = sorted(k for k in OWNERS if not writes.get(k))
    assert not missing, f"OWNERS にあるが、どこからも書き換えられていないキー: {missing}"


def test_session_keys_are_written_only_by_their_owner_modules():
    writes = _scan_package()
    violations = []
    for key, places in writes.items():
        for place in places:
            module = place.rsplit(":", 1)[0]
            if module not in OWNERS[key]:
                violations.append(f'{key}: {place}（書いてよいのは {sorted(OWNERS[key])}）')
    assert not violations, (
        "セッションのキーが、持ち主ではないモジュールから書き換えられている。"
        "持ち主のモジュールに関数を用意してそれを呼ぶか、理由を書いて OWNERS に足すこと:\n  "
        + "\n  ".join(violations)
    )
