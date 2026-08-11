# DEF TRPG GM Agent System 設計書

TRPGモード上で動作するマルチエージェントシステムの設計を扱う。DEFの既存インフラ（`session.py` / `characters.py` 等）を土台に、GM・プレイヤー・NPCの各役割をAgentとして定義し拡張する。

**目的**: AIだけでTRPGセッションを完結させる基盤を作る。人間が参加しても・しなくても動く。

-----

## 1. 設計哲学

### Character Authenticity over Human Imitation

本システムはAIが人間を模倣することを目指さない。評価軸は「人間らしさ」ではなく：
- そのキャラクターとして一貫した振る舞いができるか
- 世界観との整合性が取れているか
- 判断に一貫性があるか

**AIであることは欠点ではなく、一つの個性として扱う。**

### Character First

本プロジェクトが扱うのは「人間の模倣」ではなく「永続するキャラクター」。キャラクターは人間でも・AIでも・架空存在でも・本人格でもよい。重要なのは **そのキャラクターとして自然であること**。

### Character ≠ Agent（最重要）

**Agent と Character は別物**。混同しない。

```
Character（永続する存在）
    ↓ owns
Agent Instance（役割・動作の型）
    ↓ runs on
Runtime: LLM | Human | Rule（差し替え可能）
```

- **Character** = `profile.json` で定義された永続する存在。人格・外見・価値観・記憶を持つ
- **Agent** = そのCharacterが「何の役割で動くか」のインスタンス（Player / NPC / Observer）
- **Runtime** = 実際に動かす主体。LLMでも・人間でも・ルールエンジンでも差し替えられる

この設計により：
- 同じキャラクターを人間が操作しても、別モデルが操作しても、Characterは変わらない
- AIが進化してもサービスが変わっても、キャラクターは残る
- これがDEFの「Characters persist longer than conversations」の実装形

**GM Agentだけは特殊**。特定のCharacterを所有せず、World/Story/NPC/Directorを管理する管理者Agentとして機能する。

-----

## 2. アーキテクチャ

### レイヤー構成

```
Application Layer
└── Game Manager

Agent Layer
├── GM Agent                  ← Character非依存の管理者
├── Player Agent × N          ← 各Characterが所有する
├── NPC Agent × N             ← 各Characterが所有する
└── Observer Agent (将来)     ← Character非依存の観察者

Service Layer
├── Context Builder
├── Event Bus
├── Rule Engine
└── Dice Engine

Domain Layer
├── Character
├── World
├── Story / Campaign
├── Quest
├── Memory
└── Relationship

Infrastructure Layer
├── LLM Backend
├── History Store
├── JSON Storage
└── Session API
```

### Character → Agent → Runtime の関係

```
hanfei_20260611 (Character)
    └── Player Agent
            └── Runtime: LLM (local model)

司祭ジョセフ (Character / NPC)
    └── NPC Agent
            └── Runtime: LLM

人間プレイヤー (Human)
    └── Player Agent
            └── Runtime: Human (waiting_for_human)

GM Agent
    ├── World Manager
    ├── Story Manager
    ├── NPC Controller
    ├── Director
    └── Runtime: LLM
```

**Game Manager のみがプレイヤー（人間/AI）と対話する。**

-----

## 3. Agent Interface

すべてのAgentが実装する共通インターフェース：

```python
class Agent:
    def perceive(self, context: dict) -> None:
        """現在の状況・イベントを受け取る"""

    def think(self) -> list[str]:
        """目標・記憶・性格をもとに行動候補を生成する"""

    def act(self) -> AgentResult:
        """行動・発言を決定して返す"""

    def reflect(self, result: AgentResult) -> None:
        """経験を記憶に反映する"""
```

```python
@dataclass
class AgentResult:
    message: str          # 発言・行動テキスト
    state_update: dict    # 状態変化
    events: list[str]     # 発火するイベント名
    confidence: float     # 0.0〜1.0
```

GMとPlayerで異なるのは**持っている責任だけ**。フレームワークは共通。

| 機能 | GM Agent | Player Agent | NPC Agent |
|------|----------|--------------|-----------|
| 世界管理 | ✓ | ✗ | ✗ |
| NPC操作 | ✓ | ✗ | ✗ |
| ルール裁定 | ✓ | ✗（要求のみ） | ✗ |
| 自キャラ操作 | ✗ | ✓ | ✓ |
| パーティ相談 | ✗ | ✓ | ✗ |
| シナリオ進行 | ✓ | ✗ | ✗ |

