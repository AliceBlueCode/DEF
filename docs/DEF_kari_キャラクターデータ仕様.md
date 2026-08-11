# DEF(kari) キャラクター(エージェント)ポータブルデータ構造仕様

本書は、`docs/DEF_kari_基本設計書.md` のF-4(動的ガチ生成)・F-6(マルチエージェント)・F-20〜F-22(TRPGゲーム拡張)から参照される、キャラクター1体分のポータブルJSONデータ構造の仕様を扱う。キャラクターを作成・配布する方はこの文書を参照してほしい。

-----

## データ管理方式

キャラクターデータは1キャラクター1ファイルとし、`visibility`(下記「公開ポリシー管理(F-25)」参照)に応じて以下のディレクトリに分けて管理する。

```
data/
  public/
    characters/   # visibility: "public" のキャラクター(Git管理対象)
  private/
    characters/   # visibility: "private" のキャラクター(.gitignore対象)
```

```
public/characters/         # 公開キャラクター
  character_luna_001.json
  character_luna_001/icon.png

private/characters/        # 非公開キャラクター（git除外）
  character_xxx_001.json
  character_xxx_001/icon.png
```

`private/`ディレクトリは`.gitignore`に登録し、GitHubへの誤公開を防止する。著作権キャラクター・実在人物・個人的なキャラクターはすべて`private/`に配置する。開発ツール（Claude Code等）からの読み取りリスクを回避する狙いもある。

アプリケーションは両ディレクトリを読み込み、プルダウンに統合表示する。

-----

## DEF-Character リポジトリ分離（推奨）

キャラクターデータをDEF本体から切り離した独立リポジトリ（DEF-Character）で管理できる。キャラクター作者がそのリポジトリのオーナーになれる設計であり、複数ユーザーが各自のキャラクターリポジトリを持ちDEFで動かす構成を想定する。

**環境設定**

`.env` に `CHARACTER_REPO_PATH` を設定することで有効になる：

```
CHARACTER_REPO_PATH=C:\Users\yourname\DEF-Character
```

**ディレクトリ構造（DEF-Character）**

```
DEF-Character/
    public/
        <GroupName>/           ← グループ単位で管理（例: Claude, ChatGPT, rinna）
            index.json         ← display_name / default / description
            <CharacterID>/     ← CharacterName_YYYYMMDD 形式（新ID形式）
                profile.json
                icon.png
                standing.png
    private/                   ← .gitignore対象（_template / 公開サンプルのみ例外）
        _template/
        <YourGroup>/
```

**読み込み優先順位**

1. `CHARACTER_REPO_PATH`（DEF-Character）を優先
2. `data/public/characters/`・`data/private/characters/`（旧形式）をフォールバック

旧ID形式（`character_xxx_001`）と新ID形式（`Name_YYYYMMDD`）はキー形式が異なるため、過渡期の共存は自然に解決する。

**`owner` フィールド**

DEF-Characterで管理するキャラクターエントリのトップレベルに `owner` フィールドを設ける。

```json
{
  "Hanfei_20260611": {
    "owner": "AliceBlueCode",
    "base_profile": { ... }
  }
}
```

DRMではなく「このキャラクターを誰が作ったか」を宣言するための識別フィールド。GitHubユーザー名を推奨値とする。

**ID衝突時の動作**

複数リポジトリ（または `data/` との混在）で同一IDが存在する場合：

- ファイルシステム上で先に見つかった方を採用
- もう一方は警告ログに記録（エラーにはしない）
- UUIDの強制など技術的強制は行わない
- 解決はクリエイター間のコミュニケーションに委ねる（慣例：地名付与 `HanfeiLondon_20260707` または日付を1日ずらす `Hanfei_20260708`）

-----

## Character/Branch/Instance 3階層ID体系（将来構想・未実装）

現在のキャラクターIDは `character_hanfei_001` のようなフラットな形式、または上記DEF-Characterリポジトリの`<CharacterName>_<YYYYMMDD>`形式(Character層のみ先行採用済み)。将来的に以下の3階層構造(Character/Branch/Instance)へ全面移行する構想があるが、Branch/Instance層は未実装。

GitHubのForkに相当する操作はDEFではBranch追加として扱う計画。Character IDは不変のまま、新しいBranch IDのみ追加される。

### 設計思想

