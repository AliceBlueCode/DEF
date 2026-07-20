# DEF(kari) v3.0.0 実装状況

本ドキュメントは、基本設計書に記載された機能仕様（F番号）の実装状況を記録するものです。

> **v2.0.0 変更点:** アーキテクチャを Streamlit → FastAPI + React (Vite/TypeScript) に移行。詳細は基本設計書 Section 2.1 を参照。

> **v2.1.x 変更点:** TTSバックエンドにOpenAI TTSを追加（5種）。T2Iプロンプト生成モード追加（current/passthrough/dedicated）。LLM指示文を `session_prompts.json` で外出し管理。`status_poll_sec` 設定UI。DEF-Characterリポジトリ分離対応。同一キャラ切替時の挨拶スキップ（F-26）。

> **v3.0.0 変更点:** TRPGモード第一弾（F-20/21/22）実装。ルールブック・シナリオ管理API、ダイスロール、GMエージェント、イベントバス。発言力上限設定（`session_max_counter`）追加。i18nにTRPGモード用語（38+キー）追加。

---

## 実装済み

| F番号 | 機能名 | 状態 | 備考 |
|---|---|---|---|
| F-1 | LLM非同期パイプライン | ✅ 実装済み | テキスト生成の基本パイプライン |
| F-2 | LLMバックエンドアダプター | ✅ 実装済み | TGW / Ollama / OpenAI / Gemini / Anthropic |
| F-3 | 定期ポーリング・イベントディスパッチャー | ✅ 実装済み | ReactフロントエンドによるREST定期ポーリング。`status_poll_sec` を設定タブから変更可能（デフォルト5秒、localStorage保存） |
| F-5 | モデル選択・モデルプロファイル | ✅ 実装済み | バックエンドごとのモデル管理、プロファイル編集UI |
| F-6 | セッションモード（マルチエージェント） | ✅ 実装済み | 複数AI＋人間参加、イニシアチブ制、発言力システム |
| F-7 | セーフティタグ | ✅ 実装済み | 6段階（sfw/nsfw/hentai/violence/gore/extreme） |
| F-8 | コンテンツフィルタリング | ✅ 実装済み | off/warn/mask、ユーザー制御可能 |
| F-9 | i18n・多言語対応 | 🔶 主要UI完了 | 200+キー（日英、TRPGモード38+キーを含む）。LLM指示文は `session_prompts.json` で外出し管理。セッション内動的メッセージ約30箇所は未対応 |
| F-10 | TTS音声合成 | ✅ 実装済み | VOICEVOX / Kokoro / Irodori / Gemini TTS / OpenAI TTS |
| F-11 | TTS自動再生・パイプライン | ✅ 実装済み | セッション・ノベルモード対応 |
| F-13-1 | VRAM排他制御 | ✅ 実装済み | vram_lock方式 |
| F-14 | 構造化出力・フォールバックチェーン | ✅ 実装済み | 4段階フォールバック、フィールド名typo自動修正 |
| F-15 | T2Iトリガー | ✅ 実装済み | 4モード（各サイクル最後/最初/手動/インターバル）。T2Iプロンプト生成モード3種（current/passthrough/dedicated）を設定タブから選択可能 |
| F-16 | ゾーニング（公開/プライベート分離） | ✅ 実装済み | data/public + data/private |
| F-17 | 生成アセット管理 | ✅ 実装済み | Git管理対象外に隔離 |
| F-18 | session_state軽量化 | ✅ 実装済み | MAX_VISIBLE_TURNS=3、trim_session、遅延読み込み |
| F-23 | ターン再生成・Undo/Redo | ✅ 実装済み | 全体/音声のみ/画像のみ再生成、保持件数設定可能。ノベルモードはブラウザ標準Ctrl+Zで代替するため非対応 |
| F-25 | origin_type・公開ポリシー | ✅ 実装済み | original/reconstructed_persona/personification/derivative |
| F-26 | キャラクター切替時の自動挨拶 | ✅ 実装済み | ON/OFF設定可能。同一キャラクターへの切替は挨拶スキップ（v2.1.1〜） |
| F-27 | メタ自己認識ディレクティブ | ✅ 実装済み | content_policyベース（default/existing_ip/real_person 3バリアント）、システムプロンプト先頭強制挿入 |
| F-28 | ノベルモード基盤 | ✅ 実装済み | 作品管理、プロット設定、AI候補生成、`Chapter N + Scene M` ラベル |
| F-28 | ノベルモード 3モダリティ | ✅ 実装済み | TTS読み上げ（Scene単位）、T2I挿絵（LLM→画像プロンプト→生成） |
| F-28 | プロットファイル書き戻し | ✅ 実装済み | `PUT /api/novel/plots/{filename}` でGit管理プロットを直接保存 |
| F-28 | T2I設定ダイアログ | ✅ 実装済み | バックエンド・モデルを `/api/settings/backends` から動的取得 |
| F-28 | リサイズ対応レイアウト | ✅ 実装済み | 本文↔サムネ（縦）・本文↔AI候補（横）ドラッグリサイズ、localStorage保存 |
| F-28 | VRAM排他制御（ノベルタブ） | ✅ 実装済み | `/api/novel/generate` と `/api/novel/t2i` が vram_lock を取得・解放 |
| —— | キャラクターイメージカラー | ✅ 実装済み | `base_profile.image_color` フィールド、CharacterTab カラーピッカー、ChatTab AIバブルへの適用 |
| —— | サイドバー折り畳み | ✅ 実装済み | `Sidebar.tsx` collapse state、◀/▶ トグルボタン |
| —— | 思考タブ（ThoughtTab） | ✅ 実装済み | フリーテキストでのAI思考実験、`GET/POST /api/thought/` |
| —— | T2Iモデルプロファイルダイアログ | ✅ 実装済み | ノベルタブ内⚙ダイアログ、バックエンド別モデル選択 |
| —— | セッションルール追加 | ✅ 実装済み | manzai / rakugo プリセット追加 |
| —— | アクションディレクティブ追加 | ✅ 実装済み | standard プリセット追加 |
| —— | i18n基盤（i18n.tsx） | ✅ 実装済み | React側多言語対応基盤、日英対応 |
| —— | DEF-Character リポジトリ分離 | ✅ 実装済み | `CHARACTER_REPO_PATH` で外部キャラクターリポジトリを連携。旧 `data/characters/` 形式をフォールバック |
| F-20 | TRPGルールブック注入 | ✅ 実装済み | JSON形式。`data/public/trpg_rules/` / `data/private/trpg_rules/` から読み込み。IDバリデーション付き |
| F-21 | GMエージェント | ✅ 実装済み | キャラクターをGMとして指名。イベントバス（`game_event_bus`）で非同期通知。判定結果をセッション履歴に自動注入 |
| F-22 | ダイスロール・キャラクターシート | ✅ 実装済み | `NdM±K` 記法、成功/クリティカル/ファンブル/失敗判定、対抗判定、ダメージロール。シナリオ管理APIも提供 |

