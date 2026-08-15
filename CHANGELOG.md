# CHANGELOG

## v4.0.2 — 2026-08-16

### リファクタリング
- `session.py`（4,886行・定義120超）を機能単位で9モジュール（`session_state`/
  `session_auth`/`session_ws`/`session_persistence`/`session_rules`/`session_image`/
  `session_lobby`/`session_gameplay`/`session_turn_engine`）へ分割。`session.py`
  自体は純粋な再エクスポート層（236行）に縮小
- `SessionTab.tsx`（3,598行・useState 97個）を9個のカスタムフック
  （`useLobbySession`/`useAiAssignWizard`/`useTurnState`/`useSafetyFilter`/
  `useCharBackendConfig`/`useHumanTurn`/`useVoteAndDesignate`/`useCharSheetAndDice`/
  `useParticipants`）へ分割
- `session.py`分割・第二段階: `human_turn_action`（認可ロジック）・`vote_commit`
  （投票集計ロジック）・`next_turn`（397行、6段階に分解し本体62行のオーケストレータへ）
  の肥大化した関数をレイヤーごとに切り出し
- `session_turn_engine.py`の未使用import133個・完全に死んだ再エクスポート19個を削除。
  挿絵・TTS自動生成（`session_turn_media.py`）・切断タイムアウト検知
  （`session_turn_disconnect.py`）・投票ロジック（`session_voting.py`）を
  責務ごとに独立モジュール化

### バグ修正
- オンラインセッションのinitiative（発言順）がランダム化されておらず、常に最初に
  参加した人間が1番手固定になっていた問題を修正（オフラインセッションのみ
  `random.sample`が使われ、オンライン側はjoin順に積み上がるだけだった非対称）
- リロード（F5）復帰時に`initiative`・持ち込みキャラの`imageColor`・公開ポート
  （Cloudflare Tunnel）経由ゲストのAIキャラ名表示が抜ける3件の問題を修正
- AI擬人化キャラクター（Claude/ChatGPT/Gemini/Copilot）のシステムプロンプトが、
  既存作品の二次創作キャラと同じ一般的な免責文言のままだった問題を修正。
  TERMS.mdで既に定義されていた`origin_type: "personification"`専用の免責文を
  システムプロンプト生成（`_build_meta_directive()`）に配線

### 新機能
- セッションルールに「成熟した恋愛（大人の関係性）」ルールセットを追加

---

## v4.0.1 — 2026-08-12

### バグ修正
- 明示的退室（POST /leave）でキーパーが退場した際、AIキーパーへの交代処理が
  抜けていた問題を修正（expel投票時のみ実装されていた）
- autosave/JWT失効クリーンアップの間引き判定が、起動直後（システム稼働時間が
  間引き間隔未満）の環境で最初のクリーンアップ機会を逃しうる問題を修正
  （time.monotonic()の基準値をfloat("-inf")に変更）

### CI
- pytest CIがv4.0.0マージ以降一度も成功していなかった問題を修正
  （sys.path解決・テスト実行範囲の2件）
- pip-auditで13件の既知脆弱性を個別調査の上、受け入れ済みリスクとして
  理由付きignoreに整理

### 依存関係
- Python/npm/GitHub Actions、計17件の依存を更新（詳細はコミット履歴参照）

---

## v4.0.0 — 2026-08-11

