// 【v4.2.1 実機確認手順 C-7 / C-8】追放の可決の後、決定待ちの取り消しと、手番中の人間の追放（続行）。
//
// 構成: オンラインセッション（チャット型）、AI 2人、プレイヤー 1人、ホスト＝キーパー。
// 「投票強制賛成」をオンにして、LLMの判定を待たずに可決させる。
//
// - C-7  可決の後、続行方法を選ばずに取り消す。続行方法のダイアログには閉じる操作が無いので、
//        実際の操作どおりホストのタブを再読み込みし、「次の発言」→ 取り消しボタンで取り消す。
//        全タブに「可決された退場を取り消しました」が出て、対象は initiative に残り、進められる。
// - C-8  プレイヤーの手番（入力待ち）の間にそのプレイヤーを追放し、「人数を減らして続行」を選ぶと、
//        セッションが止まらず次のAIへ進む。
//
// 実行: venv/Scripts/python scripts/e2e_local.py expel_flow
import { chromium } from 'playwright'
import {
  assert, createOnlineSession, joinAsPlayer, lobbyAddAi, mockReset, setToggle, startSession, waitUntil,
} from './helpers.js'

const AIS = ['character_chatgpt_001', 'character_claude_001']
const GUEST_NAME = 'テストゲスト'
const CAST_KEEPER_TEXT = 'キーパーの一票を投じてください。'
const EXPEL_CANCELLED_TEXT = '可決された退場を取り消しました'
const EXPEL_BLOCKED_TEXT = '退場の扱いをキーパーが決めるまで'  // i18n の session.msg.turnBlockedByExpel

const bodyText = page => page.locator('body').innerText()
const lastMockNo = text => Math.max(0, ...[...text.matchAll(/モック応答その(\d+)/g)].map(m => Number(m[1])))
const guestInInitiative = text => text.includes(`🎭${GUEST_NAME}[`)

async function proposeExpelGuest(host, { beforeCommit } = {}) {
  await host.getByRole('button', { name: '🗳 投票' }).click()
  await host.waitForTimeout(400)
  await host.locator('select.session-select').first().selectOption('expel')
  await host.waitForTimeout(200)
  await host.locator('select.session-select').nth(1).selectOption({ label: GUEST_NAME })
  await host.getByRole('button', { name: /投票前ラウンド開始/ }).click()
  await waitUntil(async () => (await bodyText(host)).includes(CAST_KEEPER_TEXT),
    { timeout: 30000, message: 'deliberation finished' })
  // 可決の後は続行方法のダイアログが画面を覆うので、ほかの操作は確定の前に済ませる
  if (beforeCommit) await beforeCommit()
  await host.getByRole('button', { name: '✅ 賛成' }).click()
  await host.getByRole('button', { name: 'このまま人数減で続行' }).waitFor({ state: 'visible', timeout: 15000 })
}

;(async () => {
  await mockReset()
  const browser = await chromium.launch()
  try {
    const { page: host, inviteCode } = await createOnlineSession(browser, { selectMockBackend: true })
    await setToggle(host, '投票強制賛成', true)
    const { page: guest } = await joinAsPlayer(browser, inviteCode)
    for (const [label, p] of [['host', host], ['guest', guest]]) {
      p.on('pageerror', e => console.log(`[${label} pageerror] ${e.message}`))
    }
    for (const id of AIS) await lobbyAddAi(host, id)
    await startSession(host) // 自動進行オン

    const autoBtn = host.locator('button.auto-advance-btn').first()
    const guestInput = guest.locator('input.keeper-input')
    const nextBtn = host.getByRole('button', { name: /次の発言/ })

    // プレイヤーの手番まで進めて、自動進行を止める（キーパーの投票ボタンは自動進行中は押せない）
    await waitUntil(() => guestInput.isEnabled(), { timeout: 60000, message: "player's turn" })
    await autoBtn.click()
    await host.waitForTimeout(300)

    // ── C-7: 可決 → 続行方法を選ばずに取り消す ──
    await proposeExpelGuest(host)
    assert(true, 'C-7: expel passed and the follow-up dialog is shown')
    await host.reload()
    await host.waitForTimeout(2500)
    await nextBtn.waitFor({ state: 'visible', timeout: 15000 })
    // プレイヤーの手番なので「次の発言」は押せないことがある。押せないときは自動進行のオンで
    // 再開を試み、どちらでもサーバーが止めていることを取り消しボタンの表示で確かめる。
    if (await nextBtn.isEnabled()) await nextBtn.click()
    const cancelBtn = host.getByRole('button', { name: '保留中の投票を取り消す' })
    if (!(await cancelBtn.isVisible().catch(() => false))) {
      // 「次の発言」が押せない（人間の手番）場合: プレイヤーが発言しようとしても止まることを見る
      await guestInput.fill('E2E: 退場の決定待ちの発言')
      await guest.getByRole('button', { name: /発言完/ }).click()
      await guest.waitForTimeout(1500)
      assert((await bodyText(guest)).includes(EXPEL_BLOCKED_TEXT), 'C-7: the player is told the turn is paused for the expel decision')
    }
    await waitUntil(async () => {
      if (await cancelBtn.isVisible().catch(() => false)) return true
      if (await nextBtn.isEnabled().catch(() => false)) await nextBtn.click()
      return false
    }, { timeout: 15000, message: 'cancel button on host after reload' })
    await cancelBtn.click()
    for (const [label, p] of [['host', host], ['guest', guest]]) {
      await waitUntil(async () => (await bodyText(p)).includes(EXPEL_CANCELLED_TEXT),
        { timeout: 15000, message: `expel-cancelled notice on ${label} tab` })
    }
    assert(true, 'C-7: "expel cancelled" appears on both tabs')
    assert(guestInInitiative(await bodyText(host)), 'C-7: the target stays in the initiative')

    // ── C-8: プレイヤーの手番中に追放し、「人数を減らして続行」 ──
    await waitUntil(() => guestInput.isEnabled(), { timeout: 30000, message: "player's turn again" })
    await guestInput.fill('') // C-7 で入れた文章を消す
    // 続行の後は自動で進むことを確かめるため、投票の途中で自動進行をオンにする
    await proposeExpelGuest(host, { beforeCommit: () => autoBtn.click() })
    const before = lastMockNo(await bodyText(host))
    await host.getByRole('button', { name: 'このまま人数減で続行' }).click()
    await waitUntil(async () => !guestInInitiative(await bodyText(host)),
      { timeout: 15000, message: 'guest removed from initiative' })
    assert(true, 'C-8: the expelled player is removed from the initiative')
    await waitUntil(async () => lastMockNo(await bodyText(host)) > before,
      { timeout: 30000, message: 'next AI speaks after the expel' })
    assert(true, 'C-8: the session does not stall and the next AI speaks')

    console.log('expel_flow.js: all assertions passed')
  } finally {
    await browser.close()
    await mockReset().catch(() => {})
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
