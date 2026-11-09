// 【v4.2.1 実機確認手順 D-2 / D-3 / D-4】投票・追放の決定待ちの最中にサーバーを再起動する。
//
// scripts/e2e_local.py の制御用の窓口でバックエンドを止めて起動し直す（restartBackend）。
// 起動時は自動保存からセッションを復元し、保留中の投票・追放の決定待ちを捨てて履歴に通知を残す。
//
// - D-2  保留中の投票があるまま再起動 → 履歴に「サーバーの再起動のため、保留中の投票を取り消しました」が
//        1回だけ出て、そのまま進められる
// - D-3  何もせずに、もう1回再起動 → 通知が増えない（1回のまま）
// - D-4  追放の可決の後、続行方法を選ばずに再起動 → 「可決された退場の処理を取り消しました」が出て、
//        対象は残り、進められる
//
// 実行: venv/Scripts/python scripts/e2e_local.py restart_recovery
import { chromium } from 'playwright'
import {
  assert, createOnlineSession, getSessionAuth, joinAsPlayer, lobbyAddAi, mockReset, restartBackend, sessionApi, setToggle,
  startSession, waitUntil,
} from './helpers.js'

const AIS = ['character_chatgpt_001', 'character_claude_001']
const GUEST_NAME = 'テストゲスト'
const CAST_KEEPER_TEXT = 'キーパーの一票を投じてください。'
const VOTE_DROPPED = 'サーバーの再起動のため、保留中の投票を取り消しました'
const EXPEL_DROPPED = 'サーバーの再起動のため、可決された退場の処理を取り消しました'

const count = (text, needle) => text.split(needle).length - 1
const bodyText = page => page.locator('body').innerText()

async function proposeAndDeliberate(host, type, fill) {
  await host.getByRole('button', { name: '🗳 投票' }).click()
  await host.waitForTimeout(400)
  await host.locator('select.session-select').first().selectOption(type)
  await host.waitForTimeout(200)
  await fill()
  await host.getByRole('button', { name: /投票前ラウンド開始/ }).click()
  await waitUntil(async () => (await bodyText(host)).includes(CAST_KEEPER_TEXT),
    { timeout: 30000, message: 'deliberation finished' })
}

// 自動進行オフのまま、ホストの「次の発言」でAIの手番を進め、プレイヤーの手番にする
async function advanceToGuestTurn(host, guest) {
  const guestInput = guest.locator('input.keeper-input')
  const nextBtn = host.getByRole('button', { name: /次の発言/ })
  await waitUntil(async () => {
    if (await guestInput.isEnabled().catch(() => false)) return true
    if (await nextBtn.isEnabled().catch(() => false)) {
      await nextBtn.click()
      await host.waitForTimeout(1500)
    }
    return false
  }, { timeout: 60000, interval: 500, message: "player's turn" })
}

// 再起動の後、両方のタブを開き直し、プレイヤーが発言できる（＝進められる）ことを確かめる
async function reopenAndSpeak(host, guest, line) {
  await host.reload()
  await guest.reload()
  await host.waitForTimeout(3000)
  const guestInput = guest.locator('input.keeper-input')
  await waitUntil(() => guestInput.isEnabled(), { timeout: 30000, message: 'player can speak after restart' })
  await guestInput.fill(line)
  await guest.getByRole('button', { name: /発言完/ }).click()
  await waitUntil(async () => (await bodyText(host)).includes(line), { timeout: 15000, message: 'line reaches host after restart' })
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
    await startSession(host)

    // プレイヤーの手番で自動進行を止める（キーパーの投票ボタンは自動進行中は押せない。
    // 再起動の後も、プレイヤーの手番のまま止まっているので「進められる」を発言で確かめられる）
    const guestInput = guest.locator('input.keeper-input')
    await waitUntil(() => guestInput.isEnabled(), { timeout: 60000, message: "player's turn" })
    await host.locator('button.auto-advance-btn').first().click()
    await host.waitForTimeout(500)

    // ── D-2 ──
    await proposeAndDeliberate(host, 'topic_change', () => host.getByPlaceholder('新しいお題を入力...').fill('再起動で消えるお題'))
    await restartBackend()
    await reopenAndSpeak(host, guest, 'E2E: 再起動の後の発言1')
    assert(count(await bodyText(host), VOTE_DROPPED) === 1, 'D-2: the "vote dropped by restart" notice appears exactly once')
    assert(await host.getByRole('button', { name: '✅ 賛成' }).count() === 0, 'D-2: no vote buttons remain after restart')
    assert(true, 'D-2: the session can be continued after restart')

    // ── D-3: 何もせずに、もう1回再起動 ──
    await restartBackend()
    await host.reload()
    // 履歴が読み込まれる（通知が1つ見える）のを待ってから、少し置いて数える
    await waitUntil(async () => count(await bodyText(host), VOTE_DROPPED) >= 1, { timeout: 20000, message: 'history after the second restart' })
    await host.waitForTimeout(1500)
    assert(count(await bodyText(host), VOTE_DROPPED) === 1, 'D-3: a second restart does not add another notice')

    // ── D-4: 追放の可決の後、続行方法を選ばずに再起動 ──
    await guest.reload()
    await host.waitForTimeout(2000)
    await advanceToGuestTurn(host, guest)
    await proposeAndDeliberate(host, 'expel', () => host.locator('select.session-select').nth(1).selectOption({ label: GUEST_NAME }))
    await host.getByRole('button', { name: '✅ 賛成' }).click()
    await host.getByRole('button', { name: 'このまま人数減で続行' }).waitFor({ state: 'visible', timeout: 15000 })
    await restartBackend()
    await reopenAndSpeak(host, guest, 'E2E: 再起動の後の発言2')
    const t = await bodyText(host)
    assert(count(t, EXPEL_DROPPED) === 1, 'D-4: the "expel dropped by restart" notice appears once')
    // 「対象が残っているか」はサーバーの状態で確かめる。画面の手番の順の表示は、再読み込みの
    // 直後はまだ整っていないことがあり、すぐ読むと落ちる（2026-11-09、CI で一度だけ発生）。
    const { charId: guestCharId } = await getSessionAuth(guest)
    const { body } = await sessionApi(host, '', { method: 'GET' })
    assert(body.session.initiative.includes(guestCharId), 'D-4: the target stays in the initiative (server state)')
    await waitUntil(async () => (await bodyText(host)).includes(`🎭${GUEST_NAME}[`),
      { timeout: 15000, message: 'target shown in the initiative on the host tab' })
    assert(true, 'D-4: the target is shown in the initiative on the host tab')

    console.log('restart_recovery.js: all assertions passed')
  } finally {
    await browser.close()
    await mockReset().catch(() => {})
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
