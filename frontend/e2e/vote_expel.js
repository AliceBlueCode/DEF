// 投票expel(参加者退場)が実際にゲストを追放し、追放後の操作をサーバーが401で
// 拒否することを検証する。DEF_kari_セキュリティ設計書_内部用.md 5章の実装記録に対応。
//
// 実行: node frontend/e2e/vote_expel.js
import { chromium } from 'playwright'
import { assert, setToggle, createOnlineSession, joinAsPlayer, startSession } from './helpers.js'

;(async () => {
  const browser = await chromium.launch()
  try {
    let guestHttp401Seen = false

    const { page: host, inviteCode } = await createOnlineSession(browser)
    await setToggle(host, '投票強制賛成', true) // LLM判定を待たず即可決させる

    const { page: guest } = await joinAsPlayer(browser, inviteCode)
    guest.on('response', res => {
      if (res.url().includes('/human_turn') && res.status() === 401) guestHttp401Seen = true
    })

    await startSession(host)

    // 投票発議ボタンはdisabled={autoAdvance}のため、startSession()が有効化した「自動」を
    // 一旦オフに戻してから発議する（少し待って先着AIターンがあれば消化させてから切る）。
    await host.waitForTimeout(3000)
    await host.locator('button.auto-advance-btn').first().click()
    await host.waitForTimeout(300)

    // 投票発議: expel対象=ゲスト
    await host.getByRole('button', { name: '🗳 投票' }).click()
    await host.waitForTimeout(400)
    await host.locator('select.session-select').first().selectOption('expel')
    await host.waitForTimeout(200)
    await host.locator('select.session-select').nth(1).selectOption({ label: 'テストゲスト' })
    await host.waitForTimeout(200)
    await host.getByRole('button', { name: /投票前ラウンド開始/ }).click()
    await host.waitForTimeout(15000) // 弁明ラウンド(LLM呼び出しを含む)

    await host.getByRole('button', { name: /賛成/ }).click()
    await host.waitForTimeout(2500)

    const hostText = await host.locator('body').innerText()
    assert(hostText.includes('可決'), 'expel vote passed on host screen')
    assert(!hostText.includes('🎭テストゲスト['), 'expelled guest removed from host initiative display')

    // 追放後、旧トークンでの操作を試みる → バックエンドは401で拒否するはず
    await guest.getByRole('button', { name: /スキップ/ }).click().catch(() => {})
    await guest.waitForTimeout(1500)
    assert(guestHttp401Seen, 'expelled guest action rejected with 401')

    const guestText = await guest.locator('body').innerText()
    assert(!guestText.includes('はスキップしました'), 'no false-success message shown to expelled guest (SessionTab.tsx parseJsonResponse regression check)')

    console.log('vote_expel.js: all assertions passed')
  } finally {
    // try本体のどこで例外が出てもbrowserを確実に閉じる。以前はbrowser.close()を成功パスの
    // 最後にしか呼んでおらず、失敗時にPlaywrightのハンドルが残ってNodeプロセスが終了せず、
    // 実CI実行でtimeout-minutesの上限まで無駄に占有する事態が起きた。
    await browser.close()
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