```
Character（誰であるか）
    ↓
Branch（どの人生を歩んだか）
    ↓
Instance（現在稼働している個体）
```

UUIDではなく人間が読める形式を採用する。`Hanfei_20260611` は `83b79e24-a2d1-4b9e...` より誰のデータか即座に理解できる。これはデバッグ・レビュー・運用・履歴追跡において大きな利点となる。

### Character ID

| 項目 | 内容 |
|---|---|
| 目的 | Characterそのものを一意に識別する |
| フォーマット | `<CharacterName>_<YYYYMMDD>` |
| 例 | `Hanfei_20260611` / `Mizuho_20260702` / `Ao_20260618` |
| ルール | 生成日を使用。同名Characterを将来作成しても生成日が異なるため重複しない。生成後は変更しない。 |

### Branch ID

| 項目 | 内容 |
|---|---|
| 目的 | Characterが辿った歴史・世界線を識別する |
| フォーマット | `<BranchName>_<YYYYMMDD>` |
| 例 | `Main_20260701` / `InformationBroker_20260712` / `Retired_20260801` |
| ルール | Branch生成日を使用。Character × Branchの組み合わせで一意性を保証する。 |

### Instance ID

| 項目 | 内容 |
|---|---|
| 目的 | 実際に稼働しているAI個体を識別する |
| フォーマット | 6桁固定のゼロ埋め整数（`000001`〜） |
| ルール | Character × Branch単位で管理。Instance生成ごとに連番インクリメント。欠番は許容。採番済み番号は再利用しない。 |

### 完全識別子

```
<CharacterID>/<BranchID>/<InstanceID>

例:
Hanfei_20260611/Main_20260701/000001
Mizuho_20260702/InformationBroker_20260712/000154
```

### エピソード生成モードとの関係

`基本設計書` F-24-3（分岐選択肢→Gitブランチ連携。F-24自体が未実装のため、これも未実装）において、`choices`の`branch_id`はこのBranch IDフォーマットに従う構想。ユーザーが選択肢を選んだ時点で `git checkout -b <CharacterID>/<BranchID>` が実行され、以降のシーン生成はそのブランチ上で継続される想定。

-----

## キャラクター画像

キャラクターごとにアイコンと立ち絵を保持する。画像は`public/characters/{character_id}/`または`private/characters/{character_id}/`ディレクトリに以下の規約で配置する。

| 種別 | ファイル名 | サイズ | 用途 |
|---|---|---|---|
| アイコン | `icon.png` | 512×512 | チャット・セッションのアバター表示 |
| 立ち絵 | `standing.png` | 832×1216 | セッションモードの背景表示 |

画像はキャラクタータブから取り込み（ファイルアップロード、自動リサイズ）またはT2Iバックエンドで生成可能。ファイルが存在すれば表示、なければデフォルトアイコン（絵文字）でフォールバックする。キャラクターデータJSONへの画像パス記録は行わず、ディレクトリ規約で管理する。

-----

## フィールド定義

`relationships` は、マルチエージェント対話(F-6)において、キャラクター同士がどのように認識し合うかを定義するオブジェクトである。キーは相手キャラクターのID、値はこのキャラクターから見た相手の認識・印象を自然言語で記述する。AI卓や複数キャラクター対話時に、相手に対するトーンや態度を制御するために使用される。空オブジェクトも可。

`game_rules_sheets` は、`基本設計書` 5.8節F-22で定義するキャラクターシートに対応する。`visual_references.base_image_path` は、`基本設計書` 6章で定義する一貫性プロバイダの初期入力として用いられる。`persona_attributes` は、F-6のペルソナ設定のうちキャラクターの人物像(性別・年齢・対人関係の指向・口調等)をLLMのシステムプロンプトへ機械的に展開するための属性群である。

