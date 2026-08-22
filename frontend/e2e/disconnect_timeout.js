// 唯一のプレイヤーが切断したまま設定秒数(disconnect_timeout_sec)を超えると、
// サーバーが自動的にそのターンをskipして進行を続けることを検証する。
// テストを高速化するため最小値(10秒)に設定してから実行する。
//
// 実行: node frontend/e2e/disconnect_timeout.js
import { chromium } from 'playwright'
import { assert, openSessionTab, openSettingsTab, setNumberSetting, createOnlineSession, joinAsPlayer, startSession } from './helpers.js'

const DISCONNECT_TIMEOUT_SEC = 10
const WAIT_MARGIN_SEC = 10 // タイマー起動の遅延・イベント配信のばらつき吸収

;(async () => {
  const browser = await chromium.launch()
  try {
  const { page: host, inviteCode } = await createOnlineSession(browser)
  await openSettingsTab(host)
  await setNumberSetting(host, '切断タイムアウト', DISCONNECT_TIMEOUT_SEC)
  await openSessionTab(host) // ロビー画面(セッション開始ボタン)に戻る

  const { ctx: guestCtx } = await joinAsPlayer(browser, inviteCode)

  await startSession(host)

  const t0 = Date.now()
  await guestCtx.close() // ゲストのブラウザごと落として切断をシミュレート

  await host.waitForTimeout((DISCONNECT_TIMEOUT_SEC + WAIT_MARGIN_SEC) * 1000)
  const elapsedSec = (Date.now() - t0) / 1000
  console.log(`elapsed since disconnect: ${elapsedSec.toFixed(1)}s (configured timeout: ${DISCONNECT_TIMEOUT_SEC}s)`)

  const hostText = await host.locator('body').innerText()
  assert(hostText.includes('はスキップしました'), 'disconnected guest turn auto-skipped after timeout')

  console.log('disconnect_timeout.js: all assertions passed')
  } finally {
    // try本体のどこで例外が出てもbrowserを確実に閉じる(vote_expel.js等と同じ理由)。
    await browser.close()
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
