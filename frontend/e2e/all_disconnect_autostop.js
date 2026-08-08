// 【回帰防止テスト】全参加者切断後、idle_shutdown待機を挟んだ再接続でも
// 会話履歴が復元されること。
//
// 当初は idle_shutdown (session.py _schedule_idle_shutdown、300秒固定) を
// 検証する意図だったが、実際に動かしたところ、それとは別のもっと基本的な
// 問題で「再接続後にマーカーテキストが見当たらない」ことが判明した
// (2026-08-08)。原因は SessionTab.tsx が WebSocket接続時に既存の会話履歴を
// 取得・再構築する経路を持たず、`messages` state が接続後に飛んでくる
// ライブイベントの追記のみで構築されていたこと。GET /api/session/{id}から
// 履歴を取得して再構築する経路を追加して修正済み(2026-08-08、同日中)。
//
// 300秒のidle_shutdown待機自体はこの現象の再現に必須ではなかった
// (単純なページリロードだけでも再現した) が、「300秒放置+全員切断から
// の再接続」という一番厳しいシナリオでも履歴が復元されることの確認として
// このテストは残す。
//
// 実行: node frontend/e2e/all_disconnect_autostop.js
import { chromium } from 'playwright'
import { assert, createOnlineSession, joinAsPlayer, startSession } from './helpers.js'

const MARKER_TEXT = `autostop-check-${Date.now()}`
const IDLE_SHUTDOWN_SEC = 300
const WAIT_MARGIN_SEC = 20

;(async () => {
  const browser = await chromium.launch()

  const { page: host, ctx: hostCtx, inviteCode } = await createOnlineSession(browser)
  const { page: guest, ctx: guestCtx } = await joinAsPlayer(browser, inviteCode)

  await startSession(host)

  const sendBtn = guest.getByRole('button', { name: /発言完/ })
  await sendBtn.waitFor({ state: 'visible', timeout: 30000 })

  const textarea = guest.locator('input.keeper-input')
  await textarea.fill(MARKER_TEXT)
  await sendBtn.click() // _run_ai_turns がサーバー側で起動する

  // AIの応答が完了する前に全タブを落とす(ws_connectionsを空にしてidle_shutdownタイマーを起動させる)
  await host.waitForTimeout(200)
  await hostCtx.close()
  await guestCtx.close()

  console.log(`waiting ${IDLE_SHUTDOWN_SEC + WAIT_MARGIN_SEC}s for idle_shutdown to cancel the in-flight AI task...`)
  await new Promise(r => setTimeout(r, (IDLE_SHUTDOWN_SEC + WAIT_MARGIN_SEC) * 1000))

  // 再接続して現在の画面を確認する。
  const { page: rejoined } = await joinAsPlayer(browser, inviteCode)
  await rejoined.waitForTimeout(1500)
  const bodyText = await rejoined.locator('body').innerText()

  assert(
    bodyText.includes(MARKER_TEXT),
    `pre-disconnect message should be visible after (re)joining post idle_shutdown-wait (history replay) — not found`
  )

  await browser.close()
  console.log('all_disconnect_autostop.js: regression guard passed (history replay survives all-disconnect + idle_shutdown wait)')
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
