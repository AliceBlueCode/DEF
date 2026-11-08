# マルチプレイヤー機能 E2Eテスト

オンラインセッション機能(投票・認証・切断処理)を実ブラウザ(Playwright)で動かして検証するスクリプト群。`tests/`配下のpytestはバックエンドをTestClient経由で検証するが、こちらはフロントの表示・WebSocketの実際の挙動まで含めて確認する。

## 前提条件

1. バックエンドとフロントエンドを別ターミナルで起動しておく

   ```bash
   python -m uvicorn def_kari.api.main:app --host 127.0.0.1 --port 8511
   cd frontend && npm run dev
   ```

2. `guest_onboarding.js`だけは上記に加えて`npm run build`（`frontend/dist`生成）と、
   `main.py`単体ではなく`dual_run.py`経由の起動が必要（公開ポート＝ゲスト向け
   オンボーディング画面が実際にマウントされる経路そのものを検証するため）。

   ```bash
   cd frontend && npm run build
   python -m def_kari.api.dual_run --local-port 8511 --public-port 8512 --no-trust-cloudflare-tunnel
   ```

3. 設定タブでLLMバックエンド(APIキー等)を疎通可能な状態にしておく。`vote_expel.js`は投票の弁明ラウンドで実際にLLM呼び出しが発生する。
4. Playwrightのブラウザバイナリが未取得なら `npx playwright install chromium` を一度実行する。

## 実行

```bash
npm run e2e:vote-expel               # 投票expelでゲストが完全追放され、旧トークンの操作が401で拒否されることを確認
npm run e2e:jwt-regen                # JWT秘密鍵再生成で全接続が強制切断され、旧トークンが失効することを確認
npm run e2e:disconnect-timeout       # 切断タイムアウト(10秒に短縮)経過でターンが自動skipされることを確認
npm run e2e:ws-auth                  # WS認証: 正常接続/token無し→4001/実在しないセッション→4004
npm run e2e:message-sync             # ゲストの発言操作がリロードなしでホストタブにリアルタイム反映される
npm run e2e:ai-turn-dedup            # /human_turn を並列連打してもAIターンが二重生成されない
npm run e2e:keepalive                # 100秒超アイドルでもWSが30秒間隔pingで維持される(~2分かかる)
npm run e2e:rate-limit               # WSメッセージ61通/60秒でrate_limitエラーが返る
npm run e2e:host-disconnect          # ホストタブを閉じても進行中のAIターンはサーバー側で完走する
npm run e2e:all-disconnect-autostop  # 全員切断→300秒放置→再接続してもセッションが健全(~6分かかる)
npm run e2e:invite-rating            # 招待コードのレーティングとキャラクター側の照合（拒否されること）を確認
npm run e2e:full-integration         # 招待→ゲスト2人参加→セッション開始→双方向リアルタイム同期→終了、を一気通貫で確認
npm run e2e:trpg-keeper-online-join  # TRPGモードのオンラインセッションで、参加者(ホスト以外)のタブでも🎩キーパーのナレーションが発火することを確認
npm run e2e:ai-takeover              # 参加者切断時、ホストのイニシアチブ表示に🤖AI引き継ぎボタンが現れクリックで引き継ぎ済みに切り替わることを確認
npm run e2e:vote-expel-defense-and-handover  # expelの弁明ラウンドが対象者タブにもリアルタイムで届き、対象者自身が意見と反対票を投じられ、キーパーの「AIに引き継ぐ」選択でキャラがinitiativeに残ることを確認
npm run e2e:trpg-guest-sheet-join    # TRPGモードのオンラインセッションで、招待コード参加時に持ち込みキャラJSONのキャラクターシートを選べ、ゲスト自身・ホスト双方のタブに反映されることを確認
npm run e2e:guest-onboarding         # 公開ポート(dual_run.pyのpublic-port)経由のゲストがTERMS同意オンボーディング画面へ振り分けられ、招待コード→TERMS同意→キャラ選択の3ステップを経て最小シェルへ参加できることを確認（他シナリオと違いBASE_URLではなくGUEST_BASE_URL=127.0.0.1:8512を使う。要npm run build + dual_run.py起動）
```

各スクリプトはヘッドレスChromiumを2つのブラウザコンテキスト(ホスト/ゲスト)で操作し、`helpers.js`の`assert()`で結果を検証する。失敗すると該当のassertメッセージを`FAIL:`付きで出力し、非ゼロ終了コードで終わる。