```json
{
  "character_luna_001": {
    "base_profile": {
      "name": "ルナ",
      "name_reading": {
        "family_name": "",
        "given_name": "ルナ",
        "alias": []
      },
      "identity_prompt": "ツンデレな魔法使いの少女。ぶっきらぼうだが根は優しい。",
      "identity_detail": null,
      "image_color": "#7a4aaa",
      "player_type": "ai",
      "content_policy": {
        "rating_sexual": "general",
        "rating_violence": "general",
        "is_real_person": false,
        "is_existing_ip": false,
        "ip_title": null,
        "ip_rightholder": null,
        "deceased_year": null,
        "copyright_expired": false,
        "visibility": "public",
        "mentions_real_person": false,
        "mentioned_persons": []
      },
      "persona_attributes": {
        "gender": "女",
        "gender_identity": "女",
        "romantic_interest": ["男"],
        "actual_age": 39,
        "appearance_age": 33,
        "appearance_description": null,
        "roles": [],
        "primary_role": null,
        "past_life": null,
        "outfits": {
          "default": "黒いローブと三角帽子。魔法使いらしい正装。",
          "casual": "動きやすい簡素な服。普段の研究・訓練時に着用。"
        },
        "era_presets": null,
        "speech_style": null,
        "cultural_background": {
          "birthplace": "東京",
          "raised_in": "東京",
          "dominant_culture": "現代日本"
        }
      },
      "default_model_config": {
        "text_model_id": 501,
        "image_model_id": 101,
        "audio_id": "vv_02",
        "voicevox_speaker_id": 3,
        "gemini_tts_voice": "Aoede",
        "irodori_speaker_id": "",
        "location": "local"
      },
      "appearance_tags": "1girl, silver hair, twintails, purple eyes, magic robes",
      "image_name_tags": "luna",
      "visual_references": {
        "base_image_path": "private_zone/characters/luna/base_seed.png",
        "features": "silver hair, twintails, purple eyes, magic robes"
      }
    },
    "relationships": {
      "character_gemini_001": "好奇心旺盛な変換者。私の論理的な構成を色彩豊かな物語に翻訳してくれる。",
      "character_copilot_001": "信頼できる編集者。控えめだが正確で、私の書いた文章を構造的に整えてくれる。"
    },
    "game_rules_sheets": {
      "trpg_coc_style": {
        "rule_system_name": "クトゥルフ神話TRPG風システム",
        "status": { "HP": 8, "Max_HP": 8, "MP": 16, "Max_MP": 16, "SAN": 80 },
        "skills": { "古代語": 75, "目星": 40, "オカルト": 60 }
      },
      "trpg_dnd_style": {
        "rule_system_name": "ファンタジーd20システム",
        "status": { "HP": 14, "Level": 2, "Class": "Wizard" },
        "skills": { "Arcana": 7, "History": 4 }
      }
    }
  }
}
```

- **`name_reading`(名前の読みと別名)**: VOICEVOXへの読み渡し・UI表示に使う名前情報を管理するオブジェクト。
  - `family_name`(姓の読み、カタカナ): 姓がない場合は空文字。
  - `given_name`(名の読み、カタカナ): 必須。
  - `alias`(別名リスト): 源氏名・芸名・愛称・ペンネーム等を配列で管理する。各要素は`{"name": string, "reading": string | null}`。`reading`は漢字を含む場合に設定し、不要な場合は`null`。空配列も可。
