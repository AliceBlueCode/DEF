# CHANGELOG

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
