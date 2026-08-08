// WebSocket接続がCloudflareの100秒アイドルタイムアウトを越えて維持されることを
// 検証する(session.py _keepalive: 固定30秒間隔で {"type":"ping"} を送信する)。
// 100秒以上待つ都合上、実行に2分弱かかる。
//
// 実行: node frontend/e2e/keepalive.js
import { chromium } from 'playwright'
import {
  assert, createOnlineSession, trackAuthTokens, waitForToken,
  openRawWs, rawWsState, rawWsClose, startSession,
} from './helpers.js'

const IDLE_WAIT_SEC = 105 // 30秒間隔pingが3回届く想定 + 余裕

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
  let st = await rawWsState(host, id)
  assert(st.opened, 'raw WS connected')

  console.log(`waiting ${IDLE_WAIT_SEC}s without sending any application traffic...`)
  await host.waitForTimeout(IDLE_WAIT_SEC * 1000)

  st = await rawWsState(host, id)
  assert(!st.closed, `WS still open after ${IDLE_WAIT_SEC}s idle (Cloudflareの100秒タイムアウトを越えて維持)`)

  const pingCount = st.messages.filter(m => {
    try { return JSON.parse(m).type === 'ping' } catch { return false }
  }).length
  assert(pingCount >= 3, `received >=3 keepalive pings in ${IDLE_WAIT_SEC}s at 30s interval (got ${pingCount})`)

  await rawWsClose(host, id)
  await browser.close()
  console.log('keepalive.js: all assertions passed')
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