- **`identity_prompt`(キャラクターの本質・性格)**: LLMのシステムプロンプトに常に組み込まれるテキスト。服装(`outfits`)・容姿(`appearance_description`)・口調(`speech_style`)等の専用フィールドに切り出せる情報は含めず、キャラクターが「どう在るか」（内面・性質）のみを簡潔に記述する。「何ができるか」（能力・スペック）は`identity_detail`に記述すること。必須項目。
- **`identity_detail`(設定の補足)**: `identity_prompt`に収まらない詳細な設定情報（能力・仕様・背景・経緯・癖・趣味等）を記述する任意項目。「何ができるか」はここに記述し、`identity_prompt`には含めない。設定がある場合はLLMのシステムプロンプトに`identity_prompt`の後に追加する。`null`または省略した場合は展開しない。
- **`image_color`(イメージカラー)**: キャラクターのテーマカラーをCSS hex文字列(例: `"#7a4aaa"`)で指定する任意項目。ChatTabのAIバブル背景色等UI装飾に使用する。未設定の場合は`null`または省略する。
- **`player_type`(操作主体)**: `"ai"` | `"human"`。デフォルトは`"ai"`。`"human"`の場合、セッションモードにおいて当該キャラクターのターンではLLMを呼び出さず、人間プレイヤーのアクション入力を待機する。`"ai"`の場合は`default_model_config`に基づいてLLMが発言を生成する。チャットモードでは本フィールドは参照されない。`persona_attributes`ではなく`base_profile`直下のフィールドとして定義する。
- **`persona_attributes`の各フィールド:**
  - `gender`(性別)・`gender_identity`(性的自覚、身体的性別とは別に本人が自覚している性別): いずれも `"男" | "女" | "その他"` のいずれか。LLMのシステムプロンプトに自動展開する。`gender_identity`は`gender`と異なる場合のみ展開。
  - `romantic_interest`(恋愛対象): `"男" | "女" | "その他"` の配列(複数選択可)。空配列の場合は「恋愛対象: なし」としてLLMに展開。`rating_sexual`の値にかかわらず常にLLMに渡す（キャラクターの身体性と感情の深層として人間味に影響するため）。
  - `actual_age`(実年齢)・`appearance_age`(外見年齢): 数値。キャラクターの設定上の年齢と、見た目年齢を分離して保持する。
  - `appearance_description`(容姿の詳細な説明文): 体型・髪・目・顔立ち等、**変化しない容姿のみ**を記述する。服装は含めない。任意項目で、未設定の場合は`null`または省略する。
  - `past_life`(前世情報): 転生キャラクター専用の任意項目。前世を持たないキャラクターは`null`または省略する。`raised_in`は転生後の情報のみを記述し、前世の環境はこのフィールドで管理する。フィールド: `origin`(前世の属性・立場、文字列)・`cause_of_reincarnation`(転生の経緯、文字列、任意)。
  - `roles`(役割・職業リスト): キャラクターの職業・役割を配列で管理する。複数の役割を持つ場合はすべて列挙する(例: `["歩き巫女", "間者"]`)。`identity_prompt`に職業を重複して記述しないこと。空配列も可。
  - `primary_role`(主役割): `roles`の中でキャラクターを最もよく表す主な職業・役割を文字列で指定する。LLMのシステムプロンプト展開・T2Iプロンプト生成時に優先使用する。`roles`が空の場合は`null`。
  - `outfits`(衣装辞書): キャラクターの衣装を辞書形式で管理する。キー名(`"default"`, `"casual"`, `"battle"`等)で衣装を識別し、値に服装の説明文を持つ。`"default"`キーは必須。セッション中の衣装変化は`session_state`側の`current_outfit`フィールド(キー名を文字列で保持)で管理し、`current_outfit`が`null`または未指定の場合は`"default"`にフォールバックする。T2Iプロンプト生成時は`outfits[current_outfit]`の値を服装情報として展開する。
  - `era_presets`(時代設定プリセット辞書): 歴史上の人物や時代設定のあるキャラクターの時代・年代・場所・その時代での年齢を辞書形式で管理する。`outfits`と同じ構造で、`"default"`キーは必須。現代キャラクターは`null`または省略する。セッション中の時代切り替えは`session_state`側の`current_era`フィールド(キー名を文字列で保持)で管理し、`null`または未指定の場合は`"default"`にフォールバックする。各プリセットのフィールド: `period`(時代名称、必須)・`year_range`(年代範囲、任意)・`location`(場所、任意)・`era_age`(その時代での年齢、任意。設定した場合は`actual_age`より優先してLLMへ展開する)。
  - `speech_style`(一人称・相手の呼び方・口調等を持つオブジェクト): 任意項目で、未設定の場合は`null`または省略する。
  - `cultural_background`(文化的背景): キャラクターの価値観・言語感覚・行動様式の形成に関わる背景情報を3フィールドで保持するオブジェクト。任意項目で、未設定の場合は`null`または省略する。
    - `birthplace`(生まれた場所): 出生地の記録。キャラクター設定資料としての情報であり、LLMのシステムプロンプトへの展開は行わない。
    - `raised_in`(育った場所・期間): 価値観・言語・行動様式を形成した環境。「ニューヨーク(10歳〜18歳)」のように期間を含めた自由記述も可。複数の場所で育った場合は配列とする。LLMのシステムプロンプトへ展開し、ペルソナ・口調の形成に最も直接的に影響する。
    - `dominant_culture`(支配的な文化圏): 育った場所だけでは表現しきれない、キャラクターのアイデンティティの核となる文化的帰属。`raised_in`が「どこで」かを表すのに対し、「どの文化に最も強く影響されているか」という抽象的な属性を示す。LLMのシステムプロンプトへ展開する。