-----

## 4. GM Agent

Character を所有しない特殊な管理者Agent。ルールブック・シナリオ・世界設定・全NPCの状態を把握し、セッションを進行させる。`def_kari/gm/gm_agent.py`に実装されている。

### 内部サブ責任

| 責任 | 説明 |
|------|------|
| World | 場所・環境・世界の状態を把握・描写する |
| Story | Campaign/Chapter/Scene/Flags を管理し進行を制御する |
| Rule | ルールブックに基づき判定の要否・結果を裁定する |
| Director | 演出・雰囲気・次のシーンへの誘導を担う |
| GM Planner | 次のイベント・NPC登場タイミング・クライマックス制御 |

### GMだけが知る真実

Context Builder の設計原則として、GMは「全情報」を持つ。Player Agentには「そのキャラクターが知っている情報のみ」を渡す。これが情報の非対称性を生み、ゲームになる。

```
GM: { "truth": "司祭は吸血鬼" }
PlayerA: { "knowledge": ["司祭が怪しい"] }
PlayerB: { "knowledge": [] }   ← 何も知らない状態
```

### コンテキスト構成

```
システム: キーパーの役割定義
ルールブック: 判定基準・世界観
シナリオ: 現在シーン・目標・フラグ状態（GM専用）
キャラクター情報: 参加者一覧・名前マップ
履歴: 直近Nターン
```

### AIキーパーの指名と人格インストール（F-21）

- セッション開始時にキーパー設定で「AIキーパー」を選択
- キャラクター指名は任意。未指定の場合は**無個性モード**（機械的な進行文のみ）
- 指名されたキャラクターは参加者のイニシアチブには入らない
- 指名後はそのキャラクターの人格・口調でキーパーを担わせる（「機能として動く」を先に確保し、「誰として動くか」は後から被せる設計）

**AIキーパーの責務:**
- ルールブック（F-20）を最優先で遵守
- 場面描写・進行（ルールに従った情景・状況説明）
- ダイスロール要求と判定結果への反応（成功・失敗の描写）
- `choices` の提示と選択後の分岐進行

### セーフティ（F-8）との関係

AIキーパーの情景描写（「血痕がある」「遺体が...」等）が F-8 で完全マスクされると進行停止する。
→ キーパーレイヤーの発言は `warn` 相当で扱い、`mask` にならないようガードレールを設ける。

-----

## 5. Player Agent

Character が所有するAgent。Character の `profile.json` から人格・価値観を読み込み、Goal/Emotion/Memory をもとに意思決定する。`def_kari/gm/player_agent.py`に実装されている。

### 内部構成

```
Player Agent
├── Personality   ← Character の profile.json から読み込む（設定）
├── Character Sheet ← game_rules_sheets（HP/MP/スキル等）
├── Goal          ← 3階層（最終目標 / 今 / 直近）
├── Emotion       ← Fear / Trust / Anger / Hope / Stress（動的）
├── Memory        ← Character の memory/ から読み込む（経験）
├── Knowledge     ← キャラが知っていること（他PCが知らない情報も）
├── Planner       ← 行動候補生成 → Emotionでスコアリング → 決定
└── Dialogue      ← 行動をロールプレイ発言に変換する
```

### Goal 3階層

```json
{
  "ultimate": "生き残る",
  "current": "神殿へ行く",
  "immediate": "司祭に質問する"
}
```

下位Goalが達成 or 断念されると上位から次の `immediate` を生成する。

### 意思決定フロー

```
GM説明
  → 状況理解（perceive）
  → Goal確認・Memory参照（think）
  → 行動候補生成
  → Emotionでスコアリング
  → 決定（act）
  → Dialogue生成
  → 送信
  → reflect（Memoryに経験を追加）
```

### Plannerの段階

- **静的Planner**: Goalは`profile.json`に保持し、Emotion値によるルールベースのスコアリングで行動候補を選ぶ
- **LLM Planner**: 設定で有効化すると、Plannerに小さなLLM呼び出しを追加して候補を動的生成する

-----

## 6. NPC Agent

Character が所有するAgent。Player Agent と同じ構造を持つが、パーティ相談機能を持たない。

