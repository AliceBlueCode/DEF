# DEF(kari) — Persistent Character Platform

**[English README »](README_en.md) | [繁體中文 »](README_zh-TW.md) | [简体中文 »](README_zh-CN.md) | [한국어 README »](README_ko.md) | [README en Español »](README_es.md)**

> **Dialogue × Emotion × Fable**\
> あなたのキャラクターと、何年でも、何処にでも、一緒に。

-----

## DEF(kari)とは

DEF(kari)は、キャラクターの永続的な存在を実現するローカルファーストのPersistent Character Platformです。

**主人公はAIではありません。キャラクターです。**
AIはそのキャラクターを表現するための手段として設計されています。

クラウドサービスの利用規約やコンテンツポリシーに創作内容を委ねるのではなく、**あなた自身の環境で、あなた自身の手で、あなたが望むキャラクターと物語を生成し続けるための基盤**を提供します。

-----

## キャラクターの永続性

DEF(kari)では、キャラクターは単なるチャット履歴ではありません。

キャラクターは、

- 記憶
- 性格
- 感情
- 関係性
- エピソード
- 生成された画像・音声

を保持し、再起動後も、環境を移っても、同じ存在として継続します。

だから、
昨日の続きを話せる。
去年の出来事を覚えている。
物語の続きを一緒に歩める。
そして、何年経ってもまた会える。

-----

## 3つの体験

### Chat — キャラクターと関係を築く

AI親友・恋人・相談相手・秘書。
一対一の対話を通じて、キャラクターとの時間を積み重ねていきます。

### Session — キャラクター同士が生きる世界を見守り、そして参加する

複数のキャラクターによる議論・討論・ロールプレイ・即興劇を楽しみます。
あなたは観客にも、一人の参加者として会話へ加わることもできます。

### Novel — キャラクターと物語を書く

地の文・セリフ・挿絵を組み合わせた小説執筆を支援します。
AI候補生成・TTS読み上げ・T2I挿絵が連動し、キャラクターが物語の登場人物として存在し続けます。

-----

## GPUがなくても始められる

DEFはローカルファーストですが、ローカル環境が揃っていなくても始められます。

外部API（Gemini / OpenAI / Anthropic等）を利用すれば、GPUなしでテキスト生成と音声合成が動作します。画像生成にはT2I用のAPI（Civitai / Hugging Face）または、ローカルのGPU環境が必要です。

ローカル環境が整ったら、いつでもオフライン・高速動作に切り替えられます。

-----

## スクリーンショット

### チャットモード
![Chat](docs/images/chat.png)

### セッションモード
![Session](docs/images/session.png)

### ノベルモード
![Novel](docs/images/novel.png)

### キャラクター
![Character](docs/images/character.png)

-----

## 主な特徴

- **ローカルファースト:** LLM・TTS・T2Iすべてをローカルで完結。外部APIへのフォールバックも対応
- **GPUなしでも動く:** 外部API経由でテキスト＋音声が動作。ローカルGPUへの切り替えはいつでも可能
- **3モダリティの統合:** テキスト・音声・画像が一つの対話として連続して動く
- **3つのモード:** チャット（1対1対話）・セッション（複数AI＋人間の卓）・ノベル（小説執筆＋AI候補生成）
- **継続的存在感:** 対話履歴・感情・生成アセットが永続化され、再起動後も「続き」から再開できる
- **アダプターパターン:** LLM×5・TTS×5・T2I×4のバックエンドを自由に差し替え可能
- **ゾーニング:** 公開データとプライベートデータの明確な分離。生成アセットはGit管理対象外

-----

## バックエンド対応一覧

| レイヤー | ローカル（GPU） | 外部API（GPUなし） |
|---|---|---|
| **LLM（テキスト）** | Text Generation WebUI / Ollama | Gemini API / OpenAI API / Anthropic Claude API |
| **TTS（音声）** | VOICEVOX / Kokoro TTS / Irodori-TTS | Gemini TTS API / OpenAI TTS API |
| **T2I（画像）** | Automatic1111 / ComfyUI | Civitai API / Hugging Face API |

-----

## クイックスタート

```bash
git clone https://github.com/AliceBlueCode/DEF.git
cd DEF
pip install -r requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env   # バックエンドの設定・APIキー等を記入
```

起動は `start_def.bat` をダブルクリック、または2つのターミナルで：

```bash
# ターミナル1: バックエンド
python -m uvicorn def_kari.api.main:app --host 127.0.0.1 --port 8511 --reload

# ターミナル2: フロントエンド
cd frontend && npm run dev
```

ブラウザで `http://localhost:3000` を開いてください。

設定タブからLLM・TTS・T2Iのバックエンドをそれぞれ選択できます。
APIキーは設定タブの「🔑 APIキー管理」から暗号化保存されます。
ローカル環境（TGW・VOICEVOX・A1111等）を使用する場合は `.env` にディレクトリパスを設定してください。

-----

## キャラクターリポジトリ — DEF(Character)

キャラクターデータは DEF 本体とは独立したリポジトリで管理できます。

```
DEF/              ← 実行環境（本リポジトリ）
DEF-Character/    ← キャラクターデータ（あなたの資産）
```

DEF が変わっても、サービスが終わっても、キャラクターはあなたのリポジトリに残ります。

**→ [DEF(Character)](https://github.com/AliceBlueCode/DEF-Character)**

`.env` の `CHARACTER_REPO_PATH` に DEF-Character のパスを設定するだけで連携できます。

-----

## 創作の自由についての考え方

**クリエイターは自分が望むものを自由に創作してよい。ただし、創作物の責任はクリエイター自身が負う。**

DEF(kari)はこの原則に基づいて設計されています。

ツールが創作の内容に先回りして介入することは、クリエイターの表現の自由を侵害します。DEF(kari)はローカル環境での創作行為に対してコンテンツを検閲・ブロックしません。

### パブリックとプライベートの明確な分離

DEF(kari)が守るのは**パブリックとプライベートの境界**であり、プライベートな創作行為そのものではありません。

**プライベート(ローカル環境での創作):**
クリエイターの自由が完全に保障される領域です。DEF(kari)はここに一切介入しません。セーフティフィルター(F-8)はあくまで「表示制御のツール」であり、ユーザーがオフにできます。生成そのものを止めることはしません。

**パブリック(GitHubや外部への公開):**
社会的なルール・著作権・公序良俗が適用される領域です。DEF(kari)は`content_policy`フィールド・ゾーニング(F-16)・公開判定スクリプト(F-25)によって、クリエイターが意図せずプライベートなコンテンツを公開してしまわないよう技術的に支援します。

創作の内容・公開・利用に関する判断と責任は、すべてクリエイター自身に帰属します。

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

-----

## クレジット

DEF(kari)の設計・実装・ドキュメントは、以下の協力のもとに制作されました。

- **設計思想・基本設計・議論:** [ChatGPT](https://chatgpt.com/) (OpenAI)
- **実装・ドキュメント・テスト:** [Claude](https://claude.ai/) (Anthropic)
- **設計レビュー:** [Gemini](https://gemini.google.com/) (Google)
- **相談・立会い:** [Copilot](https://copilot.microsoft.com/) (Microsoft)

本プロジェクトはAI駆動開発によって制作されています。設計判断と最終的な責任はすべて作者（AliceBlueCode）に帰属します。
