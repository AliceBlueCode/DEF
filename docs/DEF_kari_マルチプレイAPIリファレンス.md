# DEF(kari) マルチプレイヤー APIリファレンス

本書は、オンラインマルチプレイヤーセッション(v4.0〜)のワイヤープロトコルを定義する。別クライアントの実装・セッション状態の監視ツール作成等、DEF本体のフロントエンド以外からセッションAPIを利用する場合の参照資料として使う。

セッションの参加者ロール・自治ルール(発言力・投票・Round/Turn/Action進行)については`docs/DEF_TRPG卓_自治規約.md`、用語の定義は`docs/DEF_用語集.md`8章を参照。

-----

## 1. 招待コード仕様

コードにセッションレーティングを埋め込む形式で、コードを見ただけで内容が分かる。

```
形式: {RATING}-{ALPHA3}-{NUM3}
例:
  SFW-ABK-492   全年齢
  R15-GHM-837   軽度の暴力・ホラーあり
  R18-XPQ-264   成人向け
  UNL-RTK-519   無制限（ゾーニング設定に委ねる）
```

- 除外文字: `O`（ゼロと混同）・`I`（アイと混同）・`0`・`1`
- 使用文字: 英大文字A-Z（O・I除く）24種 + 数字2-9（0・1除く）8種
- 有効期限: セッション終了まで
- エントロピー: レーティング固定時、24³×8³ ≈ 710万通り。IPベースのレート制限（10回/分、10回失敗で1時間ロック）とセットで運用する前提で、コード空間の広さ単体を強度の根拠にはしていない
- 参加画面ではレーティングをUIに反映（色分け等）する。Discordやチャット上でコードをそのまま共有しても、受け取った側がレーティングを把握できる

-----

## 2. APIエンドポイント

```
POST /api/session/join
  body: { invite_code, character_json (持ち込みキャラ), join_as_gm: bool }
  response: { player_token (JWT), session_id, character_id, role, lobby_active, display_name }

POST /api/session/available-slots
  body: { invite_code }
  response: { human_slots, online_mode, gm_taken, waiting_for_gm, trpg_mode }
  → 招待コードからスロット状況を取得（参加ダイアログ用）

POST /api/session/{session_id}/invite
  → 招待コード発行（ホストのみ）

PATCH /api/session/{session_id}/host_role?is_keeper=bool
  → ホストの役割切替（keeper: 観戦・進行管理 / player: キャラ担当）

PATCH /api/session/{session_id}/lobby/mode
  body: { trpg_mode: bool }
  → TRPGモード / 通常セッション の切替（ロビー中のみ有効、開始後は409）

PATCH /api/session/{session_id}/lobby/keeper_source
  body: { waiting_for_gm: bool }
  → キーパー枠をAI自動進行にするか参加者を待つかを切替

POST /api/session/{session_id}/lobby/set_keeper_char
  body: { character_id: string }  # 空文字列 = 解除
  → ロビー中にAIキーパー役のキャラクターを割り付け・解除する。
  → TRPGモード・AI自動進行時のみ意味を持つ。
  → 割り付けなくても無名AIキーパー（汎用「🎩 Keeper」表示）としての自動進行は維持される。
  → initiativeに既にいるキャラ・human型キャラは拒否

PATCH /api/session/{session_id}/lobby/settings
  body: { topic?, rule_set?, trpg_rulebook?, trpg_scenario?, max_players? }
  → ロビー中のセッション設定変更（省略フィールドは変更しない）。
  → rules/scene・skill_pool・npc_state の派生データも再構築。開始後は409。
  → max_players はオンライン作成時デフォルト4。join定員判定は initiative 長
    （AIスロット+参加プレイヤー）基準。観戦者・GMは定員対象外

PATCH /api/session/{session_id}/auto_advance
  body: { enabled: bool }
  → 自動進行モードの切替（セッション状態）。AUTO_ADVANCE_CHANGED を全タブに配信。
  → 進行権限は常に一人: gm参加中はgmのみ（ホストは403）、AIキーパー構成ではホストのみ

WS   /api/session/{session_id}/ws
  → WebSocket接続エンドポイント（詳細は下記3章参照）

GET  /api/session/{session_id}
  headers: Authorization: Bearer {token}  # 参加者トークン必須（host/player/gm/observer）
  → 過去ログ全件・initiative・name_map・進行状況（round/turn等）・モードフラグなど、
    全ロール（host/player/gm/observer含む）に公開してよいフィールドのみを返す
    （allowlist方式）。認証トークン/招待コード等の機密フィールドに加え、
    npc_state・player_knowledge（GM専用のNPC知識・キャラ別既知情報）、
    rules/scene（ルールセット本文）、char_game_sheets/skill_pool/skill_values、
    guest_chars等のGM/シナリオ由来コンテンツ・内部状態も一切含まれない
    （GM専用情報が必要な場合は `GET /{session_id}/npc/{npc_id}/state` 等の
    require_keeper保護された個別エンドポイントを使う）。そのセッションの
    参加者トークンでのみ読める（退室・追放でトークンが失効した後は読めない）。
    過去ログのページネーションは未実装で、毎回全件を返す。セッション規模が
    大きくなった場合のレスポンス肥大化は既知の制約
```

