// 【回帰防止テスト】TRPGモードのオンラインセッションで、セッションを作成した
// ホスト以外のタブ(招待コード参加者)でも🎩キーパーのナレーションが発火する
// ことを確認する。
//
// trpgModeRef(useLobbySession.ts)がセッションを実際に作成したタブの
// _initSessionでしか初期化されず、招待コード参加(JoinDialog)・リロード復帰
// のいずれの経路でも一切セットされないまま初期値falseに取り残されていた
// (2026-08-21発覚・修正)。キーパー発火(fireKeeperTurn)の唯一の判定
// (isLastOfRound)はこのrefを見ているため、参加者タブでは🎩キーパーの
// ナレーション・【判定】が永久に発火しなかった一方、プレイヤー同士の
// ターン進行はサーバー主導の別経路のため正常に動き続け、症状が
// 「動いているのに判定だけ入らない」という分かりにくい形で現れていた。
//
// initiativeをゲストの人間キャラ1人だけにすることで、ai_turn_dedup.js/
// full_integration.jsで踏んだシャッフル順序起因のflakinessを避ける
// (要素1つのリストはシャッフルしても順序が変わらない)。ホストはキャラを
// 選ばずキーパー専任のまま作成するため、initiativeにはゲストのキャラだけが
// 乗り、ゲスト自身の発言完了 = 常にラウンドの最後 = 修正前は発火しなかった
// fireKeeperTurnの発火経路そのものを確実に踏める。
//
// 実行: node frontend/e2e/trpg_keeper_online_join.js
import { chromium } from 'playwright'
import { assert, createOnlineTrpgSession, joinAsPlayer, startSession } from './helpers.js'

;(async () => {
  const browser = await chromium.launch()
  try {
    const { page: host, inviteCode } = await createOnlineTrpgSession(browser)
    const { page: guest } = await joinAsPlayer(browser, inviteCode)

    // キーパー発火(fireKeeperTurn)はhumanIsLastOfRoundに加えてautoAdvanceRef.current
    // も必須(SessionTab.tsx:1816)。startSession()が「自動」トグルを有効化する
    // (helpers.jsのコメント参照、AI-firstターンの進行だけでなくこの条件にも必要
    // と判明——2026-08-22、実CIでai_keeperが一度も呼ばれないことから発覚)。
    await startSession(host)

    // ゲストが唯一のinitiativeメンバーなので、開始直後から自分のターンのはず。
    const sendBtn = guest.getByRole('button', { name: /発言完/ })
    await sendBtn.waitFor({ state: 'visible', timeout: 30000 })
    await guest.locator('input.keeper-input').fill('明かりを頼りに、奥へ進む。')
    await sendBtn.click()

    // キーパーのナレーション(モックLLM経由でも非空文字列を返す、内容の質は
    // e2eの検証対象外)がゲスト自身の画面に現れるまで待つ。修正前はここで
    // 一切現れず、プレイヤーのターンだけが無限に待たされる状態になっていた。
    // 表示ラベルはkeeper_char_name未設定時"🎩 Keeper"(英語、session_gameplay.py
    // ai_keeper_narrateのcharacter_nameフォールバック)固定のため、絵文字で判定する。
    await guest.waitForTimeout(10000)
    const guestText = await guest.locator('body').innerText()
    assert(
      guestText.includes('🎩'),
      'keeper narration appears on the JOINING guest tab (regression check for trpgModeRef hydration bug)',
    )

    console.log('trpg_keeper_online_join.js: all assertions passed')
  } finally {
    await browser.close()
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
