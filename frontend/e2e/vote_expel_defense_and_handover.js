// 【回帰防止テスト】投票expelの弁明ラウンド・個別投票権・AI引き継ぎ確認ダイアログを
// 一気通貫で検証する。
//
// 2026-08-22、実機でexpel投票を試したところ3つの問題が見つかった:
// (1) 弁明ラウンドの内容(AI意見・発議者発言)がHTTPレスポンスのみで他タブへブロード
//     キャストされておらず、対象者(別タブの人間)には投票が起きていること自体が
//     見えなかった。(2) 対象者を含む人間キャラの票は全員一律キーパーのクリック値の
//     コピーになっており、対象者本人の意思表示手段が存在しなかった(スクショの
//     「賛成4/反対0」はAI2票＋キーパー1票＋対象者=キーパー票のコピー1票で説明が
//     つき、対象者の実際の意思は一切反映されていなかった)。(3) expel可決時、自治規約が
//     謳う「続行/AI引き継ぎ」の選択がキーパーに提示されないまま無条件でinitiativeから
//     即削除されていた。
//
// このテストは、ゲスト自身のタブに弁明ラウンドがリアルタイムで届くこと・ゲストが
// 自分の意見と反対票を投じるとそれが「キーパー票のコピー」ではなく本人の実際の意思
// として集計に反映されること(単独キーパー票との1-1で否決になることで証明)・
// ゲストが賛成すれば可決しキーパーが「AIに引き継ぐ」を選ぶとキャラがinitiativeに
// 残り続けること・それでも人間プレイヤー自身の接続は切断される(ws.onclose修正で
// 本人に通知される)こと・AI引き継ぎ後に実際にAIがそのキャラのターンを生成して
// セッションが進行すること(human_char_idsから外すだけでは誰も_run_ai_turnsを
// 再起動せずセッションが止まったままになる不具合と、guest_chars所属を無条件に
// 人間扱いしていたため引き継ぎ後もAI判定されなかった不具合の、2つの回帰防止)を
// 一気通貫で確認する。
//
// 実行: node frontend/e2e/vote_expel_defense_and_handover.js
import { chromium } from 'playwright'
import { assert, createOnlineSession, joinAsPlayer, startSession } from './helpers.js'