このほか、人間ターン送信・投票・退室等のセッション進行アクションは`POST /{session_id}/human_turn`等の個別RESTエンドポイントで行う（3章参照）。

-----

## 3. WebSocket

### 3.1 接続と認証（first-message auth）

`WS /api/session/{session_id}/ws`に接続後、クライアントは最初のメッセージとして`{"type": "auth", "token": "..."}`を送信する（トークンをURLクエリに含めない設計。ログ・ブラウザ履歴への漏洩を防ぐため）。

- 認証成功: 以降の受信を開始
- 認証失敗: `close(code=4001)`
- セッションが存在しない: `close(code=4004)`

接続維持のため、サーバーは30秒間隔で`{"type": "ping"}`を送信する（Cloudflare Tunnelの100秒アイドルタイムアウト対策）。クライアントは`{"type": "pong"}`で応答する。

### 3.2 クライアント → サーバー メッセージ

| type | ペイロード | タイミング |
|---|---|---|
| `auth` | `{token: string}` | WS接続直後（最初のメッセージ必須） |
| `pong` | なし | サーバーからpingを受け取った時 |

**`auth`/`pong`以外のクライアント→サーバーWSメッセージは存在しない。** 人間ターン送信・投票・退室・キーパー発言等、セッション進行に関わる全アクションは個別のRESTエンドポイント（`POST /{session_id}/human_turn`等）で行い、結果は下記のイベントとして`game_event_bus`経由でWS配信される。WebSocketはサーバーからクライアントへの片方向の通知チャネルとして機能している。

### 3.3 サーバー → クライアント メッセージ

配信されるメッセージには2種類の形がある。

- **`game_event_bus`経由（大半）**: `{"id", "type", "session_id", "payload": {...}, "timestamp"}`の5フィールド構造。中身は`payload`以下を参照する（`type`直下ではない）
- **`ping`/`error`（キープアライブ・レート制限）**: `payload`ラッパー無しで`{"type": "..."}`を直接送信

