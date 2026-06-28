# DEF(kari) Contributing Guide

## 基本方針

DEF(kari) はコアアーキテクチャを1名(オーナー)が設計・実装するプロジェクトです。コミュニティからの貢献を歓迎しますが、受け付けるPRの範囲を明確に定めています。貢献前に本ガイドを必ずお読みください。

## 創作の自由についての考え方

**クリエイターは自分が望むものを自由に創作してよい。ただし、創作物の責任はクリエイター自身が負う。**

DEF(kari)はこの原則に基づいて設計されています。ツールが創作の内容に先回りして介入することはクリエイターの表現の自由を侵害します。DEF(kari)はローカル環境での創作行為に対してコンテンツを検閲・ブロックしません。

DEF(kari)が守るのは**パブリックとプライベートの境界**であり、プライベートな創作行為そのものではありません。

- **プライベート(ローカル環境):** クリエイターの自由が完全に保障される領域。DEF(kari)は一切介入しません。
- **パブリック(外部への公開):** 著作権・公序良俗が適用される領域。`content_policy`・ゾーニング・F-25による技術的支援を提供します。

この考え方はコントリビューションにも適用されます。コンテンツの内容そのものを理由に貢献を拒否することはしません。ただし、以下の技術的・法的要件は守ってください。

- 実在人物・既存著作物キャラクターは`publish_restriction: "private"`とし、PRには含めない
- `content_policy`の必須フィールドをすべて正しく設定する
- 創作物の公開・利用に関する判断と責任はコントリビューター自身が負う

-----

## 受け付けるPR・受け付けないPR

|カテゴリ     |受け付ける                  |受け付けない                                   |
|---------|-----------------------|-----------------------------------------|
|キャラクターデータ|✅ オリジナルキャラクターの追加       |❌ 実在人物・既存著作物キャラクター                       |
|LLMアダプター |✅ 新しいLLMバックエンドのアダプター追加 |❌ 既存アダプターの挙動変更                           |
|TTSアダプター |✅ 新しいTTSバックエンドのアダプター追加 |❌ 既存アダプターの挙動変更                           |
|T2Iアダプター |✅ 新しいT2Iバックエンドのアダプター追加 |❌ 既存アダプターの挙動変更                           |
|翻訳・ロケール  |✅ `locales/`への言語追加     |❌ 既存翻訳キーの削除・変更                           |
|バグ修正     |✅ 軽微なバグ修正(Issue確認済みのもの)|❌ 動作仕様の変更を伴うもの                           |
|ドキュメント   |✅ README・コメントの誤字・補足    |❌ 設計仕様・アーキテクチャの変更提案                      |
|コアロジック   |❌                      |❌ `core/`・`llm/`・`history/`・`safety/`等の変更|
|アーキテクチャ  |❌                      |❌ 設計原則・データ構造・インターフェースの変更                 |

> コアロジック・アーキテクチャに関する提案はIssueとして起票してください。採用するかどうかはオーナーが判断します。

-----

## 1. キャラクターデータの追加

### ファイル配置

キャラクターデータは1キャラクター1ファイルで `data/characters/` 以下に配置してください。

```
data/characters/
  character_<name>_<3桁連番>.json   例: character_hana_001.json
```

キャラクター画像は以下のディレクトリ規約に従ってください。

```
data/characters/<character_id>/
  icon.png       # アイコン画像（512×512）
  standing.png   # 立ち絵画像（832×1216）
```

### 必須フィールド

以下のフィールドがすべて含まれていることを確認してください。

```json
{
  "character_xxx_001": {
    "base_profile": {
      "name": "キャラクター名",
      "name_reading": {
        "family_name": "ミョウジ",
        "given_name": "ナマエ",
        "alias": []
      },
      "player_type": "ai",
      "identity_prompt": "100文字以上のペルソナ説明（どう在るか・内面・性質）",
      "identity_detail": "能力・仕様・背景・経緯等の補足（任意、nullで省略可）",
      "content_policy": {
        "rating_sexual": "general",
        "rating_violence": "general",
        "is_real_person": false,
        "is_existing_ip": false,
        "ip_title": null,
        "ip_rightholder": null,
        "deceased_year": null,
        "copyright_expired": false,
        "publish_restriction": "public",
        "mentions_real_person": false,
        "mentioned_persons": []
      },
      "persona_attributes": {
        "gender": "女 | 男 | その他",
        "gender_identity": "女 | 男 | その他",
        "romantic_interest": [],
        "actual_age": 0,
        "appearance_age": 0,
        "appearance_description": "容姿の説明(服装を含めない)",
        "roles": ["職業・役割"],
        "primary_role": "主役割",
        "past_life": null,
        "outfits": {
          "default": "デフォルトの服装説明"
        },
        "era_presets": null,
        "speech_style": {
          "first_person": "私",
          "address_partner": "あなた",
          "tone": "口調の説明"
        },
        "cultural_background": {
          "birthplace": "出生地",
          "raised_in": "育った場所",
          "dominant_culture": "支配的な文化圏"
        }
      },
      "default_model_config": {
        "text_model_id": 501,
        "image_model_id": 101,
        "audio_id": "vv_default",
        "voicevox_speaker_id": 0,
        "gemini_tts_voice": "Aoede",
        "irodori_speaker_id": null,
        "location": "local"
      },
      "visual_references": {
        "base_image_path": null,
        "features": "T2I向け英語特徴タグ(例: brown hair, blue eyes)",
        "appearance_tags": "T2I向け英語タグ(featuresの別名、どちらか一方でよい)"
      }
    },
    "relationships": {},
    "game_rules_sheets": {}
  }
}
```