---

## 未実装（次フェーズ）

| F番号 | 機能名 | 状態 | 備考 |
|---|---|---|---|
| F-4 | 動的生成（Consistency Provider） | ❌ 未実装 | 視覚的一貫性の自動維持。手動T2I生成で代替可能 |
| F-12 | スマート・リソースマネージャー | ⏸ 保留 | F-13-1（vram_lock）で主要目的を達成済み。CPU/GPUハイブリッド推論の自動判別は現アーキテクチャでは不要 |
| F-13-2 | 軽量レスポンスモード | ⏸ 保留 | 現アーキテクチャでは不要 |
| F-13-3 | Diffusersオフロード制御 | ⏸ 保留 | 現アーキテクチャでは不要 |
| F-19 | エクスポート/インポート | ⏸ 保留 | データ構造が固まるまで保留 |
| F-24 | エピソードモード基盤 | ❌ 未実装 | Episode > Chapter > Scene 階層管理。将来フェーズ |
| F-24 | エピソードモード基盤 | ❌ 未実装 | Episode > Chapter > Scene 階層管理。将来フェーズ |
| F-24-1 | エピソード構造化出力 | ❌ 未実装 | narration/dialogue/tags/choices JSON Schema |
| F-24-3 | 分岐選択肢+Git連携 | ❌ 未実装 | choices→Gitブランチ |

---

## 既知の制約

| 項目 | 内容 |
|---|---|
| セッション履歴のトークン上限 | 長時間セッションでLLMのコンテキスト上限に達する可能性あり |
| Irodori-TTS CUDA | uv sync後にvenvがCPU版になる場合がある |
| バックエンド多重起動 | PIDファイルガードの不安定さ |

---

## 対応バックエンド

| 種別 | バックエンド数 | 内訳 |
|---|---|---|
| LLM | 5 | Text Generation WebUI / Ollama / OpenAI / Gemini / Anthropic |
| TTS | 5 | VOICEVOX / Kokoro / Irodori / Gemini TTS / OpenAI TTS |
| T2I | 4 | A1111 / ComfyUI / Hugging Face / Civitai |

---

## テスト

| 種別 | 件数 | 結果 |
|---|---|---|
| ユニットテスト | 186件 | 全パス |

---

本ドキュメントはv3.0.0時点の状況です。最新の状況はリポジトリのIssuesおよびリリースノートを参照してください。