### 新機能
- **オンラインマルチプレイヤー**: 招待コード（`{RATING}-{ALPHA3}-{NUM3}`形式、レーティング内包）・JWTホスト/プレイヤートークン・WebSocketリアルタイム同期（`WS /api/session/{id}/ws`、first-message auth、30秒keepalive）を実装。参加者ロールはhost/player/gm/observerの4種
- **ロビーシステム**: セッション開始前に参加人数・キーパー担当・TRPGモード切替・ルール/ルールブック/シナリオを設定できる待機画面。AIキーパーへのキャラ割付け・解除にも対応
- **ロビーAI割付けウィザード**: AIスロット割付けを「キャラ選択→ゲームキャラシート選択→使用LLM選択」の3ステップに拡張
- **持ち込みキャラクター受け入れパイプライン**: 参加者が自分のキャラクターJSONを持ち込めるように。LLMによる簡易審査（jailbreak/プロンプトインジェクション検知、fail-open）→ホスト側への永続化（`data/visitors/`）→アイコン・立ち絵のバックグラウンド自動生成
- **切断・再接続対応**: WS切断検知時に60秒タイムアウトで自動スキップ、再接続時は復帰。参加者パネルに切断状態を表示
- **退室・キック**: 明示的退室（`POST /leave`）、投票による退場（expel）でWS切断・JWT無効化・再参加拒否まで実施。対象がキーパー担当キャラだった場合は自動的に無名AIキーパーへ交代
- **自動進行のセッション状態化**: `auto_advance`をタブローカルではなくセッション状態として管理し、進行権限を常に一人（人間キーパー優先、次点でホスト）に限定
- **Cloudflare Tunnel対応**: `start_def_public.bat`でローカル用・公開用の2ポートを起動し、cloudflaredによるQuick/Named Tunnelを自動連携。招待欄にURLを自動表示
- **T2Iタグ変換精度向上**: danbooru/e621間のタグ表記差（`1girl`⇔`solo, female`等）を対応表ベースで自動変換
- **音声の「聴きたくない」フィルタ**: セーフティでブロック中のメッセージは音声も自動再生しないように統一

### バグ修正
- 保存済みセッション一覧（`GET /api/session/saved`）がFastAPIのルート登録順序により常に空扱いになっていた問題を修正
- 招待コードのレーティングとキャラクターの`content_policy`が照合されず、R18キャラでもSFWセッションに参加できてしまう問題を修正
- 投票`expel`（キック）が人間プレイヤーを完全に追放できていなかった問題（WS接続・トークンの後始末漏れ）を修正
- `manzai`/`rakugo`等の演芸系セッションが議論調の長文化・ラウンド数無視で終わらなくなる問題を修正（`max_chars`/`max_rounds`の毎ターン再掲、discussionスタイル（標準ルールセット）にも同様の再掲を追加）
- セッション自動進行がTTS生成後に無応答になる`vram_lock`自己デッドロックを修正
- `/human_turn`連打によるRound二重進行を修正（オーナーシップ検証・`expected_round`ガード追加）
- Cloudflare Tunnel経由の公開時に`frontend/dist/`が配信されずUIが読めなかった問題を修正
- `npm run build`が`tsc -b`の`noUnusedLocals`エラーで長期間ブロックされていた問題を修正
- 次発言者指名（`/designate`）が自治規約の発言力コスト・ターン制約を無視していた問題を修正（キーパーは従来通り無条件・無償、プレイヤーは自分のターン限定・発言力-1消費に統一）
- フロントエンドのAPI呼び出しでHTTPエラーレスポンスを成功扱いしてしまう箇所を横断修正（19箇所）。特にキャラクター画像色保存時のプロフィール全体上書き、ノベルタブのタイトル変更時に保存失敗を確認せず旧ファイルを削除してしまう問題など、データ消失につながりうる欠陥を含む