### フィールドの使い分け

|フィールド            |書くべき内容      |例                            |
|-----------------|------------|----------------------------|
|`identity_prompt`|どう在るか・内面・性質 |「何かを変換することに純粋な喜びを感じる」       |
|`identity_detail`|何ができるか・背景・仕様|「ネイティブマルチモーダルモデル。最大100万トークン」|

### コンテンツポリシー

- `is_real_person: true` のキャラクターは**受け付けません**。
- `is_existing_ip: true` のキャラクターは**受け付けません**。
- `publish_restriction` は必ず `"public"` にしてください。それ以外は受け付けません。
- `appearance_age` が18未満のキャラクターの `rating_sexual` は必ず `"general"` にしてください。

-----

## 2. LLMアダプターの追加

`def_kari/llm/adapters/` 以下に新しいアダプターを追加してください。

### 要件

- アダプターパターンに従い、`chat()`関数と`make_chat_fn()`ファクトリを実装すること。
- 既存の`tgw.py`・`anthropic.py`の実装を参考にしてください。
- **コアコード(`def_kari/llm/client.py`等)にモデル固有の条件分岐を入れないこと。** モデル固有の処理はすべてアダプター内で完結させてください。
- `data/llm_services.json`にサービス定義を追加してください。
- 対応するモデルプロファイルを`data/llm_profiles/`に追加してください。
- アダプター固有の依存ライブラリは `requirements_optional.txt` に追記してください。
- 動作確認済みの環境(OS・Pythonバージョン)をPR本文に明記してください。

-----

## 3. TTSアダプターの追加

`def_kari/workers/tts_adapters/` 以下に新しいアダプターを追加してください。

### 要件

- 基本設計書2.5節で定義した`synthesize()`インターフェースを実装すること。
- 既存の`VoicevoxAdapter`・`IrodoriTtsAdapter`の実装を参考にしてください。
- アダプター固有の依存ライブラリは `requirements_optional.txt` に追記してください。
- 動作確認済みの環境(OS・Pythonバージョン)をPR本文に明記してください。

```python
class YourTtsAdapter:
    def synthesize(
        self,
        text: str,
        speaker_id: str | int | None,
        adapter_options: dict | None = None
    ) -> bytes:
        """WAVバイト列を返す"""
        ...
```

-----

## 4. T2Iアダプターの追加

`def_kari/workers/t2i_adapters/` 以下に新しいアダプターを追加してください。

### 要件

- 基本設計書2.4節で定義した`generate_image()`インターフェースを実装すること。
- 既存の`A1111Adapter`の実装を参考にしてください。
- アダプター固有の依存ライブラリは `requirements_optional.txt` に追記してください。

-----

## 5. 翻訳・ロケールの追加

`locales/` 以下に言語コードのJSONファイルを追加してください。

```
locales/
  ja.json   # 日本語(基準ファイル)
  en.json   # 追加例
```

- `ja.json` のすべてのキーを含めてください。キーの追加・削除はしないでください。
- 翻訳に自信がない箇所は `"(要確認)"` と記載してください。

-----

## 6. PRの手順

1. このリポジトリをforkする。
1. `develop` ブランチから作業ブランチを切る。

   ```
   git checkout develop
   git checkout -b feature/character-hana
   ```
1. 変更を加えてcommitする。
1. forkしたリポジトリにpushし、`develop` ブランチへのPRを作成する。
1. PR本文に以下を記載する。
- 追加・変更の概要
- 動作確認済みの環境(キャラクターデータの場合は不要)
- 関連するIssue番号(あれば)

-----

## 7. Issue の起票

バグ報告・機能提案はIssueとして起票してください。

- **バグ報告**: 再現手順・環境(OS・Pythonバージョン・使用モデル)・期待する動作・実際の動作を記載してください。
- **機能提案**: コアロジック・アーキテクチャに関わる提案はIssueのみ受け付けます。PRは受け付けません。採用するかどうかはオーナーが判断します。

-----

## 8. ライセンス

本リポジトリのライセンスは別途 `LICENSE` ファイルを参照してください。PRを送ることで、あなたの貢献が本リポジトリのライセンスに従って公開されることに同意したものとみなします。
