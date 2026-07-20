# CHANGELOG

## v3.0.0 — 2026-07-20

### 新機能
- **TRPGモード第一弾（F-20/21/22）**: ルールブック・シナリオ管理API、ダイスロール（技能/能力値生判定・`is_skill`/`is_stat`フラグ）、ダメージロール、対抗判定（`trpg.py` / `rule_engine.py`）
- **GMエージェント・イベントバス**: `gm/events.py` の `game_event_bus` による非同期通知（`JUDGMENT_RESOLVED`）。セッション履歴に判定結果を自動注入（`🎲 {name}【{技能}】 {出目} / {判定値} → {結果}` 形式）
- **TRPGモードUI**: `SessionTab.tsx` にDiceRow・ダイスダイアログ・シーン進行ボタン・キーパーターンバナー・ロール別バッジ（gm/human/ai）を追加
- **発言力上限設定**: `session_max_counter`（デフォルト5、範囲1〜20）を設定タブに追加。上限到達時は赤色警告表示
- **i18n TRPGモード対応**: `trpg.*` 名前空間 38+キーを日英両対応で追加
- ブラウザタブタイトルを `DEF(kari)` に変更（`index.html`）

### セキュリティ
- **SSRF修正** (`settings.py` `test_backend()`): `file://` 等のスキームを拒否、`http`/`https` のみ許可
- **`.env` インジェクション修正** (`settings.py` `_save_env_file()`): 改行文字を含む値を `ValueError` で拒否
- **`NameError` クラッシュ修正** (`session.py`): `_char_contents` / `penalty_message` の初期化を `if` 文外に移動

---

## v2.1.1 — 2026-07-14

### 新機能
- **`session_prompts.json` 外出し**: セッションモードのLLM指示文（弁明・賛否判定・キーパー判定・投票結果文言）を `data/session_prompts.json` に外出し。`_sp(key, lang)` ヘルパーで `user_language` 設定に応じた言語選択

### バグ修正
- VOICEVOX起動時に `--use_gpu` フラグを追加（DirectML経由でGPU使用）

---

## v2.1.0 — 2026-07-13

### 新機能
- **T2Iプロンプト生成モード3種**: current / passthrough / dedicated の切り替えと設定タブUI
- **バックエンド状態ポーリング間隔設定**: `status_poll_sec` を設定タブから変更可能
- サイドパネルの「チャット設定」→「設定」リネーム

### バグ修正
- 同一キャラクターへの切替時に挨拶をスキップ（F-26）
- `_find_char_dir` を `rglob("profile.json")` 再帰走査に変更し、3階層以上のキャラクターディレクトリで立ち絵がアイコンにフォールバックする問題を修正
- DEF-Characterリポジトリ分離を正式採用

---

## v2.0.3 — 2026-07-12

### バグ修正
- **`emotion` リスト型 Pydantic ValidationError → HTTP 500 修正**: `chat.py` にて `ChatResponse` 構築前に `emotion_str` 正規化処理を追加
- **i18n 未定義キー3件補完** (`chat.charSwitch.announce` / `chat.charGreeting.message` / `chat.history.showBtn`)

### 機能改善
- **F-26 キャラ切替挨拶改善** (`ChatTab.tsx`): 毎回挨拶送出・過去履歴を `hiddenHistory` ステートに退避・「📜 過去の会話を表示 (N件)」ボタンで復元・ページング読み込みボタンとの排他制御

---

## v2.0.2 — 2026-07-10

### 新機能
- セッションリテイク（`POST /retake`、history巻き戻し）
- セッション TTS 自動再生 + LLM 先読みパイプライン（`generateTTSUrl`/`playAudio` 分離、`prefetchRef`）

### バグ修正
- `get_character()` の `image_color` 欠落修正
- `SessionTab` `useEffect` 内 `return` 位置ミスによるルール消失修正

