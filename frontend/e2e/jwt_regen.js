// JWT秘密鍵の手動再生成(設定タブ)が、接続中の全参加者(ホスト・ゲスト)のWSを
// 強制切断し、旧トークンでの操作を401で拒否することを検証する。
//
// 2026-08-22: ws.oncloseの修正（投票expelで追放された後も無限リトライし続ける
// バグの修正）により、確立済み接続がトークン失効で再接続に失敗した場合
// （4001/4004）は無条件で諦めてセッション作成/参加画面へ戻るようになった。
// JWT再生成もまさにこのケース（再生成後の再接続は必ず署名検証失敗＝4001で
// 弾かれる）に該当するため、ゲスト側のUIは「スキップ」ボタンをクリックする前に
// 既にリセットされてしまう（=旧トークンでのリクエスト自体が飛ばなくなる）。
// 401拒否という本来のセキュリティ特性はUIクリックに頼らず直接fetchで検証し、
// 加えてゲストが切断通知を見てスタート画面へ戻る新しい挙動も別途検証する。
//
// 実行: node frontend/e2e/jwt_regen.js
import { chromium } from 'playwright'
import { assert, openSettingsTab, createOnlineSession, joinAsPlayer, startSession } from './helpers.js'

// JWTペイロードは署名検証なしで誰でも読める(暗号化ではない)。session_id claimを
// 取り出すためだけにブラウザ側でbase64url decodeする(ws_auth.jsと同じ手法)。
async function decodeJwtSessionId(page, token) {
  return page.evaluate(t => {
    const payload = t.split('.')[1]
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(json).session_id
  }, token)
}

;(async () => {
  const browser = await chromium.launch()
  try {
  let hostWsClosed = false
  let guestWsClosed = false

  const { page: host, inviteCode } = await createOnlineSession(browser)
  host.on('websocket', ws => ws.on('close', () => { hostWsClosed = true }))

  const { page: guest, playerToken } = await joinAsPlayer(browser, inviteCode)
  guest.on('websocket', ws => ws.on('close', () => { guestWsClosed = true }))
  const sessionId = await decodeJwtSessionId(guest, playerToken)
  assert(!!sessionId, `session_id decoded from guest (pre-regeneration) token: ${sessionId}`)

  await startSession(host)

  await openSettingsTab(host)
  host.once('dialog', d => d.accept())
  await host.getByRole('button', { name: /JWT秘密鍵を再生成/ }).click()
  await host.waitForTimeout(2000)

  assert(hostWsClosed, 'host WebSocket closed after JWT regeneration')
  assert(guestWsClosed, 'guest WebSocket closed after JWT regeneration')

  const hostText = await host.locator('body').innerText()
  assert(/再生成しました.*\d+件の接続を切断/.test(hostText), 'regeneration result message shown with disconnect count')

  // 旧トークンでの操作は拒否されるはず(UIクリックに頼らず、直接fetchで検証する)
  const staleStatus = await guest.evaluate(
    ({ sid, token }) => fetch(`/api/session/${sid}/human_turn`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ action: 'skip', expected_round: 1 }),
    }).then(r => r.status),
    { sid: sessionId, token: playerToken },
  )
  assert(staleStatus === 401, `pre-regeneration token rejected with 401 (got ${staleStatus})`)

  // ws.oncloseの修正(2026-08-22)により、旧トークンでの再接続が4001で失敗した時点で
  // guest側は諦めてセッション作成/参加画面へ戻り、切断された旨の通知を表示するはず。
  await guest.waitForTimeout(2000)
  const guestText = await guest.locator('body').innerText()
  assert(guestText.includes('切断されました'), 'guest sees removedNotice and returns to the start screen after JWT regeneration (ws.onclose fix)')

  console.log('jwt_regen.js: all assertions passed')
  } finally {
    // try本体のどこで例外が出てもbrowserを確実に閉じる(vote_expel.js等と同じ理由)。
    await browser.close()
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
