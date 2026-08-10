// 統合テスト（複数タブ）: 招待コード発行→複数ゲスト参加→セッション開始→
// 各参加者の発言が全タブにリアルタイム同期→ホストによるセッション終了、を
// 一気通貫で検証する。既存シナリオ（message_sync.js等）はホスト↔ゲスト1人の
// ペアや個別機能を対象にしているが、これは招待から終了までの全体フローを
// ゲスト2人体制で通しで確認する（マルチプレイ設計書§5 Phase 8「統合テスト
// （複数タブ）」に対応）。
//
// 実行: node frontend/e2e/full_integration.js
import { chromium } from 'playwright'
import { assert, createOnlineSession, joinAsPlayer, startSession } from './helpers.js'

const MARKER_1 = `int-test-g1-${Date.now()}`
const MARKER_2 = `int-test-g2-${Date.now()}`

async function waitForMyTurnAndSpeak(page, markerText) {
  const sendBtn = page.getByRole('button', { name: /発言完/ })
  await sendBtn.waitFor({ state: 'visible', timeout: 30000 })
  const textarea = page.locator('input.keeper-input')
  await textarea.fill(markerText)
  await sendBtn.click()
}

;(async () => {
  const browser = await chromium.launch()
  try {
    // 1. ホストがオンラインセッションを作成し、招待コードを発行
    const { page: host, inviteCode } = await createOnlineSession(browser)
    assert(!!inviteCode, 'invite code issued by host')

    // 2. ゲスト2人が同じ招待コードで参加（キャラJSON持ち込み）
    const { page: guest1 } = await joinAsPlayer(browser, inviteCode)
    const { page: guest2 } = await joinAsPlayer(browser, inviteCode)

    // ホスト側ロビーに両ゲストが参加者として反映されていること
    await host.waitForTimeout(500)
    const hostLobbyText = await host.locator('body').innerText()
    assert(hostLobbyText.includes('参加者') || hostLobbyText.includes('2'), 'host lobby reflects joined guests')

    // 3. ホストがセッションを開始
    await startSession(host)

    // 全タブがロビー/参加画面を離れ、セッション画面（終了ボタンの存在）に到達していること
    await guest1.waitForTimeout(500)
    await guest2.waitForTimeout(500)
    for (const [name, page] of [['host', host], ['guest1', guest1], ['guest2', guest2]]) {
      const hasSessionUi = await page.locator('.end-btn, button:has-text("退出")').count()
      assert(hasSessionUi > 0, `${name} tab reached in-session UI after start`)
    }

    // 4. guest1のターンで発言し、host・guest2の両方にリアルタイム反映されること
    await waitForMyTurnAndSpeak(guest1, MARKER_1)
    await host.waitForTimeout(2500)
    await guest2.waitForTimeout(200)
    const hostTextAfterG1 = await host.locator('body').innerText()
    const guest2TextAfterG1 = await guest2.locator('body').innerText()
    assert(hostTextAfterG1.includes(MARKER_1), 'host tab sees guest1 message in real time')
    assert(guest2TextAfterG1.includes(MARKER_1), 'guest2 tab sees guest1 message in real time')

    // 5. guest2のターンで発言し、host・guest1の両方にリアルタイム反映されること
    await waitForMyTurnAndSpeak(guest2, MARKER_2)
    await host.waitForTimeout(2500)
    await guest1.waitForTimeout(200)
    const hostTextAfterG2 = await host.locator('body').innerText()
    const guest1TextAfterG2 = await guest1.locator('body').innerText()
    assert(hostTextAfterG2.includes(MARKER_2), 'host tab sees guest2 message in real time')
    assert(guest1TextAfterG2.includes(MARKER_2), 'guest1 tab sees guest2 message in real time')

    // 6. ホストがセッションを終了し、ゲスト側もSESSION_ENDEDを受けて通常画面に戻ること
    await host.getByRole('button', { name: /セッション終了/ }).click()
    await guest1.waitForTimeout(2000)
    await guest2.waitForTimeout(200)
    const guest1AfterEnd = await guest1.locator('body').innerText()
    const guest2AfterEnd = await guest2.locator('body').innerText()
    assert(guest1AfterEnd.includes('招待コードで参加') || guest1AfterEnd.includes('オンラインセッション作成'), 'guest1 returns to setup screen after SESSION_ENDED broadcast')
    assert(guest2AfterEnd.includes('招待コードで参加') || guest2AfterEnd.includes('オンラインセッション作成'), 'guest2 returns to setup screen after SESSION_ENDED broadcast')

    console.log('full_integration.js: all assertions passed')
  } finally {
    await browser.close()
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