追加で持たせるもの（Goal/Knowledge/Relationship）:
```json
{
  "goal": { "immediate": "探索者に情報を与えずに立ち去る" },
  "knowledge": ["地下室の存在を知っている"],
  "relationship": { "hanfei_20260611": { "trust": 20, "hostility": 60 } }
}
```

NPCのKnowledge/Relationshipはセッション中に動的更新される（`session["npc_state"]`）。

-----

## 7. Observer Agent（将来構想・未実装）

セッションに参加せず、外から観察・記録するAgent。Character を所有しない。

### 役割と Episode 連携

```
TRPG Session
    ↓ Observer が観察・記録
Episode（小説素材）
    ↓ Novelモードで執筆
Novel
```

「各場面の要約」ではなく「**キャラクターの人生記録**」として機能させる。TRPGでの出来事（失敗談・武勇伝）が、Chatモードでの会話ネタとして自然に出てくる状態が理想。

役割:
- 場面ごとのハイライト・感情の動きを抽出
- キャラクター成長の記録
- セッション後のリプレイ素材生成
- DEFの「Episode（小説執筆）」モードとの連携

**DEFの中核価値と直結する**構想のため、設計は早期に固めているが実装は将来フェーズ。

### TRPGセッションとChatセッションの連続性

TRPGセッションで起きたことはキャラクターの記憶・経験として永続する。

- AIキャラクターはChatセッションで「あのとき〇〇のシナリオで…」と自分が演じた体験を話題に出せる
- TRPGの冒険がキャラクターの人格・関係性・記憶を構成する一部になる
- DEFの「キャラクターは単なるチャット履歴ではない」という設計思想と直結する

実装上はTRPGセッションのログをキャラクターの記憶として `memory/episodic/` に反映する仕組みが必要で、Observer Agentが担う想定。

-----

## 8. Service Layer

### 8.1 Context Builder

`def_kari/gm/context_builder.py`に、GM/Player/NPC向けにそれぞれ異なる情報を渡す関数群が実装されている。

**設計原則**: Agentに渡す情報を最小化する。全情報を渡すと「世界の全知視点AI」になる。

#### インターフェース設計

```python
class ContextBuilder:

    def build_for_gm(self, rulebook, scenario, session, user_lang) -> str:
        """GMコンテキスト。
        - シナリオ全情報（gm_notes / goal / gm_only フラグ含む）
        - 全キャラクターシート（HP/MP/SAN 等）
        - 現在フラグ状態（gm_only 含む全フラグ）
        - 世界状態
        """

    def build_for_player(self, char_id, character, rulebook, scenario, session, user_lang) -> str:
        """プレイヤーコンテキスト。
        - 現在シーンの description のみ（gm_notes は除外）
        - 公開NPCの description のみ（gm_notes / goal は除外）
        - 自分のキャラクターシートのみ
        - 自分の knowledge（静的: profile.json + 動的: セッション中に獲得）
        - gm_only: false のフラグで自分に関係するもの
        """

    def build_for_npc(self, npc_id, npc_data, rulebook, scenario, session, user_lang) -> str:
        """NPCコンテキスト。
        - 自分の goal（NPCには見えている）
        - 自分の knowledge
        - PCへの relationship（trust / hostility）
        - 公開シーン情報
        """
```

#### シナリオJSON スキーマ拡張

情報非対称を実現するために、シナリオ側に `gm_notes` / `gm_only` フィールドを持たせる：

```json
{
  "scenes": [{
    "id": "scene_1",
    "title": "玄関ホール",
    "description": "古い屋敷の玄関ホール。執事が出迎える。",
    "gm_notes":   "執事の右手が微かに震えている。悪魔憑きの徴候。",
    "npcs":       ["butler_johnson"]
  }],
  "npcs": [{
    "id":          "butler_johnson",
    "name":        "執事・ジョンソン",
    "description": "礼儀正しい老人",
    "gm_notes":    "悪魔に魂を売った。見破られると逃走する。",
    "goal":        "プレイヤーを別室に誘い込む"
  }],
  "flags": [
    { "key": "found_secret_door",   "value": false, "gm_only": false },
    { "key": "butler_is_possessed", "value": true,  "gm_only": true  }
  ]
}
```

ルール:
- `description` → 全員に見える
- `gm_notes` / `goal` / `gm_only: true` フラグ → GM専用（Player/NPC には渡さない）

