# TRPG のテスト用の固定の写し

挙動を固定するテスト（`tests/characterization/`）と、外部のリポジトリに頼らないテストのためのルールブックの写し。
要求仕様 C-005（`DEF_マルチルールブック基盤_要求仕様_内部用.md`）による。

- `public/trpg_rules/def_original.json` と `public/trpg_rules/blank_template.json` は、`data/public/trpg_rules/` から 2026-11-13（`feature/multi-rulebook` の 950134a）に写したもの。
- 本体の側のルールブックが変わっても、この写しは変えない。テストが固定するのは「この写しを読んだときの DEF の挙動」。
- `private/` は、public → private の読み込みの順番を確かめるための空の置き場。

## ライセンス

`def_original` のルールブックは、DEF-Rulebooks へ移すときに CC BY-SA 4.0 とする予定（要求仕様 B-016）。テンプレート（`blank_template.json`）は CC0 とする予定。
この写しは、作者本人が、DEF（AGPL v3）のリポジトリにテスト用として置いたもの。テスト以外の目的で使うときは、元のルールブックのライセンスに従うこと。