`DEF_kari_マルチプレイ設計書_内部用.md` 13章の統合テスト観点表(12項目)のうち、上記11本(既存3本+新規8本)でJWT期限切れ以外の全項目をカバーする(JWT期限切れは鍵再生成による強制失効を`jwt_regen.js`で代替確認しており、24時間後の自然失効そのものは検証していない)。

## 台本つきシナリオ（v4.2.1 の実機確認手順の自動化、2026-11-08）

モックLLM（`scripts/e2e_mock_llm.py`）に「この呼び出しには、この返事」という台本を差し込み、生成の失敗・弁明の遅れ・思考モデルの出力などを再現する。実機確認手順（`DEF_v4.2.1_実機確認手順_内部用.md`、非公開）の項目に対応する。

| シナリオ | 手順書の項目 | 確かめること |
|---|---|---|
| `generation_failure.js` | A-1・A-2 | 生成失敗の表示（両タブ）、手番が進まない、自動進行が止まる |
| `chat_thinking_output.js` | A-3 | 1人用チャットで、思考モデルの推論や `</think>` が吹き出しに出ない |
| `trpg_skip_designate.js` | B-1〜B-3 | TRPGで、AIの自発スキップの後の自動進行、AIの指名の後に元の順番へ戻ること、キーパーの語りがラウンドに1回 |
| `vote_flow.js` | C-1〜C-5・C-16 | 投票中のターン停止、確定・取り消しの後の進行、弁明の重複なし |
| `expel_flow.js` | C-7・C-8 | 追放の決定待ちの取り消し、手番中の人間の追放（続行） |
| `restart_recovery.js` | D-2〜D-4 | 投票・追放の決定待ちの最中の再起動 |

これらは **`scripts/e2e_local.py` で流す**。gitが管理しているファイルだけを一時ディレクトリへ写し、別のポート（モックLLM 5100・DEF 8611/8612・Vite 3100・再起動の窓口 5199）で独立した環境を立てる。手元で動いているDEF（8511/8512/3000）や本物のTGW（5000）、`data/` の実データには触れない。

```bash
venv/Scripts/python scripts/e2e_local.py generation_failure vote_flow   # 名前は frontend/e2e/<名前>.js
venv/Scripts/python scripts/e2e_local.py --keep expel_flow              # 調査用に環境（ログ）を残す
```

- 台本は `helpers.js` の `mockScript(rules)`／`mockRules.*`（呼び出しの種類ごとの照合条件）で足し、`mockReset()` で消す。`mockCalls()` で、どの台本が何回当たったかを確かめられる。
- 照合は「最後の user メッセージ（いまの指示）」と「system の `あなたの役割: 名前`」で行う。会話の履歴に過去の指示が残るため、全メッセージで照合すると誤って当たる。DEFのプロンプトの文言を変えたら、`mockRules` も直す。
- モックの既定の返事は「モック応答その{n}です」。画面は直近の発言しか出さないので、「AIが新しく発言したか」は件数でなく番号が増えたかで見る。
- CIでは、既存のシナリオの後に同じスクリプトで流している（`.github/workflows/e2e.yml`）。

## 既知の注意点

- `vote_expel.js`は「投票強制賛成」トグル(グローバル設定)をONにする。他の作業でこの設定を見ている最中に実行すると影響するので、単独実行を前提にしている。
- `disconnect_timeout.js`は「切断タイムアウト(秒)」をUI上の最小値(10秒)に変更する。実行後は元の値(既定60秒)に戻す運用にすること — スクリプト自体は元に戻さない。
- `keepalive.js`は実時間で105秒、`all_disconnect_autostop.js`は実時間で320秒待つ。いずれもバックエンドの該当タイムアウト値(30秒周期のping、300秒固定のidle_shutdown)に設定での短縮手段が無いため。CIに組み込む場合はタイムアウト値を長めに取ること。
- `invite_rating.js`は招待コードのレーティング(SFW/R15/R18/UNL)とキャラクターJSON自身の`content_policy.rating_sexual`/`rating_violence`を比較し、R18相当のキャラクターがSFW招待コードへの参加を拒否されることを確認する回帰防止テスト(2026-08-09にレーティングガードを実装、テストも「拒否される」側の主張に書き換え済み)。
- 招待コード・キャラクターJSON持ち込み等はどれもオンラインセッション作成→ロビー→開始という共通フローを通る。新しいシナリオを足す場合は`helpers.js`の関数を再利用する。生WebSocketを直接操作する必要がある場合(認証異常系・レート制限・keepalive等)は`openRawWs`/`rawWsSend`/`rawWsState`/`rawWsClose`と、認証トークンをネットワーク傍受で採取する`trackAuthTokens`/`waitForToken`を使う。