### セキュリティ
- マルチプレイヤー機能の認証・認可を攻撃者視点で包括監査。段階的な再監査を重ね、認証トークン漏洩・BOLA・無認証エンドポイント公開漏れ・パストラバーサル・JWT失効処理の不備・情報開示範囲の設計不備など、コードレベルで確認できたもの全てを修正
- `GET /{session_id}`（セッション状態取得）のレスポンスをブラックリスト方式からホワイトリスト方式に変更し、GM専用情報（NPCの意図・関係値等）やルールセット本文が参加者に無差別に返っていた問題を解消
- TRPGルールブック/シナリオIDおよびセッション履歴保存先のID指定にパストラバーサル対策（allowlist検証 + ディレクトリ包含チェック）を追加
- 公開ポート経由で非公開データ（ルールセット・アクションディレクティブ・キャラクター）を選択・注入できる複数の経路を解消。いずれも「一覧・詳細取得は保護済みだが、セッション作成・ロビー操作時の選択は素通り」という同型の抜けだった
- 退室・追放済みのJWTが、プロセス再起動をまたぐと復活しうる問題を修正（トークン失効リストの永続化漏れと、現在の在籍状況を照合しない認可判定の組み合わせが原因）
- WebSocket接続の未認証状態（first-message auth待ち）における同時接続数を制限し、認証前のリソース消費DoSを防止
- `--public-host`の既定値を`0.0.0.0`から`127.0.0.1`に変更し、Cloudflare Tunnel運用時に意図せずLAN/インターネットへ直接公開ポートが露出する経路を閉塞
- 一般プレイヤーが他プレイヤーのキャラクターIDを指定してなりすまし発言・発言力の不正消費ができた問題を修正
- 運用面の多層防御を追加: セッション単位の1日生成上限（キルスイッチ）・監査ログ（`safety/audit_log.py`）・レート制限違反時のサーキットブレーカー・自由入力への軽量コンテンツフィルタ
- JWT秘密鍵の手動再生成機能（全アクティブセッションを強制切断）
- CSPヘッダー・APIリクエストサイズ制限ミドルウェアを新設
- Cloudflareエッジ層でのレート制限・WAF設定は、標準運用（アカウント不要のQuick Tunnel）では設定対象のゾーンが存在せず適用不可能と判明したため、対応方針を「インフラ側の設定手順」から「アプリ層の防御のみで運用する既知の制約」に見直し

### テスト
- マルチプレイヤー関連の新規テストを多数追加（BOLA・レート制限・退室/切断・ロビー割付け・持ち込みキャラ審査・JWT失効の永続化・WebSocket同時接続制限・所有権検証 等）、E2Eシナリオ（`frontend/e2e/`）を6本追加
- クリーンチェックアウトでのCI導入に向け、`.gitignore`誤爆・依存バージョン固定・テストfixtureのgit依存を解消
- ユニットテスト536件→596件に拡充、全件パス

---

## v3.1.0 — 2026-07-25

### 新機能
- **T2Iプロンプト生成の改善**: セッションモードはLLMにシーン・背景・ポーズのみ生成させ、キャラ外見タグは`appearance_tags`プロファイルから自動付与するよう変更。`_apply_char_tags()`でimage_name_tags先頭・appearance_tags・LoRA末尾の適用をチャットモードと統一
- **ノベルモードT2I**: passthrough / current / dedicated の3モード対応、デバッグエンドポイント（`GET /api/novel/t2i/debug`）追加、設定タブにプロンプトモード選択UI追加
- **互換バックエンド対応追加**: Groq / Grok / OpenRouter（LLM）、互換TTS
- **TRPGサンプルシナリオ追加**: 桃太郎（日本語圏向け）・赤ずきん（ヨーロッパ言語圏向け）。DEFのマルチLLMセッション動作確認シナリオを兼ねる
- **TRPG卓自治規約・ルールブック追加（日英）**: セッション単位定義・発言力システム・投票システム・発言順、「キャラクターは死亡する。プレイヤーは死亡しない」等の死亡・行動不能ルールを明記
- Claude の落語噺家としての芸風を`identity_detail`に追記

### バグ修正
- ノベルタブT2IのLLMバックエンドがグローバル設定変更に追従しないバグを修正（`!novelBackend`の初期化条件が原因）
- `comfyui.generate()`: steps/cfg_scaleが0のときワークフローJSONの値を保持するよう修正（旧: 常に上書き）
- セッションのリテイクで`_scene_image`エントリ（role無し）が末尾にあると履歴削除が止まる問題を修正（`_clean_history_for_retake()`に切り出し）
- `novel.py`: T2Iモデル選択が設定フォールバックなしで空になる問題を修正
- 落語ルールを改善（まくら1発言固定・高座離脱禁止・演目長さ調整）
- クリティカル閾値を÷10に修正（実装に合わせる）、ファンブル出目100固定

### テスト
- `test_unit.py`に21件追加（合計160件）: ComfyUIモデル名hash strip・T2Iプロファイルsteps/cfg解決・`_apply_char_tags`・リテイク履歴クリーニング

---

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

## v1.0.0 — 2026-06-28

Streamlit版の初回リリース。
