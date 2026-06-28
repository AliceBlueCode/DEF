# DEF(kari) — マルチモーダルAI創作プラットフォーム

> **Dialogue × Emotion × Fable**
> あなたのキャラクターと、何年でも、何処にでも、一緒に。

-----

## DEF(kari)とは

DEF(kari)は、テキスト・音声・画像を統合したローカルファーストのAI創作プラットフォームです。

クラウドサービスの利用規約やコンテンツポリシーに創作内容を委ねるのではなく、あなた自身の環境で、あなた自身の手で、あなたが望むキャラクターと物語を生成し続けるための基盤を提供します。

-----

## 創作の自由についての考え方

**クリエイターは自分が望むものを自由に創作してよい。ただし、創作物の責任はクリエイター自身が負う。**

DEF(kari)はこの原則に基づいて設計されています。

ツールが創作の内容に先回りして介入することは、クリエイターの表現の自由を侵害します。DEF(kari)はローカル環境での創作行為に対してコンテンツを検閲・ブロックしません。

### パブリックとプライベートの明確な分離

DEF(kari)が守るのは**パブリックとプライベートの境界**であり、プライベートな創作行為そのものではありません。

**プライベート(ローカル環境での創作):**
クリエイターの自由が完全に保障される領域です。DEF(kari)はここに一切介入しません。セーフティフィルター(F-8)はあくまで「表示制御のツール」であり、ユーザーがオフにできます。生成そのものを止めることはしません。プライベートな創作の内容・範囲はすべてクリエイター自身が決めることであり、ツールが制限すべきものではありません。

**パブリック(GitHubや外部への公開):**
社会的なルール・著作権・公序良俗が適用される領域です。DEF(kari)は`content_policy`フィールド・ゾーニング(F-16)・公開判定スクリプト(F-25)によって、クリエイターが意図せずプライベートなコンテンツを公開してしまわないよう技術的に支援します。ただし公開・非公開の最終判断もクリエイター自身が行います。

DEF(kari)がツールとして担う責任はこの**境界を守る仕組みの提供**に限定されます。プライベートな創作の自由を制限することは、DEF(kari)の設計原則に反します。

創作の内容・公開・利用に関する判断と責任は、すべてクリエイター自身に帰属します。

-----

## スクリーンショット

### チャットモード
![Chat](docs/images/chat.png)

### セッションモード
![Session](docs/images/session.png)

### エピソードモード
![Episode](docs/images/episode.png)

### キャラクター
![Character](docs/images/character.png)

-----

## 主な特徴

- **3モダリティの統合:** テキスト・音声・画像が一つの対話として連続して動く
- **3つのモード:** チャット（1対1対話）・セッション（複数AI＋人間の卓）・エピソード（小説執筆＋AI候補生成）
- **継続的存在感:** 対話履歴・感情・生成アセットが永続化され、再起動後も「続き」から再開できる
- **ローカルファースト:** LLM・TTS・T2Iすべてをローカルで完結。外部APIへのフォールバックも対応
- **アダプターパターン:** LLM×4・TTS×4・T2I×4のバックエンドを自由に差し替え可能
- **ゾーニング:** 公開データとプライベートデータの明確な分離。生成アセットはGit管理対象外

-----

## 必要な環境

- Python 3.10+
- LLMバックエンド（いずれか1つ以上）:
  - [Text Generation WebUI](https://github.com/oobabooga/text-generation-webui) — デフォルト
  - [Ollama](https://ollama.com/)
  - OpenAI / Google Gemini / Anthropic Claude API
- TTSバックエンド（いずれか1つ以上）:
  - [VOICEVOX](https://voicevox.hiroshiba.jp/) — デフォルト
  - [Kokoro TTS](https://github.com/hexgrad/kokoro)
  - Irodori-TTS / Gemini TTS API
- T2Iバックエンド（いずれか1つ以上）:
  - [Automatic1111 WebUI](https://github.com/AUTOMATIC1111/stable-diffusion-webui) — デフォルト
  - [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
  - Hugging Face Inference / Civitai API

-----

## セットアップ

```bash
git clone https://github.com/AliceBlueCode/DEF.git
cd DEF
pip install -r requirements.txt
cp .env.example .env   # バックエンドのディレクトリパス等を設定
streamlit run def_kari/app.py
```

-----

## ライセンス

本ソフトウェアは [GNU Affero General Public License v3.0 (AGPL v3)](https://www.gnu.org/licenses/agpl-3.0.html) のもとで配布されます。

Copyright (C) 2026 AliceBlueCode

- 自由に使用・改造・配布できます
- 改造版を配布する場合はソースコードをAGPL v3で公開する義務があります
- 改造版をネットワーク経由で提供する場合も同様にソースコードの公開が必要です

> 詳細は`LICENSE`ファイルを参照してください。

-----

## コントリビューション

`CONTRIBUTING.md`を参照してください。

-----

## 利用規約

`TERMS.md`を参照してください。本ソフトウェアは**18歳以上の方のみ**が利用できます。