"""Sessionルール・アクションディレクティブのCRUD。`session.py`分割の一部。"""

import json
import os
import re
from pathlib import Path

from fastapi import Request
from pydantic import BaseModel

from def_kari.api.routes.session_state import router, local_router

_BASE = Path(__file__).parent.parent.parent.parent
_RULE_DIRS = [
    _BASE / "data" / "public" / "session_rules",
    _BASE / "data" / "private" / "session_rules",
]
# 無認証の公開ポート（public_main.py）向けの探索範囲。data/private/session_rulesを含まない。
# GET /rules・/rules/{rule_id}は招待コードのみで参加するゲストの画面でも呼ばれるため
# local_routerには移せない（読み取り自体は許可する）が、私有・NSFWルールセットの
# フルコンテンツまで無認証で読めてしまっていたため、探索範囲を分離した。
_PUBLIC_RULE_DIRS = [
    _BASE / "data" / "public" / "session_rules",
]
_DIRECTIVE_DIRS = [
    _BASE / "data" / "public" / "action_directives",
    _BASE / "data" / "private" / "action_directives",
]
# 同上（アクションディレクティブ版）。
_PUBLIC_DIRECTIVE_DIRS = [
    _BASE / "data" / "public" / "action_directives",
]


def _is_public_request(request: Request) -> bool:
    """呼び出し元がpublic_app（無認証で外部公開されるポート）経由かを判定する。

    session.router はmain.py（ローカル、フル機能）とpublic_main.py（Cloudflare Tunnel等
    での公開用）の両方に同一インスタンスがマウントされている。dual_run.pyは両アプリを
    同一プロセスに同居させるため、モジュールレベルのグローバル変数では区別できない。
    request.app.state に public_main.py 側だけが立てるフラグを見て判定する。
    """
    return bool(getattr(request.app.state, "is_public_port", False))


def _load_one_directive_file(path: Path) -> tuple[str, dict] | None:
    if path.suffix != ".json" or path.name == ".gitkeep":
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data.get("id", path.stem), data


def _load_action_directives(public_only: bool = False) -> dict:
    directives: dict = {}
    for d in (_PUBLIC_DIRECTIVE_DIRS if public_only else _DIRECTIVE_DIRS):
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            loaded = _load_one_directive_file(f)
            if loaded:
                did, data = loaded
                directives[did] = data
    if "none" not in directives:
        directives["none"] = {"id": "none", "label": "指示なし（キャラクターに任せる）", "directives": {}}
    return directives


@router.get("/action-directives")
def get_action_directives(request: Request):
    directives = _load_action_directives(public_only=_is_public_request(request))
    return {
        "directives": [
            {"id": did, "label": d.get("label", did), "rating": d.get("rating", "general"), "recommended_for": d.get("recommended_for", [])}
            for did, d in directives.items()
        ]
    }


def _load_one_rule_file(path: Path) -> tuple[str, dict] | None:
    if path.suffix != ".json":
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data.get("id", path.stem), data


def _load_session_rules(public_only: bool = False) -> dict:
    rules = {}
    for d in (_PUBLIC_RULE_DIRS if public_only else _RULE_DIRS):
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            loaded = _load_one_rule_file(f)
            if loaded:
                rid, data = loaded
                rules[rid] = data
    if not rules:
        rules["none"] = {"id": "none", "label": "ルールなし", "rules": []}
    return rules


@router.get("/rules")
def get_session_rules(request: Request):
    rules = _load_session_rules(public_only=_is_public_request(request))
    return {
        "rules": [
            {"id": rid, "label": r.get("label", rid)}
            for rid, r in rules.items()
        ]
    }


@router.get("/rules/{rule_id}")
def get_session_rule_detail(rule_id: str, request: Request):
    if not re.match(r'^[A-Za-z0-9_\-]+$', rule_id):
        return {"error": "Invalid rule ID"}
    dirs = _PUBLIC_RULE_DIRS if _is_public_request(request) else _RULE_DIRS
    for d in dirs:
        path = d / f"{rule_id}.json"
        if path.exists():
            try:
                return {"content": path.read_text(encoding="utf-8"), "id": rule_id}
            except OSError as e:
                return {"error": str(e)}
    return {"error": f"Rule '{rule_id}' not found"}


class SaveRuleRequest(BaseModel):
    content: str


@local_router.put("/rules/{rule_id}")
def save_session_rule(rule_id: str, req: SaveRuleRequest):
    if not re.match(r'^[A-Za-z0-9_\-]+$', rule_id):
        return {"error": "Invalid rule ID"}
    try:
        data = json.loads(req.content)
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON: {e}"}
    target: Path | None = None
    for d in _RULE_DIRS:
        path = d / f"{rule_id}.json"
        if path.exists():
            target = path
            break
    if target is None:
        _RULE_DIRS[0].mkdir(parents=True, exist_ok=True)
        target = _RULE_DIRS[0] / f"{rule_id}.json"
    tmp = str(target) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, str(target))
    return {"status": "ok", "id": rule_id}
