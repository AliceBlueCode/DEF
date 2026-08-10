# マルチプレイヤー機能 E2Eテスト

オンラインセッション機能(投票・認証・切断処理)を実ブラウザ(Playwright)で動かして検証するスクリプト群。`tests/`配下のpytestはバックエンドをTestClient経由で検証するが、こちらはフロントの表示・WebSocketの実際の挙動まで含めて確認する。

## 前提条件

1. バックエンドとフロントエンドを別ターミナルで起動しておく

   ```bash
   python -m uvicorn def_kari.api.main:app --host 127.0.0.1 --port 8511
   cd frontend && npm run dev
   ```

2. 設定タブでLLMバックエンド(APIキー等)を疎通可能な状態にしておく。`vote_expel.js`は投票の弁明ラウンドで実際にLLM呼び出しが発生する。
3. Playwrightのブラウザバイナリが未取得なら `npx playwright install chromium` を一度実行する。

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
```

各スクリプトはヘッドレスChromiumを2つのブラウザコンテキスト(ホスト/ゲスト)で操作し、`helpers.js`の`assert()`で結果を検証する。失敗すると該当のassertメッセージを`FAIL:`付きで出力し、非ゼロ終了コードで終わる。

`DEF_kari_マルチプレイ設計書_内部用.md` 13章の統合テスト観点表(12項目)のうち、上記11本(既存3本+新規8本)でJWT期限切れ以外の全項目をカバーする(JWT期限切れは鍵再生成による強制失効を`jwt_regen.js`で代替確認しており、24時間後の自然失効そのものは検証していない)。

## 既知の注意点

- `vote_expel.js`は「投票強制賛成」トグル(グローバル設定)をONにする。他の作業でこの設定を見ている最中に実行すると影響するので、単独実行を前提にしている。
- `disconnect_timeout.js`は「切断タイムアウト(秒)」をUI上の最小値(10秒)に変更する。実行後は元の値(既定60秒)に戻す運用にすること — スクリプト自体は元に戻さない。
- `keepalive.js`は実時間で105秒、`all_disconnect_autostop.js`は実時間で320秒待つ。いずれもバックエンドの該当タイムアウト値(30秒周期のping、300秒固定のidle_shutdown)に設定での短縮手段が無いため。CIに組み込む場合はタイムアウト値を長めに取ること。
- `invite_rating.js`は招待コードのレーティング(SFW/R15/R18/UNL)とキャラクターJSON自身の`content_policy.rating_sexual`/`rating_violence`を比較し、R18相当のキャラクターがSFW招待コードへの参加を拒否されることを確認する回帰防止テスト(2026-08-09にレーティングガードを実装、テストも「拒否される」側の主張に書き換え済み)。
- 招待コード・キャラクターJSON持ち込み等はどれもオンラインセッション作成→ロビー→開始という共通フローを通る。新しいシナリオを足す場合は`helpers.js`の関数を再利用する。生WebSocketを直接操作する必要がある場合(認証異常系・レート制限・keepalive等)は`openRawWs`/`rawWsSend`/`rawWsState`/`rawWsClose`と、認証トークンをネットワーク傍受で採取する`trackAuthTokens`/`waitForToken`を使う。
