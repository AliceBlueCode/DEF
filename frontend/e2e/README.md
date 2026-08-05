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
npm run e2e:vote-expel          # 投票expelでゲストが完全追放され、旧トークンの操作が401で拒否されることを確認
npm run e2e:jwt-regen           # JWT秘密鍵再生成で全接続が強制切断され、旧トークンが失効することを確認
npm run e2e:disconnect-timeout  # 切断タイムアウト(10秒に短縮)経過でターンが自動skipされることを確認
```

各スクリプトはヘッドレスChromiumを2つのブラウザコンテキスト(ホスト/ゲスト)で操作し、`helpers.js`の`assert()`で結果を検証する。失敗すると該当のassertメッセージを`FAIL:`付きで出力し、非ゼロ終了コードで終わる。

## 既知の注意点

- `vote_expel.js`は「投票強制賛成」トグル(グローバル設定)をONにする。他の作業でこの設定を見ている最中に実行すると影響するので、単独実行を前提にしている。
- `disconnect_timeout.js`は「切断タイムアウト(秒)」をUI上の最小値(10秒)に変更する。実行後は元の値(既定60秒)に戻す運用にすること — スクリプト自体は元に戻さない。
- 招待コード・キャラクターJSON持ち込み等はどれもオンラインセッション作成→ロビー→開始という共通フローを通る。新しいシナリオを足す場合は`helpers.js`の関数を再利用する。