| type | payload の中身 | タイミング |
|---|---|---|
| `ping` | （payloadラッパー無し・フィールドも無し） | 30秒ごと（keepalive） |
| `error` | （payloadラッパー無し）`{code: string}` | レート制限超過等（`code: "rate_limit"`） |
| `WAITING_FOR_HUMAN` | `{character_id, character_name, round, counters}` | 人間ターン開始時。再接続直後にも、現在人間ターン待ちなら再送される |
| `HUMAN_ACTION` | `{character_id, character_name, text, action, ...}`（`action`は`"speak"`/`"vote"`/`"skip"`/`"keeper"`等） | 人間の発言・投票・キーパー発言・タイムアウトによる自動スキップ等 |
| `AI_TURN_COMPLETED` | AIターン生成結果一式（`text`, `character_id`, `judgments`, `advance_scene`等） | サーバー自律AIターン完了時 |
| `AI_ERROR` | `{error: string}` | AIターン生成失敗時 |
| `JUDGMENT_RESOLVED` | `{character_id, stat_name, notation, roll, judgment_value, success, critical, fumble, ...}` | ダイス判定確定時（TRPGモード） |
| `SCENE_NARRATED` | `{text, judgments}` | AIキーパーがナレーションを生成した時 |
| `TOPIC_CHANGED` | `{new_topic}` | お題変更の投票が可決した時 |
| `FLAG_UPDATED` | `{key, value, gm_only}` | ストーリーフラグが更新された時 |
| `PLAYER_JOINED` | 参加者情報一式（`/join`レスポンスと同型） | 参加者入室時 |
| `PLAYER_LEFT` | `{participant_id, character_id}` | 意図的退室・投票除名（expel）時 |
| `PLAYER_DISCONNECTED` | `{participant_id, character_id, timeout_sec}` | プレイヤー切断検出時 |
| `PLAYER_RECONNECTED` | `{participant_id, character_id}` | 再接続時 |
| `SESSION_STARTED` | `{initiative, name_map, participants}` | ロビー解除・セッション開始時 |
| `SESSION_ENDED` | `{}` | セッション終了時 |
| `LOBBY_UPDATE` | ロビー構成変更の内容（呼び出し箇所により中身が変わる） | ロビー中の参加者・スロット構成変更時 |
| `AUTO_ADVANCE_CHANGED` | `{enabled: bool}` | 自動進行モード切替時 |
| `VISITOR_ICON_READY` | `{character_id}` | 持ち込みキャラのアイコン・立ち絵生成完了時 |
| `TURN_IMAGE_READY` | `{character_id, round, turn, url}` | AIターン自動生成の挿絵完了時 |
| `TURN_AUDIO_READY` | `{character_id, round, turn, url}` | AIターン自動読み上げのTTS合成完了時 |
| `AUDIO_READY` | `{character_id, request_id, url}` | 投票弁明ラウンド・人間プレイヤー自己発言のTTS合成完了時 |
| `SESSION_IMAGE` | `{url}` | キーパーが手動でシーン挿絵を生成した時 |
| `CHARACTER_AUDIT_SKIPPED` | `{character_id, reason}` | 持ち込みキャラのLLM審査がタイムアウト等でfail-openした時 |

`participant_id`について: `char_id=""`の観戦者・キーパーが複数存在するケースがあるため、`PLAYER_LEFT`/`PLAYER_DISCONNECTED`/`PLAYER_RECONNECTED`では`character_id`ではなく`participant_id`で対象を一意に識別する。

### 3.4 WebSocket closeコード

| コード | 意味 |
|---|---|
| `4001` | 認証失敗（tokenなし・無効） |
| `4004` | セッションが存在しない |
| `1008` | JWT秘密鍵再生成による強制切断 |

-----

## 4. エラーコード体系

### HTTP

| ステータス | 用途 |
|---|---|
| `400` | リクエスト形式不正・バリデーションエラー。持ち込みキャラのLLM審査不合格時もこちら（`detail: "Character content rejected: {reason}"`） |
| `401` | JWT未提供・失効・署名不正 |
| `403` | ロール不足（observerがアクション実行等） |
| `404` | セッション・キャラが存在しない |
| `409` | 人間枠が満員・招待コード衝突 |
| `422` | Pydanticバリデーション失敗（FastAPIデフォルト） |
| `429` | レートリミット超過（招待コードブルートフォース等） |

### アプリケーションエラー（WSメッセージ内 `code` フィールド）

| code | 意味 |
|---|---|
| `rate_limit` | WebSocketメッセージ連打超過 |

WS側のアプリケーションレベルエラーは現状`rate_limit`のみ。人間枠の満員判定は`POST /api/session/join`時点（WS接続より前）で行われるため、HTTP `409`で表現される。

-----

## 関連文書

- `docs/DEF_kari_基本設計書.md`: 3章(非同期処理とリアルタイム通知モデル)・7章(マルチエージェント制御)
- `docs/DEF_TRPG卓_自治規約.md`: 参加者ロール・発言力・投票等の自治ルール
- `docs/DEF_kari_操作手順書.md`: オンラインセッションの利用手順（ユーザー向け）
- `docs/DEF_用語集.md`: 用語の定義
