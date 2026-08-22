// JWT秘密鍵の手動再生成(設定タブ)が、接続中の全参加者(ホスト・ゲスト)のWSを
// 強制切断し、旧トークンでの操作を401で拒否することを検証する。
//
// 実行: node frontend/e2e/jwt_regen.js
import { chromium } from 'playwright'
import { assert, openSettingsTab, createOnlineSession, joinAsPlayer, startSession } from './helpers.js'

;(async () => {
  const browser = await chromium.launch()
  try {
  let hostWsClosed = false
  let guestWsClosed = false
  let guestHttp401Seen = false

  const { page: host, inviteCode } = await createOnlineSession(browser)
  host.on('websocket', ws => ws.on('close', () => { hostWsClosed = true }))

  const { page: guest } = await joinAsPlayer(browser, inviteCode)
  guest.on('websocket', ws => ws.on('close', () => { guestWsClosed = true }))
  guest.on('response', res => {
    if (res.url().includes('/human_turn') && res.status() === 401) guestHttp401Seen = true
  })

  await startSession(host)

  await openSettingsTab(host)
  host.once('dialog', d => d.accept())
  await host.getByRole('button', { name: /JWT秘密鍵を再生成/ }).click()
  await host.waitForTimeout(2000)

  assert(hostWsClosed, 'host WebSocket closed after JWT regeneration')
  assert(guestWsClosed, 'guest WebSocket closed after JWT regeneration')

  const hostText = await host.locator('body').innerText()
  assert(/再生成しました.*\d+件の接続を切断/.test(hostText), 'regeneration result message shown with disconnect count')

  // 旧トークンでの操作は拒否されるはず
  await guest.getByRole('button', { name: /スキップ/ }).click().catch(() => {})
  await guest.waitForTimeout(1500)
  assert(guestHttp401Seen, 'guest action with pre-regeneration token rejected with 401')

  console.log('jwt_regen.js: all assertions passed')
  } finally {
    // try本体のどこで例外が出てもbrowserを確実に閉じる(vote_expel.js等と同じ理由)。
    await browser.close()
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
