// タブA(ゲスト)の発言操作が、リロードなしでタブB(ホスト)にWebSocket経由で
// リアルタイム反映されることを検証する(HUMAN_ACTIONイベントのブロードキャスト)。
//
// 実行: node frontend/e2e/message_sync.js
import { chromium } from 'playwright'
import { assert, createOnlineSession, joinAsPlayer, startSession } from './helpers.js'

const MARKER_TEXT = `sync-check-${Date.now()}`

;(async () => {
  const browser = await chromium.launch()
  try {
  const { page: host, inviteCode } = await createOnlineSession(browser)
  const { page: guest } = await joinAsPlayer(browser, inviteCode)

  await startSession(host)

  const hostMsgCountBefore = await host.locator('.session-msg').count()

  // ゲストの人間ターンが来るまで待つ(イニシアチブ順によっては即時ではない)。
  // 「発言完」ボタンが有効になる=自分のターンであることの目印として使う。
  const sendBtn = guest.getByRole('button', { name: /発言完/ })
  await sendBtn.waitFor({ state: 'visible', timeout: 30000 })

  const textarea = guest.locator('input.keeper-input')
  await textarea.fill(MARKER_TEXT)
  await sendBtn.click()

  // ホスト側は一切操作・リロードしない。WS配信のみで反映されるはず。
  await host.waitForTimeout(2500)

  const hostMsgCountAfter = await host.locator('.session-msg').count()
  assert(hostMsgCountAfter > hostMsgCountBefore, 'host tab message count increased without reload')

  const hostText = await host.locator('body').innerText()
  assert(hostText.includes(MARKER_TEXT), 'host tab shows guest message text in real time (HUMAN_ACTION broadcast)')

  console.log('message_sync.js: all assertions passed')
  } finally {
    // try本体のどこで例外が出てもbrowserを確実に閉じる(vote_expel.js等と同じ理由)。
    await browser.close()
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
