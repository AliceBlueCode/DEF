# ルールブックの形（DEF のスキーマの公開用の写し）

DEF の本体の `validate_rulebook`（`def_kari/trpg/rule_engine.py`）が確かめる決まりの写しです。
決まりの本体は DEF の側にあり、食い違ったときは DEF の側が正しいものとします（要求仕様 B-017）。
この写しは `def_original` のルールシステム（`rule_system` を書かないルールブック）向けです。
ほかのルールシステムの決まりは、そのプラグインが決めます。

## 必須の項目

| 項目 | 形 | 決まり |
|---|---|---|
| `rule_system_name` | 文字列 | 画面に出すルールシステムの名前 |
| `dice_system` | 文字列 | `NdM` か `NdM+K`・`NdM-K`（例: `1d100`、`2d6+3`） |
| `judgment` | オブジェクト | `success_condition` は `roll_lte_skill`・`roll_gte_skill`・`roll_lte_stat_x5` のどれか |

## よく使う項目

- `id`・`label`: ルールブックの ID と画面の名前。ID はファイル名（拡張子なし）と同じにします。
- `rule_system`: ルールシステムの ID。書かなければ `def_original` として扱います。
- `stats`・`skills`・`damage_mechanics`: `blank_template.json` と `../def_original/rulebooks/def_original.json` を見本にしてください。

## manifest（`manifest.json`）

| 項目 | 意味 | 無いとき |
|---|---|---|
| `license` | ルールのデータの利用条件 | — |
| `credit` | ルールブックを選ぶ画面とセッションの画面に出す文 | 出さない |
| `external_services_allowed` | 外部の LLM・読み上げ・画像生成に送ってよいか | `def_original` のルールブックは許す。それ以外は許さない |
| `online_sessions` | 招待で人が入る卓で使ってよいか | 同上 |
