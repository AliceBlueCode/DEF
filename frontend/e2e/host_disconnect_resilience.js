// ホストのブラウザが切断していても、既に開始済みのAIターンはサーバー側
// asyncioタスクとして完走し、生存している他タブ(ゲスト)にWS配信されることを
// 検証する(DEF_kari_マルチプレイ設計書_内部用.md §1「ターン実行はサーバーが単一所有」)。
//
// 実行: node frontend/e2e/host_disconnect_resilience.js
import { chromium } from 'playwright'
import { assert, createOnlineSession, joinAsPlayer, startSession } from './helpers.js'

const MARKER_TEXT = `host-dc-check-${Date.now()}`

;(async () => {
  const browser = await chromium.launch()

  const { page: host, ctx: hostCtx, inviteCode } = await createOnlineSession(browser)
  const { page: guest } = await joinAsPlayer(browser, inviteCode)

  await startSession(host)

  const sendBtn = guest.getByRole('button', { name: /発言完/ })
  await sendBtn.waitFor({ state: 'visible', timeout: 30000 })
  const guestMsgCountBefore = await guest.locator('.session-msg').count()

  const textarea = guest.locator('input.keeper-input')
  await textarea.fill(MARKER_TEXT)
  await sendBtn.click() // ここで _run_ai_turns がサーバー側で起動する
  await guest.waitForTimeout(300) // AIタスクが起動する猶予(完了は待たない)

  // ホストのブラウザを即座に落とす。進行中のAIターンはサーバー側タスクなので
  // 影響を受けないはず。
  await hostCtx.close()

  // ゲストは接続を維持したまま、AIの発言完了を待つ
  await guest.waitForTimeout(12000)

  const guestMsgCountAfter = await guest.locator('.session-msg').count()
  assert(guestMsgCountAfter > guestMsgCountBefore, 'guest received new message(s) after host disconnected mid-turn')

  const guestText = await guest.locator('body').innerText()
  assert(guestText.includes(MARKER_TEXT), 'human turn text itself was recorded despite host disconnect')

  await browser.close()
  console.log('host_disconnect_resilience.js: all assertions passed')
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
