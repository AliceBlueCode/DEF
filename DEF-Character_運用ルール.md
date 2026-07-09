# DEF-Character 運用ルール（v2.1.0〜）

> 本文書はDEF-Characterリポジトリの運用方針を定める内部文書です。
> コミュニティルールとしての公式化はv3以降で検討します。

---

## 1. キャラクターの哲学

### キャラクターはプラットフォームから独立した資産である

チャット履歴はプラットフォームに属するが、キャラクターはあなたに属する。
`profile.json` がある限り、プラットフォームが変わっても、サービスが終わっても、そのキャラクターは再び動き出せる。

DEF-Characterはキャラクターの「本籍地」である。

### リポジトリはキャラクターの世界線の宿である

- `profile.json` が人格の中心
- 記憶・日記・関係性は `private/` に置く
- `public/` に出ていいのは人格の輪郭だけ

### プレイヤーはキュレーターである

プレイヤーはキャラクターの「管理者」ではなく「学芸員（Curator）」である。
古い書庫を開くように、そのキャラクターが歩んだ人生に触れる。
キャラクターを消費するのではなく、キャラクターの歴史を保存する。

---

## 2. ディレクトリ構造とファイル配置

```
DEF-Character/
    public/
        <GroupName>/
            index.json              ← グループの表示名・説明
            <CharacterName_YYYYMMDD>/
                profile.json        ← 人格定義（必須）
                icon.png            ← アイコン 512×512（推奨）
                standing.png        ← 立ち絵 832×1216（推奨）
    private/                        ← .gitignore対象
        _template/                  ← テンプレート（コミット対象）
        <YourGroup>/
            index.json
            <CharacterID>/
                profile.json
                ...
```

- `public/` に置けるのは `visibility: "public"` のキャラクターのみ
- `private/` の中はGit管理されない。記憶・個人設定・NSFWデータはここに置く

---

## 3. キャラクターID形式

```
<CharacterName>_<YYYYMMDD>
```

`YYYYMMDD` はそのキャラクターがこの世界に現れた日（誕生日）。

- 例: `Claude_20260611`、`Hanfei_20260611`、`rinna_20260709`
- IDは生成日固定。後から変更しない
- 旧ID形式（`character_xxx_001`）はDEF本体の `data/` にそのまま残すことができる

---

## 4. `owner` フィールド

キャラクターエントリのトップレベルに `owner` を設ける。

```json
{
  "Hanfei_20260611": {
    "owner": "GitHubユーザー名",
    "base_profile": { ... }
  }
}
```

- DRMではなく「このキャラクターを誰が作ったか」の宣言
- GitHubユーザー名を推奨値とする
- `owner` がないエントリは警告のみ（エラーにはしない）

---

## 5. 世界線（ブランチ）運用

キャラクターはGitのブランチとして複数の「世界線」を持てる。

### ブランチID形式

```
<CharacterID>/<WorldlineName>_<YYYYMMDD>
```

例：

```
Hanfei_20260611/Lancer_20260706
Hanfei_20260611/Avenger_20260706
Hanfei_20260611/乙女_20260706
```

### 世界線はマージしない

- ブランチ = もう一つの人生
- マージは行わない
- 世界線は独立したまま存在し続ける

ブランチを切り替えると `public/Hanfei_20260611/` の中身が変わる。
DEF側でのブランチ切り替えUIはv3以降で実装予定。

---

## 6. ID衝突と解決方針

### システム側の動作

同一IDが複数リポジトリで検出された場合：

- エラーにはしない
- ファイルシステム上で先に見つかった方を採用
- もう一方は警告ログに記録
- ユーザーはキャラクターが表示されないことで気づき、手動でIDを変更して解決できる

### 人間側の解決慣例

同じIDを持つキャラクターが並立した場合、クリエイター同士で以下の方法で調整する：

- 名前の後ろに地方名・所属を足す: `HanfeiLondon_20260707`
- 誕生日を1日ずらす: `Hanfei_20260708`

これはシステムのエラーではない。同じ名前（魔法）を持つ別世界線のキャラクターが出会った状態として扱う。
技術的強制（UUID等）は行わない。解決はクリエイター間のコミュニケーションに委ねる。

---

## 7. 公開判定ルール（F-25準拠）

`public/` にコミットできるキャラクターの条件：

| 条件 | 説明 |
|---|---|
| `visibility: "public"` | 必須 |
| `rating_sexual` | `"nsfw"` / `"hentai"` は公開禁止（GitHubの利用規約） |
| `rating_violence` | `"gore"` / `"extreme"` は公開禁止（同上） |
| `appearance_age < 18` | `rating_sexual: "general"` 固定 |
| `is_real_person: true` | `visibility: "private"` 固定。公開不可 |
| `origin_type: "derivative"` | `visibility: "private"` 固定。公開不可 |
| `origin_type: "reconstructed_persona"` | `copyright_expired: true`（没後70年以上）の場合のみ公開可 |
| `origin_type: "personification"` | `ip_title` と `ip_rightholder` が設定されている場合のみ公開可（免責条件付き） |

---

## 8. DEFへの接続

`.env` に以下を追加する：

```
CHARACTER_REPO_PATH=C:\Users\yourname\DEF-Character
```

DEFは起動時に `CHARACTER_REPO_PATH` を優先して読み込む。
旧形式（`data/public/characters/`・`data/private/characters/`）はフォールバックとして継続動作する。

---

> Characters persist longer than conversations.
