"""8.26対策: def_kari/gm/context_builder.py の load_trpg_rulebook/load_trpg_scenario が
クライアント指定のID（POST /api/session/start の trpg_rulebook/trpg_scenario 等）を
そのままファイル名に使っており、IDの形式検証が一切無かった（パストラバーサル・
絶対パス注入で data/private/ や任意の.jsonファイルを読み込めた）。
"""

from pathlib import Path

from def_kari.gm import context_builder


def _setup_dirs(tmp_path, monkeypatch):
    public_dir = tmp_path / "public" / "trpg_rules"
    private_dir = tmp_path / "private" / "trpg_rules"
    public_dir.mkdir(parents=True)
    private_dir.mkdir(parents=True)
    (public_dir / "sample.json").write_text('{"label": "public rulebook"}', encoding="utf-8")
    (private_dir / "secret.json").write_text('{"label": "private rulebook"}', encoding="utf-8")
    dirs = [public_dir, private_dir]
    monkeypatch.setattr(context_builder, "_TRPG_RULEBOOK_DIRS", dirs)
    monkeypatch.setattr(context_builder, "_PUBLIC_TRPG_RULEBOOK_DIRS", [public_dir])
    return public_dir, private_dir, dirs


def test_load_trpg_rulebook_public_only_excludes_private_dir(tmp_path, monkeypatch):
    """8.28対策: public_only=True（public_app経由の/start等）ではdata/private/を
    検索対象から除外すること。public_only=False（従来どおり、ローカル専用ポート・
    セッション内部の再読み込み）はprivateも引き続き見える。"""
    _setup_dirs(tmp_path, monkeypatch)
    assert context_builder.load_trpg_rulebook("secret", public_only=True) == {}
    assert context_builder.load_trpg_rulebook("secret", public_only=False) == {"label": "private rulebook"}
    assert context_builder.load_trpg_rulebook("sample", public_only=True) == {"label": "public rulebook"}


def test_load_trpg_rulebook_valid_id_still_works(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    assert context_builder.load_trpg_rulebook("sample") == {"label": "public rulebook"}


def test_load_trpg_rulebook_finds_private_dir_by_normal_id(tmp_path, monkeypatch):
    """private dirも正規のID経由なら引き続き読める（従来通りのゲーム内挙動）。"""
    _setup_dirs(tmp_path, monkeypatch)
    assert context_builder.load_trpg_rulebook("secret") == {"label": "private rulebook"}


def test_load_trpg_rulebook_rejects_traversal_id(tmp_path, monkeypatch):
    public_dir, private_dir, _ = _setup_dirs(tmp_path, monkeypatch)
    assert context_builder.load_trpg_rulebook("../private/trpg_rules/secret") == {}
    assert context_builder.load_trpg_rulebook("..%2Fprivate%2Ftrpg_rules%2Fsecret") == {}


def test_load_trpg_rulebook_rejects_absolute_path_injection(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    outside = tmp_path / "outside.json"
    outside.write_text('{"label": "outside base dir"}', encoding="utf-8")
    # OSに関わらずスラッシュ形式の絶対パスも拒否されることを確認
    assert context_builder.load_trpg_rulebook(str(outside)[:-5]) == {}


def test_load_trpg_rulebook_rejects_dotted_and_slashed_ids(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    for bad_id in ["../secret", "a/b", "a\\b", "a.b", "", "   "]:
        assert context_builder.load_trpg_rulebook(bad_id) == {}


def test_load_trpg_rulebook_missing_id_returns_empty(tmp_path, monkeypatch):
    _setup_dirs(tmp_path, monkeypatch)
    assert context_builder.load_trpg_rulebook("does_not_exist") == {}


def test_load_trpg_scenario_rejects_traversal_id(tmp_path, monkeypatch):
    public_dir = tmp_path / "public" / "trpg_scenarios"
    private_dir = tmp_path / "private" / "trpg_scenarios"
    public_dir.mkdir(parents=True)
    private_dir.mkdir(parents=True)
    (private_dir / "hidden_npc.json").write_text(
        '{"npcs": [{"id": "n1", "knowledge": ["gm-only secret"]}]}', encoding="utf-8"
    )
    monkeypatch.setattr(context_builder, "_TRPG_SCENARIO_DIRS", [public_dir, private_dir])
    monkeypatch.setattr(context_builder, "_PUBLIC_TRPG_SCENARIO_DIRS", [public_dir])

    assert context_builder.load_trpg_scenario("../private/trpg_scenarios/hidden_npc") == {}
    # 正規のIDなら引き続き読める（従来通り）
    assert context_builder.load_trpg_scenario("hidden_npc")["npcs"][0]["id"] == "n1"


def test_load_trpg_scenario_public_only_excludes_private_dir(tmp_path, monkeypatch):
    """8.28対策: /startのtrpg_scenarioがpublic_app経由でも通常IDでprivateシナリオの
    npc.knowledge等を取り込めた件。public_only=Trueならprivateディレクトリのシナリオは
    正規IDでも読めなくなること。"""
    public_dir = tmp_path / "public" / "trpg_scenarios"
    private_dir = tmp_path / "private" / "trpg_scenarios"
    public_dir.mkdir(parents=True)
    private_dir.mkdir(parents=True)
    (private_dir / "hidden_npc.json").write_text(
        '{"npcs": [{"id": "n1", "knowledge": ["gm-only secret"]}]}', encoding="utf-8"
    )
    monkeypatch.setattr(context_builder, "_TRPG_SCENARIO_DIRS", [public_dir, private_dir])
    monkeypatch.setattr(context_builder, "_PUBLIC_TRPG_SCENARIO_DIRS", [public_dir])

    assert context_builder.load_trpg_scenario("hidden_npc", public_only=True) == {}
    assert context_builder.load_trpg_scenario("hidden_npc", public_only=False)["npcs"][0]["id"] == "n1"