セッション中に`gm_only: false`のフラグが更新されたとき、そのキャラクターの「知っていること」（`session["player_knowledge"]`）に追記される（Event Busの`FLAG_UPDATED`ハンドラ経由）。静的な知識（セッション開始時から知っていること）は`profile.json`の`knowledge`フィールドに置く。

### 8.2 Event Bus

`def_kari/gm/events.py`にゲームロジック用のイベントバスが実装されている（TTS/画像完了通知専用の`core/events.py`とは別名前空間）。

```python
# ゲームロジック系イベント
NPC_DEAD         = "npc_dead"
FLAG_UPDATED     = "flag_updated"
QUEST_STARTED    = "quest_started"
QUEST_COMPLETED  = "quest_completed"
DAMAGE_APPLIED   = "damage_applied"
STATUS_CHANGED   = "status_changed"
SCENE_CHANGED    = "scene_changed"
```

連鎖の例:

```
Player Attack
  → Rule Engine（ダメージ計算）
  → DAMAGE_APPLIED イベント
  → NPC Agent（HP更新）
  → NPC_DEAD イベント（HP≤0なら）
  → Story Manager（フラグ更新）
  → FLAG_UPDATED イベント
  → Observer（記録）
  → Director（演出）
```

マルチプレイヤー対応（`docs/DEF_kari_マルチプレイAPIリファレンス.md`参照）は、このEvent Busに購読者を追加する形で実現されている。

### 8.3 Rule Engine

`def_kari/trpg/rule_engine.py`に実装されている。

**設計原則**: ルール解釈（成否判定）は**LLMに任せない**。コードが決定論的に処理する。LLMは裁定者ではなく演出者。

```
悪い設計: Player → LLM「攻撃成功しました」
良い設計: Player → Rule Engine（成功/失敗）→ LLM「どう演出するか」
```

ゲームシステムごとの差異はルールブックJSON（`docs/DEF_TRPG_ルールブック.md`参照）で吸収する。

### 8.4 Dice Engine

`POST /api/trpg/dice`として実装されている。`secrets.randbelow()`で安全な乱数を生成する。対応記法は`NdM±K`形式（詳細は`docs/DEF_用語集.md`参照）。

-----

## 9. Domain Layer

### Character

DEF Characterの `profile.json` と `memory/` ディレクトリで構成する。

**重要**: `profile.json` は「設定」、`memory/` は「経験」。混在させない。

```
Character/
├── profile.json       ← 永続する人格・外見・価値観（設定）
└── memory/
    ├── episodic/      ← 出来事の記憶（「あのとき○○で失敗した」）
    ├── knowledge/     ← 獲得した知識（「地下室の存在を知っている」）
    └── relationship/  ← 関係性・感情値（動的更新）
```

`profile.json` に入れるもの: name / personality / speech_style / appearance / base_values
`memory/` に入れるもの: 経験・獲得情報・感情の変化

### Goal と Emotion（セッション内動的データ）

Goalと現在のEmotionはセッション中に変化するため、セッション状態として保持する。セッション終了後に `memory/episodic/` に記録する。

```json
{
  "goal": { "ultimate": "生き残る", "current": "神殿へ行く", "immediate": "司祭に質問する" },
  "emotion": { "fear": 20, "trust": 60, "anger": 10, "hope": 70, "stress": 30 }
}
```

### World / Story / Campaign

`def_kari/gm/domain.py`に`World` / `WorldNPC` / `WorldLocation` / `Story` / `StoryScene` / `Campaign`のデータクラスが定義されている。Campaign → Chapter → Scene → Flags の階層で管理する構想だが、永続化・ディレクトリ構造は未整備。

### ルールブック・シナリオ データ配置（F-20）

```
data/public/trpg_rules/      ← 公開ルールブック・シナリオ（Git管理対象）
data/private/trpg_rules/     ← NSFWルールブック・シナリオ（gitignore対象）
```

ファイル形式はJSON必須（Rule Engine が解釈するため）。ルールブックの詳細スキーマは`docs/DEF_TRPG_ルールブック.md`を参照。

セッション開始時にルールブック・シナリオをドロップダウンで選択すると、JSONがシステムプロンプトに展開される。未選択の場合は通常セッションと同じ動作になる。

### キャラクターシートの永続化

