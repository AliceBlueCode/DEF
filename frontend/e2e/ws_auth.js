// WebSocketの first-message auth (session.py ws_endpoint) の3パターンを検証する。
// - 正常な token + 実在する session_id → 接続維持
// - token なし(空文字) → 4001 で切断
// - token は正当(session_id claimも一致)だが、接続時点でセッションが実在しない
//   (終了後の古いトークンを使い回す) → 4004 で切断
//
// 実行: node frontend/e2e/ws_auth.js
import { chromium } from 'playwright'
import {
  assert, createOnlineSession, trackAuthTokens, waitForToken,
  openRawWs, rawWsState, rawWsClose, startSession,
} from './helpers.js'

// JWTペイロードは署名検証なしで誰でも読める(暗号化ではない)。session_id claimを
// 取り出すためだけにブラウザ側でbase64url decodeする。
async function decodeJwtSessionId(page, token) {
  return page.evaluate(t => {
    const payload = t.split('.')[1]
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(json).session_id
  }, token)
}

;(async () => {
  const browser = await chromium.launch()

  const { page: host, inviteCode } = await createOnlineSession(browser)
  const tokens = trackAuthTokens(host)
  await startSession(host) // /start 等の認証済みリクエストを発生させてトークンを採取
  const hostToken = await waitForToken(tokens)
  const sessionId = await decodeJwtSessionId(host, hostToken)
  assert(!!sessionId, `session_id decoded from host JWT: ${sessionId}`)

  // --- 1. 正常接続 ---
  const okId = await openRawWs(host, sessionId, hostToken)
  await host.waitForTimeout(1000)
  let st = await rawWsState(host, okId)
  assert(st.opened && !st.closed, 'valid token + existing session: connection stays open')
  await rawWsClose(host, okId)

  // --- 2. token なし → 4001 ---
  const noTokenId = await openRawWs(host, sessionId, '') // 空文字tokenを即送信
  await host.waitForTimeout(800)
  st = await rawWsState(host, noTokenId)
  assert(st.closed && st.closeCode === 4001, `empty token rejected with 4001 (got ${st.closeCode})`)

  // --- 3. 実在しないセッション → 4004 ---
  // ホストにセッションを終了させ、_sessions からエントリを消してから
  // (session_id claimは一致するが実体がない)古いトークンで接続を試みる。
  await host.getByRole('button', { name: 'セッション終了' }).click()
  await host.waitForTimeout(1000) // _end_session の非同期後片付け + 0.3s猶予を待つ

  const goneId = await openRawWs(host, sessionId, hostToken)
  await host.waitForTimeout(800)
  st = await rawWsState(host, goneId)
  assert(st.closed && st.closeCode === 4004, `ended (nonexistent) session rejected with 4004 (got ${st.closeCode})`)

  await browser.close()
  console.log('ws_auth.js: all assertions passed')
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
