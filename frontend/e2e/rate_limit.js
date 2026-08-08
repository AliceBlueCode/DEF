// WebSocketメッセージのレート制限(session.py _check_ws_rate: 60メッセージ/60秒)を
// 超過すると {"type":"error","code":"rate_limit"} が返ることを検証する。
//
// 実行: node frontend/e2e/rate_limit.js
import { chromium } from 'playwright'
import {
  assert, createOnlineSession, trackAuthTokens, waitForToken,
  openRawWs, rawWsSend, rawWsState, rawWsClose, startSession,
} from './helpers.js'

const N_MESSAGES = 61 // limit=60 のため61通目で超過するはず

async function decodeJwtSessionId(page, token) {
  return page.evaluate(t => {
    const payload = t.split('.')[1]
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(json).session_id
  }, token)
}

;(async () => {
  const browser = await chromium.launch()

  const { page: host } = await createOnlineSession(browser)
  const tokens = trackAuthTokens(host)
  await startSession(host)
  const hostToken = await waitForToken(tokens)
  const sessionId = await decodeJwtSessionId(host, hostToken)

  const id = await openRawWs(host, sessionId, hostToken)
  await host.waitForTimeout(500)

  // pong型メッセージ(no-op)をN回連続送信。_check_ws_rateはメッセージ種別を問わず
  // 受信ごとにカウントするため、pongでよい。
  for (let i = 0; i < N_MESSAGES; i++) {
    await rawWsSend(host, id, { type: 'pong' })
  }
  await host.waitForTimeout(1500)

  const st = await rawWsState(host, id)
  const rateLimitHit = st.messages.some(m => {
    try {
      const parsed = JSON.parse(m)
      return parsed.type === 'error' && parsed.code === 'rate_limit'
    } catch { return false }
  })
  assert(rateLimitHit, `rate_limit error received after sending ${N_MESSAGES} messages within the 60s window`)
  assert(!st.closed, 'exceeding rate limit does not close the connection (soft-rejected, not disconnected)')

  await rawWsClose(host, id)
  await browser.close()
  console.log('rate_limit.js: all assertions passed')
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
