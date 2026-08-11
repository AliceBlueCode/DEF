# DEF(kari) アーキテクチャ概要

このドキュメントは、初めてこのリポジトリに触るコントリビュータ向けの俯瞰資料です。詳細な設計判断は各ドキュメント（[README.md](../README.md)・[CONTRIBUTING.md](../CONTRIBUTING.md)・本ディレクトリの基本設計書等）を参照してください。ここではまず「全体がどう繋がっているか」と「どこを触っていいか」だけを掴めることを目標にしています。

## 全体像

```
┌─────────────────────────────────────────────────────────────┐
│  フロントエンド  frontend/                                    │
│  React + Vite SPA（キャラクター・チャット・セッション・ノベル等の  │
│  タブUI）。REST + WebSocketでバックエンドと通信する。            │
└───────────────────────────┬─────────────────────────────────┘
                             │ HTTP / WebSocket
┌───────────────────────────▼─────────────────────────────────┐
│  APIサーバー層  def_kari/api/                                 │
│  FastAPI。main.py（フル機能・127.0.0.1限定）と                 │
│  public_main.py（session機能＋読み取り専用配信のみ・Cloudflare  │
│  Tunnel等での外部公開用）の2アプリを dual_run.py が同一プロセス │
│  内で同時起動する。ルーティングは def_kari/api/routes/ 配下     │
└──────┬──────────────┬──────────────┬──────────────┬─────────┘
       │              │              │              │
┌──────▼──────┐ ┌─────▼──────┐ ┌────▼───────┐ ┌────▼─────────┐
│ ドメイン層    │ │ セーフティ層 │ │ 履歴/設定層  │ │ TRPG層        │
│ def_kari/gm/ │ │def_kari/    │ │history/     │ │def_kari/trpg/ │
│ セッション進  │ │safety/      │ │settings.py  │ │ルールブック    │
│ 行・GM/キー   │ │contentフィ  │ │secrets_     │ │注入・ダイス    │
│ パーエージェ  │ │ルタ・持ち込  │ │store.py     │ │判定           │
│ ント          │ │みキャラ審査  │ │             │ │               │
└──────┬───────┘ └─────┬──────┘ └─────────────┘ └───────────────┘
       │               │
┌──────▼───────────────▼────────────────────────────────────┐
│  バックエンドアダプタ層（LLM / T2I / TTS 共通パターン）         │
│  def_kari/llm/ ・ def_kari/t2i/ ・ def_kari/tts/             │
│  各backend.pyが {バックエンドID: 関数} の辞書でアダプターを     │
│  登録し、adapters/ 配下の各モジュールレベル関数（chat() /      │
│  generate() / synthesize()）に処理を委譲する                  │
└──────┬─────────────────────────────────────────────────────┘
       │
┌──────▼─────────────────────────────────────────────────────┐
│  外部ツール（別プロセス、backends.pyが自動起動/停止を管理）      │
│  TextGen WebUI (LLM) ・ ComfyUI (T2I) ・ VOICEVOX / Irodori-  │
│  TTS (TTS)。他にOpenAI/Anthropic/Gemini等の外部APIも同じ      │
│  アダプタ層から利用できる                                     │
└───────────────────────────────────────────────────────────┘
```

データは `data/public/`（配布・共有可能）と `data/private/`（個人の環境依存データ、gitignore対象）に分離されている。詳細はCONTRIBUTING.md冒頭の「創作の自由についての考え方」を参照。

## 各層の役割

- **フロントエンド（`frontend/`）**: React + Vite。タブ単位でコンポーネントが分かれる（`frontend/src/components/`）。多言語UIは`frontend/src/i18n.tsx`のja/en辞書。
- **APIサーバー層（`def_kari/api/`）**: `main.py`はローカル専用（設定・APIキー等フル機能）、`public_main.py`はオンラインセッション機能のみに絞った公開用アプリ。両者は同一プロセス内で`_sessions`等のシングルトンを共有するため、マルチプロセス化（`--workers`複数）はできない設計になっている。
- **ドメイン層（`def_kari/gm/`）**: セッションの進行管理・AIキーパー（GM）・AIプレイヤーの行動選択などゲーム進行の中核。`game_event_bus`（`events.py`）を介してWebSocket配信と疎結合になっている。
- **セーフティ層（`def_kari/safety/`）**: コンテンツフィルタ・監査ログ・持ち込みキャラクターのLLM審査（jailbreak/プロンプトインジェクション検知）。DEF(kari)はローカルでの創作行為そのものには介入しないが、オンラインセッションの参加資格ゲート等パブリックとプライベートの境界には強く介入する（CONTRIBUTING.md参照）。
- **バックエンドアダプタ層（`def_kari/llm/`・`def_kari/t2i/`・`def_kari/tts/`）**: 3層とも同じ設計パターン。`adapters/`配下に1バックエンド1モジュールでモジュールレベル関数を実装し、`backend.py`の辞書に登録するだけで新しいバックエンドを追加できる。コアコード側にバックエンド固有の分岐を書かないのが原則（詳細はCONTRIBUTING.md 2〜4節）。
- **外部ツール**: DEF(kari)本体とは別プロセスで動く。`def_kari/backends.py`がインストール先（`.env`の`*_DIR`）・起動・停止・PIDファイル管理を担う。

## ディレクトリマップ：どこを触っていいか

PR受け入れ範囲の詳細な表はCONTRIBUTING.mdにあるが、ここではディレクトリ単位でもう少し直感的にまとめる。

| 領域 | 方針 |
|---|---|
| `def_kari/llm/adapters/`・`def_kari/t2i/adapters/`・`def_kari/tts/adapters/` | ✅ 自由に追加OK。新規バックエンドアダプタの追加はいつでも歓迎（CONTRIBUTING.md 2〜4節） |
| `frontend/src/components/` | ✅ 見た目の改善・新規コンポーネント追加はOK。ただしグローバルな状態管理・API通信ロジックの変更は要相談 |
| `locales/` | ✅ 言語追加・既存翻訳の改善はOK。キーの追加・削除はしないこと |
| `def_kari/gm/`・`def_kari/api/`・`def_kari/history/`・`def_kari/safety/` | ⚠️ コアロジック。バグ修正歓迎、設計・アーキテクチャに関わる変更はまずIssueで提案してから |
| `data/public/characters/` | ❌ 本リポジトリでは受け付けない。キャラクターデータは[DEF(Character)](https://github.com/AliceBlueCode/DEF-Character)リポジトリで管理 |
| `poc/` | 📦 旧Streamlit版のレガシー実装。参考程度に留め、通常の開発対象ではない |
| `data/private/`・`.env`・`data/secret.key`・`data/api_keys.enc.json` | 🚫 個人の環境依存データ・秘密情報。gitignore対象で、PRに含めないこと |
| `docs/`（本ファイル含む） | ✅ 誤字・補足はOK。設計仕様そのものの変更提案はIssueへ |

## もっと詳しく知りたいときは

- PRの受け入れ範囲・手順の詳細: [CONTRIBUTING.md](../CONTRIBUTING.md)
- 使い方: [DEF_kari_操作手順書.md](DEF_kari_操作手順書.md) / [DEF_kari_User_Guide_en.md](DEF_kari_User_Guide_en.md)
- 設計判断の詳細: [DEF_kari_基本設計書.md](DEF_kari_基本設計書.md) / [DEF_kari_Basic_Design_Specification_en.md](DEF_kari_Basic_Design_Specification_en.md)
- 用語集: [DEF_用語集.md](DEF_用語集.md) / [DEF_Glossary_en.md](DEF_Glossary_en.md)