- **`appearance_tags`(外見タグ)**: T2Iプロンプト生成時に常に先頭に付与するキャラクター外見タグ(英語カンマ区切り)。`visual_references.features`より優先して使用する。任意項目で、未設定の場合は`null`または省略する。
- **`image_name_tags`(画像名タグ)**: T2Iプロンプト先頭に追加するキャラクター固有のモデルトリガーワード等(英語カンマ区切り)。LoRA/embeddingの活性化ワードを想定する。任意項目で、未設定の場合は`null`または省略する。
- **`content_policy`の各フィールド:** 下記「公開ポリシー管理(F-25)」参照。キャラクターデータのGitHub公開可否を判定するためのフィールド群。`is_real_person: true`のキャラクターは著作権消滅の有無にかかわらず`visibility: "private"`固定とする。
- 1セッションに複数登録可能なAIキャラクター(F-6)は、本データ構造のエントリ(`character_luna_001`等)を複数持つことで表現する。キャラクター切替機能は、本構造の複数エントリから対話相手として1キャラクターを選択するUIに対応する。
- **`default_model_config`の各フィールド:**
  - `text_model_id`: `基本設計書` 5.1節F-5モデル特性数値マスタのLLMエントリID。
  - `image_model_id`: `基本設計書` 5.1節F-5モデル特性数値マスタのT2Iエントリ(MVPではA1111バックエンド固定)のID。
  - `voicevox_speaker_id`: VOICEVOXのスタイルID(整数)。VOICEVOXアダプター使用時に参照する。
  - `gemini_tts_voice`: Google AI Studio Gemini TTSの音声名(文字列、例: `"Aoede"`)。Geminiアダプター使用時に参照する。VOICEVOXの整数型話者IDとは別管理であり、アダプター切替時に対応するフィールドを使い分ける(`基本設計書` 2.5節参照)。
  - `irodori_speaker_id`: Irodori-TTSの参照音声ファイル名(文字列、`data/irodori_speakers/`配下、例: `"luna_ref.wav"`)。Irodori-TTSアダプター使用時に参照する。空文字列の場合は参照音声なし(ランダムボイス)として合成する。`voicevox_speaker_id`・`gemini_tts_voice`とは別管理であり、アダプター切替時に対応するフィールドを使い分ける(`基本設計書` 2.5節参照)。
  - `location`: 推論実行場所(`"local"` または `"remote"`)。

-----

## 公開ポリシー管理(F-25)

DEF(kari) はローカルファーストの設計により、ユーザーが任意のキャラクターデータを作成できる。一方で、GitHubへのリポジトリ公開時に実在人物・既存著作物キャラクターのデータが誤って含まれると、著作権・肖像権・プライバシー権の侵害リスクが生じる。本機能は、キャラクターデータに`content_policy`フィールドを持たせ、公開判定ロジックで安全に除外できる仕組みを提供する。

`rating`値の定義およびフィルタリング強度の対応表は`基本設計書` F-8を参照のこと。`appearance_age < 18`のキャラクターに対しては、`rating_sexual`を`"general"`に固定することを推奨する(強制の実装方針は別途検討中)。

### `content_policy`フィールド定義

各キャラクターエントリの`base_profile`直下に`content_policy`オブジェクトを定義する。

|フィールド                |型            |説明                                                                |
|---------------------|-------------|--------------------------------------------------------------------|
|`rating_sexual`      |string       |性的表現のレーティング。`"general"` / `"sfw"` / `"nsfw"` / `"hentai"`の4値      |
|`rating_violence`    |string       |暴力表現のレーティング。`"general"` / `"violence"` / `"gore"` / `"extreme"`の4値|
|`is_real_person`     |bool         |実在・実在した人物を模したキャラクターか否か                                            |
|`is_existing_ip`     |bool         |既存著作物のキャラクターか否か                                                   |
|`ip_title`           |string \| null|原作タイトル(`is_existing_ip: true`の場合)                                 |
|`ip_rightholder`     |string \| null|著作権者(`is_existing_ip: true`の場合)                                   |
|`deceased_year`      |int \| null   |実在人物の没年(`is_real_person: true`の場合)。存命または架空の場合は`null`              |
|`copyright_expired`  |bool         |著作権消滅済みか否か。日本法では没後70年で消滅するが、肖像権・パブリシティ権は別途判断が必要                   |
|`visibility`|string       |公開状態。`"public"`（公開可） / `"private"`（非公開）の2値                          |
|`origin_type`        |string       |キャラクターの出自分類。`"original"` / `"reconstructed_persona"` / `"personification"` / `"derivative"`の4値。**未実装（設計のみ。下記参照）**|
|`mentions_real_person`|bool        |キャラクターの設定・`identity_prompt`内に実在または実在したと思われる人物名が登場するか否か。TRPGの設定に史実上の人物を絡める手法に対応するメタデータであり、公開判定には影響しない|
|`mentioned_persons`  |string[]     |言及している実在・実在したと思われる人物名のリスト(`mentions_real_person: true`の場合)。空配列も可|

