# DEF-Rulebooks の形の固定の写し

CI と E2E が、ネットワークから DEF-Rulebooks を取ってこずに読むための写し（要求仕様 C-005・C-006）。

- `def_rulebooks/`: 集約型。DEF-Rulebooks（https://github.com/AliceBlueCode/DEF-Rulebooks）の `def_original/` と
  `template/` を、2026-11-14 に写したもの。元が変わっても、この写しは変えない（変えるときは理由をコミットに書く）。
- `single_repo/`: 単体型（直下に `manifest.json`）の読み込みを確かめるための、テスト用の小さなルールブック。

## ライセンス

`def_rulebooks/def_original/` は CC BY-SA 4.0、`def_rulebooks/template/` は CC0 1.0（各フォルダの `LICENSE`）。
この写しは、作者本人が、DEF（AGPL v3）のリポジトリにテスト用として置いたもの。テスト以外の目的で使うときは、
元のフォルダのライセンスに従うこと。`single_repo/` は CC0 1.0。
