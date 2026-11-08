// 【v4.2.1 実機確認手順 A-1 / A-2】AIの応答生成に失敗したときの表示と、手番・自動進行の扱い。
//
// モックLLMの台本で、ChatGPT の発言だけを空の返事にして失敗させる（構造化出力のチェーンは、
// 本文が空なら失敗として返す）。期待:
// - ホストとプレイヤーの両方のタブに「〇〇 の応答生成に失敗しました…」が出る
// - 「(generation failed: …)」がキャラの発言として出ない
// - 手番は進まない（もう一度進めると、同じキャラでまた失敗する）
// - 自動進行中に失敗すると、自動進行が止まる（「生成エラーで自動進行を停止しました」）
// - 台本を外すと、そのキャラが普通に発言できる（止まったままにならない）
//
// 実行: venv/Scripts/python scripts/e2e_local.py generation_failure
import { chromium } from 'playwright'
import {
  assert, createOnlineSession, joinAsPlayer, lobbyAddAi, mockReset, mockScript, mockRules, waitUntil,
} from './helpers.js'

const AI_NAME = 'ChatGPT'
const AI_ID = 'character_chatgpt_001'
const FAILED_TEXT = `${AI_NAME} の応答生成に失敗しました`
const AUTO_STOP_TEXT = '生成エラーで自動進行を停止しました'

const count = (text, needle) => text.split(needle).length - 1
const bodyText = page => page.locator('body').innerText()

;(async () => {
  await mockReset()
  await mockScript([mockRules.dialogue(AI_NAME, { content: '' })])

  const browser = await chromium.launch()
  try {
    const { page: host, inviteCode } = await createOnlineSession(browser, { characterName: AI_NAME, selectMockBackend: true })
    const { page: guest } = await joinAsPlayer(browser, inviteCode)
    // ホストが作成画面で選んだキャラは、オンラインセッションの initiative に乗らない。ロビーで足す。
    await lobbyAddAi(host, AI_ID)
    for (const [label, p] of [['host', host], ['guest', guest]]) {
      p.on('pageerror', e => console.log(`[${label} pageerror] ${e.message}`))
    }

    await host.getByRole('button', { name: 'セッション開始' }).click()
    await host.waitForTimeout(1500)

    // ── A-1: 手動進行で、AIの手番を進める ──
    // initiative は開始時にシャッフルされる。プレイヤーが先なら、まずプレイヤーが発言する。
    const nextBtn = host.getByRole('button', { name: /次の発言/ })
    const guestSend = guest.getByRole('button', { name: /発言完/ })
    const guestInput = guest.locator('input.keeper-input')
    await waitUntil(async () => {
      if (count(await bodyText(host), FAILED_TEXT) > 0) return true
      // 「発言完」ボタンは手番でなくても見えるので、入力欄が有効か（自分の手番か）で見る
      if (await guestInput.isEnabled().catch(() => false)) {
        await guestInput.fill('様子を見ます。')
        await guestSend.click()
      } else if (await nextBtn.isEnabled().catch(() => false)) {
        await nextBtn.click()
      }
      await host.waitForTimeout(1500)
      return false
    }, { timeout: 60000, interval: 200, message: 'generation failure message on host tab' })
    assert(true, 'A-1: failure message appears on the host tab')

    await waitUntil(async () => count(await bodyText(guest), FAILED_TEXT) > 0,
      { timeout: 15000, message: 'failure message on guest tab' })
    assert(true, 'A-1: failure message appears on the player tab too')

    for (const [label, p] of [['host', host], ['guest', guest]]) {
      const t = await bodyText(p)
      assert(!t.includes('generation failed'), `A-1: "(generation failed: …)" is not shown as dialogue on the ${label} tab`)
    }

    // 手番は進まない: もう一度進めると、同じキャラでまた失敗する
    const before = count(await bodyText(host), FAILED_TEXT)
    await nextBtn.click()
    await waitUntil(async () => count(await bodyText(host), FAILED_TEXT) > before,
      { timeout: 20000, message: 'second failure for the same character' })
    assert(true, 'A-1: advancing again retries the same character (turn did not move on)')

    // ── A-2: 自動進行中に失敗すると、自動進行が止まる ──
    const beforeAuto = count(await bodyText(host), FAILED_TEXT)
    const beforeAutoGuest = count(await bodyText(guest), FAILED_TEXT)
    await host.locator('button.auto-advance-btn').first().click()
    await waitUntil(async () => {
      const t = await bodyText(host)
      return count(t, FAILED_TEXT) > beforeAuto && t.includes(AUTO_STOP_TEXT)
    }, { timeout: 30000, message: 'auto-advance stops on generation failure' })
    assert(true, 'A-2: auto-advance stops with the auto-stop message')
    // 失敗の通知は、サーバーから全タブに届く（プレイヤーのタブには自動進行のボタンが無いので、通知だけ見る）
    await waitUntil(async () => count(await bodyText(guest), FAILED_TEXT) > beforeAutoGuest,
      { timeout: 15000, message: 'failure notice of the auto-advance turn on guest tab' })
    assert(true, 'A-2: the failure notice reaches the player tab too')

    // ── 台本を外すと、普通に発言できる ──
    await mockReset()
    await nextBtn.click()
    await waitUntil(async () => (await bodyText(host)).includes('モック応答'),
      { timeout: 30000, message: 'AI speaks normally after the failure is cleared' })
    assert(true, 'after clearing the script, the same AI speaks normally')

    console.log('generation_failure.js: all assertions passed')
  } finally {
    await browser.close()
    await mockReset().catch(() => {})
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
