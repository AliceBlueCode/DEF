// 【既知のギャップを可視化するための特性テスト(characterization test)】
//
// 当初は全参加者切断後の idle_shutdown (session.py _schedule_idle_shutdown、
// 300秒固定)を検証する意図だったが、実際に動かしたところ、それとは別の
// もっと基本的な問題で「再接続後にマーカーテキストが見当たらない」ことが
// 判明した(2026-08-08)。
//
// 切り分けのため、320秒待たずに「同一タブで単純にページをリロードするだけ」の
// 最小再現を別途行ったところ、それだけで再現した: SessionTab.tsx は WebSocket
// 接続時に既存の会話履歴を取得・再構築する経路を持たず、`messages` state は
// 接続後に飛んでくるライブイベント(HUMAN_ACTION/AI_TURN_COMPLETED等)の
// 追記のみで構築される。そのためリロード・再接続・(本テストのような)新規
// 参加はいずれも、それ以前の会話が画面上から消える(ホスト側は当該タブを
// リロードしていないので同じ発言を問題なく表示し続けており、サーバー側の
// `session["history"]`自体は失われていないと考えられる — 消えるのはクライアント
// 側の表示状態のみ)。
//
// つまり300秒のidle_shutdown待機はこの現象の再現に必須ではなく、以下の
// アサーションは「300秒放置+全員切断からの再接続」という具体的なシナリオでも
// 同じ表示上のギャップが起きることの一事例として残す。
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

  // 【現状の挙動】新規参加者(=再接続後の実質的な新規参加)には既存の会話履歴が
  // 一切表示されない。履歴取得・再構築の仕組みが実装されたら、このassertは
  // 失敗するようになる(それが直った合図)。
  assert(
    !bodyText.includes(MARKER_TEXT),
    `[KNOWN GAP] no history-replay on (re)join — expected the pre-disconnect message to be invisible after reconnecting, but found it`
  )

  await browser.close()
  console.log('all_disconnect_autostop.js: characterization assertion passed (it documents a gap, not a guarantee — see comment at top)')
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
