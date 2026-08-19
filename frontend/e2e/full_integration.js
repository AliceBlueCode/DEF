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

// input.keeper-inputは自分のターンでない間disabledのまま描画され続ける（要素自体は
// 常にDOMに存在する）ため、visible待ちだけでは「今がそのページの番か」を判定できない。
// isEnabled()を明示的にポーリングする。
async function waitUntilEnabled(locator, timeoutMs) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if (await locator.isEnabled().catch(() => false)) return
    await new Promise(r => setTimeout(r, 300))
  }
  throw new Error(`timed out waiting for ${locator} to become enabled`)
}

async function waitForMyTurn(page, timeoutMs = 60000) {
  await page.getByRole('button', { name: /発言完/ }).waitFor({ state: 'visible', timeout: timeoutMs })
  await waitUntilEnabled(page.locator('input.keeper-input'), timeoutMs)
}

async function speak(page, markerText) {
  await page.locator('input.keeper-input').fill(markerText)
  await page.getByRole('button', { name: /発言完/ }).click()
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

    // 4. guest1・guest2どちらが先にターンを迎えるかはinitiativeのシャッフルにより
    //    実行のたびに変わるため、両者を同時に監視し、先に順番が来た方から発言させる
    //    （どちらか一方が先、と決め打ちしない）。
    const guest1First = await Promise.race([
      waitForMyTurn(guest1).then(() => true),
      waitForMyTurn(guest2).then(() => false),
    ])
    const [firstPage, firstName, firstMarker, secondPage, secondName, secondMarker] = guest1First
      ? [guest1, 'guest1', MARKER_1, guest2, 'guest2', MARKER_2]
      : [guest2, 'guest2', MARKER_2, guest1, 'guest1', MARKER_1]
    const otherPage = firstPage === guest1 ? guest2 : guest1

    await speak(firstPage, firstMarker)
    await host.waitForTimeout(2500)
    await otherPage.waitForTimeout(200)
    const hostTextAfterFirst = await host.locator('body').innerText()
    const otherTextAfterFirst = await otherPage.locator('body').innerText()
    assert(hostTextAfterFirst.includes(firstMarker), `host tab sees ${firstName} message in real time`)
    assert(otherTextAfterFirst.includes(firstMarker), `the other guest tab sees ${firstName} message in real time`)

    // 5. 残った方のターンで発言し、host・最初に発言した方の両方にリアルタイム反映されること
    await waitForMyTurn(secondPage)
    await speak(secondPage, secondMarker)
    await host.waitForTimeout(2500)
    await firstPage.waitForTimeout(200)
    const hostTextAfterSecond = await host.locator('body').innerText()
    const firstTextAfterSecond = await firstPage.locator('body').innerText()
    assert(hostTextAfterSecond.includes(secondMarker), `host tab sees ${secondName} message in real time`)
    assert(firstTextAfterSecond.includes(secondMarker), `the first guest tab sees ${secondName} message in real time`)

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
