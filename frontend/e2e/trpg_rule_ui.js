// 【v5.0 差し込み口 11】ルールシステムの画面部品（RuleUiPanel）が描かれ、操作がプラグインに届く。
//
// 構成: 架空のルールシステムのプラグイン ui_grid（tests/fixtures/plugins/ui_grid）の、TRPGのオンラインセッション。
// ホスト（キーパー）とプレイヤー1人。AI は入れない（手番は進めない）。
//
// - 相手ごとに違うもの: ホストには承認と「表示していない」知らせ、プレイヤーには質問（口が決める）
// - 盤面（SVG）・凡例・状態の欄・判定のログが描かれる。ログの文字は文字のまま（HTML として扱わない）
// - ホストがマスを選ぶ → コマが動き、ログに残る。プレイヤーのタブも WS のイベントで描き直す
// - ホストの承認（入力つき）、プレイヤーの自由記述の答えが、プラグインに届く
// - 画面部品の口の無い卓（def_original）では、パネルを出さない
//
// 実行: venv/Scripts/python scripts/e2e_local.py --with-test-plugin trpg_rule_ui
import { chromium } from 'playwright'
import { assert, createOnlineTrpgSession, joinAsPlayer, openSessionTab, sessionApi, waitUntil } from './helpers.js'

const panel = page => page.locator('section.rule-ui-panel')
const panelText = async page => (await panel(page).count()) ? panel(page).innerText() : ''

;(async () => {
  const browser = await chromium.launch()
  try {
    const { page: host, inviteCode } = await createOnlineTrpgSession(browser, { rulebook: 'ui_grid' })
    const { page: guest } = await joinAsPlayer(browser, inviteCode)
    await openSessionTab(guest)
    const errors = []
    for (const [label, p] of [['host', host], ['guest', guest]]) {
      p.on('pageerror', e => { errors.push(`${label}: ${e.message}`); console.log(`[${label} pageerror] ${e.message}`) })
    }
    await host.getByRole('button', { name: 'セッション開始' }).click()

    // ── 相手ごとの画面 ──
    await waitUntil(async () => (await panelText(host)).includes('seen by host'), { message: 'host panel' })
    await waitUntil(async () => (await panelText(guest)).includes('seen by player'), { message: 'guest panel' })
    const hostText = await panelText(host)
    const guestText = await panelText(guest)
    assert(hostText.includes('Approve the move?') && hostText.includes('Approve'), 'host sees the approval')
    assert(!guestText.includes('Approve the move?'), 'player does not see the approval')
    assert(guestText.includes('Where should we go?'), 'player sees the question')
    assert(!hostText.includes('Where should we go?'), 'host does not see the question')
    assert(hostText.includes('1件を表示していません'), 'host is told about the broken component')
    assert(!guestText.includes('表示していません'), 'player is not told about it')

    // ── 部品が描かれる ──
    assert(await panel(host).locator('svg').count() === 1, 'board is drawn as SVG')
    assert(hostText.includes('Unit One: A1'), `legend shows the token position (got: ${hostText.slice(0, 200)})`)
    assert(hostText.includes('Hill') && hostText.includes('Move') && hostText.includes('Sight'), 'legend shows terrain, overlay, line')
    assert(hostText.includes('HP 10/12'), 'status panel is drawn')
    assert(hostText.includes('start <b>bold</b>'), 'log text is drawn as text, not HTML')
    assert(await panel(host).locator('.rule-ui-log b').count() === 0, 'no HTML element was made from the log text')

    // ── ホストがマスを選ぶ（選べるマスは点線。プレイヤーには選べるマスが無い） ──
    const selectable = panel(host).locator('svg rect[style*="pointer"]')
    assert(await selectable.count() === 2, `host has 2 selectable cells next to A1 (got ${await selectable.count()})`)
    assert(await panel(guest).locator('svg rect[style*="pointer"]').count() === 0, 'player has no selectable cells')
    await selectable.first().click()
    await waitUntil(async () => /moved to (B1|A2)/.test(await panelText(host)), { message: 'host log shows the move' })
    await waitUntil(async () => /moved to (B1|A2)/.test(await panelText(guest)), { message: 'guest redraws after the WS event' })
    assert(!(await panelText(host)).includes('Unit One: A1'), 'token moved on the board')

    // 見た目の確かめ用（E2E_SCREENSHOT_DIR を設定したときだけ）
    if (process.env.E2E_SCREENSHOT_DIR) {
      await panel(host).screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/rule_ui_host.png` })
      await panel(guest).screenshot({ path: `${process.env.E2E_SCREENSHOT_DIR}/rule_ui_guest.png` })
    }

    // ── 承認（入力つき）と、プレイヤーの答え ──
    await panel(host).locator('.rule-ui-approval input').fill('looks good')
    await panel(host).getByRole('button', { name: 'Approve' }).click()
    await waitUntil(async () => (await panelText(host)).includes('approval: ok (looks good)'), { message: 'approval reached the plugin' })
    await panel(guest).locator('.rule-ui-question input').fill('to the hill')
    await panel(guest).getByRole('button', { name: '送る' }).click()
    await waitUntil(async () => (await panelText(guest)).includes('answer from player: to the hill'), { message: 'answer reached the plugin' })
    await waitUntil(async () => (await panelText(host)).includes('answer from player: to the hill'), { message: 'host sees the answer' })

    // ── プレイヤーはマスを選べない（口が断る。API を直に呼んでも） ──
    const r = await sessionApi(guest, '/rule_ui/action', { body: { component: 'map', action: 'select_cell', data: { pos: [0, 0] } } })
    assert(r.status === 409, `player's move is refused (got ${r.status})`)

    // ── 画面部品の口の無い卓では出さない ──
    const { page: plain } = await createOnlineTrpgSession(browser, { rulebook: 'def_original' })
    await plain.waitForTimeout(1500)
    assert(await panel(plain).count() === 0, 'no rule ui panel on a def_original table')

    assert(errors.length === 0, `no page errors (got: ${errors.join(' | ')})`)
    console.log('trpg_rule_ui.js: all assertions passed')
  } catch (e) {
    console.error(e)
    process.exitCode = 1
  } finally {
    await browser.close()
  }
})()