;(async () => {
  const browser = await chromium.launch()
  try {
    // selectMockBackend: AI引き継ぎ後、実際にAIターンが生成されて進行することまで
    // 検証するため(2026-08-22、AI引き継ぎ後もセッションが進まなくなる不具合を
    // 実機で発見・修正した回帰防止)。
    const { page: host, inviteCode } = await createOnlineSession(browser, { selectMockBackend: true })
    const { page: guest } = await joinAsPlayer(browser, inviteCode)
    await startSession(host)

    // 投票発議ボタンはdisabled={autoAdvance}のため、startSession()が有効化した「自動」を
    // 一旦オフに戻してから発議する（vote_expel.jsと同じ理由）。
    await host.waitForTimeout(3000)
    await host.locator('button.auto-advance-btn').first().click()
    await host.waitForTimeout(300)

    // ── Phase A: 対象者(ゲスト)が反対票を投じると、本人の意思として集計に反映され
    //    否決になることを確認する(以前は対象者の票がキーパー票のコピーになっており、
    //    キーパーが賛成した時点で対象者の実際の意思に関わらず可決していた) ──
    await host.getByRole('button', { name: '🗳 投票' }).click()
    await host.waitForTimeout(400)
    await host.locator('select.session-select').first().selectOption('expel')
    await host.waitForTimeout(200)
    await host.locator('select.session-select').nth(1).selectOption({ label: 'テストゲスト' })
    await host.waitForTimeout(200)
    await host.getByRole('button', { name: /投票前ラウンド開始/ }).click()
    await host.waitForTimeout(2000)

    // ゲスト自身のタブにも投票提案がリアルタイムで届くこと(修正前はvote_deliberateの
    // HTTPレスポンスのみで、発議した本人のタブにしか見えていなかった)
    const guestText1 = await guest.locator('body').innerText()
    assert(guestText1.includes('投票提案'), 'guest tab receives the live vote proposal broadcast (previously invisible to non-proposer tabs)')

    // ゲストが自分の意見＋反対票を投じる
    await guest.locator('input.plot-dialog-textarea').fill('私は無実です')
    await guest.getByRole('button', { name: /反対/ }).click()
    await guest.waitForTimeout(1000)

    // ゲスト自身のタブに自分の投票が反映される
    const guestText2 = await guest.locator('body').innerText()
    assert(guestText2.includes('私は無実です'), "guest's own tab shows their cast vote text")

    // ホスト側タブにもゲストの意見がブロードキャスト経由で反映される
    const hostTextAfterCast = await host.locator('body').innerText()
    assert(hostTextAfterCast.includes('私は無実です'), "guest's own cast vote+opinion appears on the host's tab too (broadcast working)")

    // ホストがキーパー票（賛成）を投じる。このセッションにはホスト自身のキャラは
    // initiativeにいない(createOnlineSessionのキャラ選択はオンライン作成では効かない)
    // ため、投票者は「キーパー票」「対象者(ゲスト)本人の票」の2者のみ。対象者の票が
    // 本人の意思(反対)として正しく数えられていれば1-1で否決になるはず——もし
    // 対象者の票がキーパー票のコピーのままなら2-0で可決してしまう(=旧バグの再現条件)。
    await host.getByRole('button', { name: /賛成/ }).click()
    await host.waitForTimeout(1500)

    const hostTextRejected = await host.locator('body').innerText()
    assert(hostTextRejected.includes('賛成1/反対1'), "target's explicit dissenting vote is tallied as their own (1 vs 1), not silently copied from the keeper's click")
    assert(hostTextRejected.includes('否決'), 'vote is rejected on a 1-1 tie, proving the target had genuine voting power')

    // ── Phase B: 今度はゲストが賛成すれば可決し、キーパーの「AIに引き継ぐ」選択で
    //    キャラがinitiativeに残り続けることを確認する ──
    await host.getByRole('button', { name: '🗳 投票' }).click()
    await host.waitForTimeout(400)
    await host.locator('select.session-select').first().selectOption('expel')
    await host.waitForTimeout(200)
    await host.locator('select.session-select').nth(1).selectOption({ label: 'テストゲスト' })
    await host.waitForTimeout(200)
    await host.getByRole('button', { name: /投票前ラウンド開始/ }).click()
    await host.waitForTimeout(2000)

    await guest.getByRole('button', { name: /賛成/ }).click()
    await guest.waitForTimeout(1000)

    await host.getByRole('button', { name: /賛成/ }).click()
    await host.waitForTimeout(1500)

    const hostTextAfterCommit = await host.locator('body').innerText()
    assert(hostTextAfterCommit.includes('可決'), 'expel vote passes when the target also votes in favor (2-0)')
    assert(hostTextAfterCommit.includes('🎭テストゲスト['), 'guest still present in initiative right after vote passes (removal is deferred to the follow-up choice)')

    // キーパーの追加選択: 「AIに引き継ぐ」を選ぶ
    await host.getByRole('button', { name: /AIに引き継ぐ/ }).click()
    await host.waitForTimeout(600)

    // 引き継ぎ後はhuman_char_idsから外れ、参加者パネル上もPLAYER_LEFTでhumanP判定が
    // 外れるため🎭マーカーは消える(=もう人間操作ではないので正しい)が、キャラ名自体は
    // initiativeに残り続けるはず(「続行」を選んだ場合は名前ごと消える)。
    const messageCountBeforeResume = await host.locator('.session-msg').count()
    const hostTextAfterHandover = await host.locator('body').innerText()
    assert(hostTextAfterHandover.includes('テストゲスト['), 'handed-over character stays in the host initiative display by name (unlike the "continue" choice, which removes it entirely)')

    // AI引き継ぎ対象がちょうど現在のターン担当キャラ(WAITING_FOR_HUMAN中)だった場合、
    // human_char_idsから外すだけではAIターン処理が誰にも再起動されず、セッションが
    // 止まったまま進まなくなる不具合があった(2026-08-22、実機のexpelでAI引き継ぎ
    // 直後にセッションが停止する現象として発見・修正)。新しいメッセージ(=AIが
    // 実際にこのキャラのターンを生成した証拠)が届くことを確認する。
    // CIランナーはこの時点までに複数回の弁明ラウンド・投票サイクルを経ており負荷が
    // 蓄積しているため、ローカルでは余裕だった15秒がCIでは不足しタイムアウトする
    // ことを実CIで確認（2026-08-23）。LLM呼び出しを含む他のシナリオの待ち時間に
    // 合わせ30秒に拡張。
    await host.waitForFunction(
      (before) => document.querySelectorAll('.session-msg').length > before,
      messageCountBeforeResume,
      { timeout: 30000 },
    )
    const hostTextAfterResume = await host.locator('body').innerText()
    assert(hostTextAfterResume.includes('テストゲスト'), 'a new AI-generated turn for the handed-over character actually appears (session did not get stuck)')

    // 人間プレイヤー自身の接続はAI引き継ぎでも切断される。ws.oncloseの修正
    // (2026-08-22)により、本人のタブは切断通知を表示してスタート画面へ戻るはず。
    await guest.waitForTimeout(2500)
    const guestTextAfterReset = await guest.locator('body').innerText()
    assert(guestTextAfterReset.includes('切断されました'), 'the expelled human is still disconnected from their own session even when their character is handed to AI (ws.onclose fix)')

    console.log('vote_expel_defense_and_handover.js: all assertions passed')
  } finally {
    await browser.close()
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
