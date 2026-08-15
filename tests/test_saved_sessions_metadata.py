"""保存済みセッション一覧（GET /api/session/saved）のオンライン/オフライン・
ルールセット表示テスト。

一覧にセッションルール（漫才、標準等）とオンライン/ローカルの区別が無く、
どのセッションか見分けにくいとの指摘があったため、metadataにonline_modeを
追加し、rule_set/rule_set_labelとあわせて一覧に含めるよう拡張した（2026-08-10）。
"""

from unittest import mock

from fastapi.testclient import TestClient


def test_list_saved_sessions_includes_rule_set_and_online_mode():
    from def_kari.api.main import app

    fake_files = [
        {
            "path": "/fake/session_mode_abc.json",
            "session_id": "abc",
            "private": False,
            "metadata": {
                "topic": "テストお題",
                "saved_at": "20260810_120000",
                "round": 3,
                "name_map": {"a": "Claude"},
                "rule_set": "manzai",
                "online_mode": True,
            },
        },
        {
            "path": "/fake/session_mode_def.json",
            "session_id": "def",
            "private": False,
            "metadata": {
                "topic": "",
                "saved_at": "20260810_110000",
                "round": 1,
                "name_map": {},
                "rule_set": "",
                "online_mode": False,
            },
        },
    ]
    with mock.patch(
        "def_kari.api.routes.session_persistence.list_session_mode_files", return_value=fake_files
    ):
        client = TestClient(app)
        resp = client.get("/api/session/saved")
    assert resp.status_code == 200
    sessions = resp.json()["sessions"]
    assert len(sessions) == 2

    manzai_entry = next(s for s in sessions if s["session_id"] == "abc")
    assert manzai_entry["rule_set"] == "manzai"
    assert manzai_entry["rule_set_label"] == "漫才"
    assert manzai_entry["online_mode"] is True

    local_entry = next(s for s in sessions if s["session_id"] == "def")
    assert local_entry["rule_set"] == ""
    assert local_entry["online_mode"] is False