`game_rules_sheets` フィールドをキャラクターの `profile.json` に永続保存する。

- ルールシステムをまたいで複数の `game_rules_sheets` を保持できる（CoC用・DEFオリジナル用等）
- スキルの割り振り・能力値の現在値はセッションをまたいで保持される
- セッション開始時にどのルールシートを使うかを選択する

-----

## 10. 実装状況

| 設計概念 | 実装状況 | 場所 |
|---------|----------|------|
| Game Manager | ✅ 実装済み | `session.py` 全体 |
| GM Agent | ✅ 実装済み | `gm/gm_agent.py` |
| Context Builder（GM/Player/NPC分離） | ✅ 実装済み | `gm/context_builder.py` |
| Turn制御・Initiative | ✅ 実装済み | `session.py: start_session()` / `next_turn()` |
| Human/AI混在（Runtime切り替え相当） | ✅ 実装済み | `player_type == "human"` |
| Party Coordinator | ✅ 実装済み | `vote_deliberate()` / `vote_commit()` |
| Director（指名） | ✅ 実装済み | `designate_next()` |
| Rule Engine | ✅ 実装済み | `trpg/rule_engine.py` |
| Dice Engine | ✅ 実装済み | `api/routes/trpg.py: dice_roll()` |
| Event Bus（ゲームロジック用） | ✅ 実装済み | `gm/events.py` |
| World / Story / Campaign データモデル | ✅ 実装済み（永続化は未整備） | `gm/domain.py` |
| Player Agent Goal（静的） | ✅ 実装済み | `profile.json > goals` |
| Player Agent Planner（LLM） | ✅ 実装済み（設定で有効化） | `gm/player_agent.py` |
| NPC Knowledge / Relationship 動的更新 | ✅ 実装済み | `session.py: npc_state` |
| Memory 分離（profile vs experience） | ✅ 実装済み | `gm/memory.py: episodic` |
| セッション内 player_knowledge 管理 | ✅ 実装済み | `session.py: player_knowledge` |
| シナリオJSON gm_notes / gm_only 拡張 | ✅ 実装済み | `context_builder.py` |
| ダメージテーブル・シナリオ連動ダメージ・死者視点モード | ✅ 実装済み | 詳細は`docs/DEF_TRPG_ルールブック.md`参照 |
| オンラインマルチプレイヤー | ✅ 実装済み | 詳細は`docs/DEF_kari_マルチプレイAPIリファレンス.md`参照 |
| Observer Agent | 🔲 未実装（将来構想） | — |
| `relationship`の`memory/`への移行 | 🔲 未着手（現状`profile.json`に同居） | — |
| F-22-Git 世界線分岐 | 🔲 未実装（将来構想、下記11章参照） | — |

-----

## 11. F-22-Git 世界線分岐（将来構想）

- `choices` から選択肢を選ぶと `git checkout -b <branch_id>` でブランチ分岐
- マージは絶対しない（DEF-Character リポジトリの方針と同じ。世界線は独立したまま存在し続ける）
- 分岐後はそのブランチで進行が続く
- UIに「現在の世界線」を表示

**技術的課題**: セッション中の `git checkout -b` はバックエンドプロセスとファイルシステム状態に影響する。セッションが走ったまま分岐するリスクを要検討。

-----

## 12. UIイメージ

### Sessionタブへの追加

```
[ ▶ 開始 ]

TRPGモード: [OFF / ON]
  └── ルールブック: [---- 選択 ----]
  └── シナリオ:    [---- 選択 ----]
  └── AIキーパー:  [---- 指名しない ----]

[ 🎲 ダイス ]  記法: [1d100    ]  [ 振る ]
```

### ダイスロール結果（チャットログ内）

```
🎲 目星: 1d100 → 37（成功：判定値 55）
```

-----

## 関連文書

- `docs/DEF_kari_基本設計書.md`: F-20〜F-22（TRPGゲーム拡張機能）
- `docs/DEF_TRPG_ルールブック.md`: ルールブックJSONのスキーマ・判定式・ダメージテーブル
- `docs/DEF_TRPG卓_自治規約.md`: 発言力・投票等の自治ルール
- `docs/DEF_kari_マルチプレイAPIリファレンス.md`: オンラインマルチプレイヤーのプロトコル
- `docs/DEF_用語集.md`: 用語の定義