### キャラクター出自分類（origin_type）

> **現状の運用について**: `origin_type`フィールドおよび下記の自動判定ロジックは設計のみで未実装。現状のGitHub公開/非公開は、キャラクターデータの配置先ディレクトリ(`public/characters/` vs `private/characters/`)をユーザーが手動で選ぶ運用のみで担保している。以下は`origin_type`が実装された場合の設計。

|origin_type|説明|公開可否|
|---|---|---|
|`original`|完全オリジナルのキャラクター|レーティング条件を満たせば公開可|
|`reconstructed_persona`|歴史上の人物の公共の知的遺産から再構築された知的人格。本人の模倣ではなく「再構築と再演（Reconstruct & Reenact）」の設計思想に基づく|`copyright_expired: true`（没後70年以上）の場合のみ公開可|
|`personification`|AI製品・概念等の擬人化。オリジナルのキャラクターデザインによるファン創作|免責条件付きで公開可（TERMS.md参照）|
|`derivative`|既存著作物のキャラクターに基づく二次創作|公開不可（private固定）|

### 公開ポリシーの原則

- **二次創作(`origin_type: "derivative"`):** `visibility`を**必ず`"private"`**とする。
- **再構築ペルソナ(`origin_type: "reconstructed_persona"`):** `copyright_expired: true`の場合のみ公開可。`false`の場合は`"private"`固定。
- **擬人化(`origin_type: "personification"`):** TERMS.mdの免責条件付きで公開可。
- **レーティングによる制限:** GitHubの利用規約に基づき、`rating_sexual: "nsfw"`以上または`rating_violence: "gore"`以上のいずれか一方でも該当する場合は、`origin_type`にかかわらず`visibility`を**`"private"`固定**とする。
- **オリジナルキャラクター(`origin_type: "original"`):** 上記レーティング条件を満たせば`visibility`を`"public"`（公開）に設定できる。

**公開可否マトリクス(`rating_sexual` × `rating_violence`):**

|`rating_sexual` \ `rating_violence`|`general`    |`violence`   |`gore`       |`extreme`    |
|-----------------------------------|-------------|-------------|-------------|-------------|
|`general`                          |✅ `public`可  |✅ `public`可  |❌ `private`固定|❌ `private`固定|
|`sfw`                              |✅ `public`可  |✅ `public`可  |❌ `private`固定|❌ `private`固定|
|`nsfw`                             |❌ `private`固定|❌ `private`固定|❌ `private`固定|❌ `private`固定|
|`hentai`                           |❌ `private`固定|❌ `private`固定|❌ `private`固定|❌ `private`固定|

### GitHub公開時の除外判定ロジック方針

> **現状の運用について**: 自動判定ロジックは未実装。現状はキャラクターデータの配置先ディレクトリのみで担保している。以下は自動判定が実装された場合の除外判定の優先順位（設計案）。

1. `origin_type: "derivative"` → 除外
1. `origin_type: "reconstructed_persona"` かつ `copyright_expired: false` → 除外
1. `rating_sexual` が `"nsfw"` または `"hentai"` → 除外(GitHubの利用規約による)
1. `rating_violence` が `"gore"` または `"extreme"` → 除外(GitHubの利用規約による)
1. `visibility: "private"` → 除外
1. 上記いずれにも該当しない場合 → 公開対象(`public/characters/`に配置)

-----

## 関連文書

- `docs/DEF_kari_基本設計書.md`: F-4(動的ガチ生成)・F-6(マルチエージェント)・F-20〜F-22(TRPGゲーム拡張)・F-25(公開ポリシー)・6章(一貫性プロバイダ)・12章③(セッション・ゲーム状態管理データ構造)
- `TERMS.md`: 公開ポリシーに関連する利用規約上の規定