### UI改善
- セッション・チャットバブルの `imageColor+'33'` 半透過着色 + borderLeft/Right
- チャットタブ立ち絵背景（opacity 0.35、z-index 0）
- セッションバブル `max-width: 85%`
- TTS Audio UI をキャラ名右にインライン配置（縦幅削減）

### モデルプロファイル
- `context_length`（参照用）/ `max_tokens`（運用値）を分離定義、全14プロファイルをWebサーチ根拠で更新
- 主要ローカルモデルの `max_tokens` を 512→2048 に引き上げ

---

## v2.0.1 — 2026-07-08

### セキュリティ
- `character_id` パストラバーサル防止（正規表現バリデーション）
- novel/episode タイトルのパストラバーサル防止（pathlib.resolve + startswith）
- セッションIDを `secrets.token_urlsafe(16)` に変更・上限100件追加
- `POST /api/chat/force-rating` を `DEF_DEBUG_ENDPOINTS=true` 環境変数で保護
- DeepL/Civitai APIキーを `PERSISTED_KEYS` から除外し `secrets_store` 専用化（既存平文キーの自動移行）

### 新機能
- **F-28 ノベルモード実装** (`novel.py` + `NovelTab.tsx`)
- **TTSアダプターパターン実装** (`def_kari/tts/backend.py` + adapters/)
- LLM/T2I/TTSデフォルトモデルを環境変数化（`OLLAMA_DEFAULT_MODEL` / `HF_DEFAULT_MODEL` / `VOICEVOX_DEFAULT_SPEAKER` 等）
- `.env.example` に全APIキー環境変数を追記

### 削除
- `EpisodeTab.tsx` / `episode.py` を削除（F-24実装時に再作成）

---

## v2.0.0 — 2026-07-06

### アーキテクチャ移行
- **Streamlit → FastAPI + React (Vite/TypeScript)** への全面移行
- バックエンド: `uvicorn` + FastAPI REST API
- フロントエンド: React + TypeScript、アリスブルーテーマ

### 新機能
- **ノベルタブ**: 作品管理・プロット設定・AI候補生成・挿絵生成（T2I）・TTS読み上げ
- **思考タブ (ThoughtTab)**: フリーテキストでのAI思考実験
- **T2Iモデルプロファイルダイアログ**: バックエンド別モデル選択UI
- **サイドバー折り畳み**: ◀/▶トグル、レイアウト自由度向上
- **リサイズ対応レイアウト**: 本文↔サムネ・本文↔AI候補のドラッグリサイズ（localStorage保存）
- **キャラクターイメージカラー**: `image_color`フィールド、チャットバブルへの反映
- **セッションルール追加**: manzai / rakugo プリセット
- **アクションディレクティブ追加**: standard プリセット
- **i18n基盤 (i18n.tsx)**: React側多言語対応（日英164キー）
- `image_name_tags`フィールド: キャラ名をT2Iプロンプト先頭に自動挿入
- セッション上限: 100 → 1000（`DEF_MAX_SESSIONS`環境変数で制御可能）

### 改善
- TTS自動再生パイプライン強化（セッション・ノベル対応）
- T2I/TTSリテイク機能（全体/音声のみ/画像のみ）
- LLMプロファイル拡張（`context_length`、`leaks_thinking`等）
- 感情タグ自動挿入
- Civitai APIペイロード修正（`?wait=60`、`engine`/`ecosystem`/`operation`フィールド対応）
- HuggingFaceバックエンド切替の即時反映修正

### セキュリティ
- APIキー管理をモーダルダイアログに移行
- `data/sessions/`をGit管理対象外に追加
- Streamlit依存をすべてのアクティブコードから除去

### 削除
- Streamlit (`app.py`は互換性のため残存、非推奨)
- `streamlit>=1.58.0` を `requirements.txt` から削除

---

## v1.0.1 — 2026-07-04

Streamlit版の最終パッチリリース。v2.0.0移行前の安定スナップショット。

---

## v1.0.0

Streamlit版の初回リリース。
