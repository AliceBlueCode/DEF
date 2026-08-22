// 【回帰防止テスト】オンラインTRPGセッションで参加者が切断した際、ホストの
// イニシアチブ表示に「AIに引き継ぐ」🤖ボタンが現れ、クリックすると
// POST /{session_id}/ai_takeoverが呼ばれてキャラがAI引き継ぎ済み表示に
// 切り替わることを確認する。
//
// aiTakeover関数自体はバックエンド実装済み(session.py:ai_takeover)のまま
// フロント側のUIトリガーが長期間コメントアウトされて未接続だった
// (TODO.md「aiTakeover/rollPendingJudgmentの機能完成」、2026-08-10発覚・
// 2026-08-22 UI実装)。ボタンの出現条件(isKeeperUi && disconnected &&
// !aiTakenOverChars.has(id))と、クリック後にaiTakenOverCharsへ反映されて
// ボタンが消え🤖表示に切り替わることの両方を検証する。
//
// 実行: node frontend/e2e/ai_takeover.js
import { chromium } from 'playwright'
import { assert, createOnlineTrpgSession, joinAsPlayer, startSession } from './helpers.js'

;(async () => {
  const browser = await chromium.launch()
  try {
    const { page: host, inviteCode } = await createOnlineTrpgSession(browser)
    const { ctx: guestCtx } = await joinAsPlayer(browser, inviteCode)

    await startSession(host)

    await guestCtx.close() // ゲストのブラウザごと落として切断をシミュレート(disconnect_timeout.jsと同じ手法)

    const takeoverBtn = host.locator('button[title="AIに引き継ぐ"]')
    await takeoverBtn.waitFor({ state: 'visible', timeout: 20000 })
    assert(true, 'AI takeover button appears for disconnected participant character')

    await takeoverBtn.click()
    await host.waitForTimeout(1500)

    await takeoverBtn.waitFor({ state: 'detached', timeout: 10000 }).catch(async () => {
      assert(await takeoverBtn.count() === 0, 'AI takeover button disappears after takeover')
    })
    assert(true, 'AI takeover button no longer present after takeover')

    const doneMarker = host.locator('span[title="AIに引き継ぎ済み"]')
    await doneMarker.waitFor({ state: 'visible', timeout: 5000 })
    assert(true, 'character shows AI-taken-over indicator after takeover')

    console.log('ai_takeover.js: all assertions passed')
  } finally {
    await browser.close()
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
