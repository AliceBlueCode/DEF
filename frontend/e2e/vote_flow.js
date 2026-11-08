// 【v4.2.1 実機確認手順 C-1 / C-2 / C-4 / C-5 / C-16】投票中のターン停止と、確定・取り消しの後の進行。
//
// 構成: オンラインセッション（チャット型）、AI 2人（ChatGPT・Claude）、プレイヤー 1人、ホスト＝キーパー。
// 弁明はモックLLMの台本で返し、遅らせて「弁明の途中」を作る。
//
// 前半（確定）:
// - C-1  投票中にプレイヤーが発言すると「投票中は…」が1回だけ出て、入力した文章は消えない
// - C-16 弁明は各AIにつき1回だけ生成される
// - C-3  （キーパーは自動進行中は発議できないので）自動進行をオフにして発議し、投票中にオンへ戻す
// - C-2  確定の後、プレイヤーが送り直せて、その後のAIの手番は自動進行で進む
// 後半（取り消し）:
// - C-4  弁明の途中でホストのタブを再読み込みし、「次の発言」を押すと、理由と取り消しボタンが出る
// - C-5  取り消すと全タブに「保留中の投票を取り消しました」が出て、残りの弁明は流れず、
//        投票のボタンも残らず、そのまま進められる
//
// 実行: venv/Scripts/python scripts/e2e_local.py vote_flow
import { chromium } from 'playwright'
import {
  assert, createOnlineSession, joinAsPlayer, lobbyAddAi, mockCalls, mockReset, mockRules, mockScript,
  startSession, waitUntil,
} from './helpers.js'

const AIS = [
  { id: 'character_chatgpt_001', name: 'ChatGPT' },
  { id: 'character_claude_001', name: 'Claude' },
]
const BLOCKED_TEXT = '投票中は発言やスキップができません'
const CANCELLED_TEXT = '保留中の投票を取り消しました'
const CAST_KEEPER_TEXT = 'キーパーの一票を投じてください。'

const count = (text, needle) => text.split(needle).length - 1
const bodyText = page => page.locator('body').innerText()
// モックの既定の返事「モック応答その{n}です」の n の最大値。画面は直近の発言しか出さないので、
// 件数ではなく番号が増えたかで「新しくAIが発言した」を判定する。
const lastMockNo = text => Math.max(0, ...[...text.matchAll(/モック応答その(\d+)/g)].map(m => Number(m[1])))

async function proposeTopicChange(host, topic) {
  await host.getByRole('button', { name: '🗳 投票' }).click()
  await host.waitForTimeout(400)
  await host.locator('select.session-select').first().selectOption('topic_change')
  await host.getByPlaceholder('新しいお題を入力...').fill(topic)
  await host.getByRole('button', { name: /投票前ラウンド開始/ }).click()
}

;(async () => {
  await mockReset()
  // 前半の弁明（各AI 1回だけ、少し遅らせる）。後半の弁明（長く遅らせる）は後で足す。
  await mockScript(AIS.map(a => mockRules.deliberation(a.name,
    { json: { dialogue: `弁明1: ${a.name}は賛成です`, emotion: 'neutral', tags: [] } },
    { name: `deliberation1:${a.name}`, times: 1, delay_ms: 1500 })))

  const browser = await chromium.launch()
  try {
    const { page: host, inviteCode } = await createOnlineSession(browser, { selectMockBackend: true })
    const { page: guest } = await joinAsPlayer(browser, inviteCode)
    for (const [label, p] of [['host', host], ['guest', guest]]) {
      p.on('pageerror', e => console.log(`[${label} pageerror] ${e.message}`))
    }
    for (const a of AIS) await lobbyAddAi(host, a.id)
    await startSession(host) // 自動進行オン

    const guestInput = guest.locator('input.keeper-input')
    const guestSend = guest.getByRole('button', { name: /発言完/ })

    // ── 前半: プレイヤーの手番まで進めて、投票を発議する ──
    const autoBtn = host.locator('button.auto-advance-btn').first()
    await waitUntil(() => guestInput.isEnabled(), { timeout: 60000, message: "player's turn" })
    await autoBtn.click() // 自動進行オフ（キーパーの投票ボタンは自動進行中は押せない）
    await host.waitForTimeout(300)
    await proposeTopicChange(host, 'E2Eの新しいお題')
    await host.waitForTimeout(500)
    await autoBtn.click() // C-3: 投票中に自動進行をオンへ戻す
    await waitUntil(async () => {
      const t = await bodyText(host)
      return AIS.every(a => t.includes(`弁明1: ${a.name}は賛成です`)) && t.includes(CAST_KEEPER_TEXT)
    }, { timeout: 30000, message: 'deliberation finished on host tab' })
    assert(true, 'deliberation of both AIs arrives on the host tab')

    // C-1: 投票中にプレイヤーが発言する
    const draft = 'E2E: 投票中に送ろうとした発言'
    await guestInput.fill(draft)
    await guestSend.click()
    // 通知が出るのを待ってから、少し置いて「1回だけ」を見る（固定の待ちだけだと、遅い環境で出る前に見てしまう）
    await waitUntil(async () => count(await bodyText(guest), BLOCKED_TEXT) >= 1, { timeout: 15000, message: 'blocked notice' })
    await guest.waitForTimeout(1500)
    assert(count(await bodyText(guest), BLOCKED_TEXT) === 1, 'C-1: the "vote in progress" notice appears exactly once')
    assert((await guestInput.inputValue()) === draft, 'C-1: the typed text is kept in the input')
    assert(!(await bodyText(host)).includes(draft), 'C-1: the blocked text was not posted')

    // C-16: 弁明は各AIにつき1回だけ生成された
    const calls = await mockCalls()
    for (const a of AIS) {
      const n = calls.filter(c => c.matched === `deliberation1:${a.name}`).length
      assert(n === 1, `C-16: deliberation for ${a.name} generated once (got ${n})`)
    }
    assert(calls.filter(c => c.last_user.includes('今、投票が提案されています:')).length === AIS.length,
      'C-16: no extra deliberation calls')

    // C-2: 確定する → プレイヤーが送り直せる → その後のAIの手番は自動で進む
    await host.getByRole('button', { name: '✅ 賛成' }).click()
    await waitUntil(async () => /可決|否決/.test(await bodyText(host)), { timeout: 30000, message: 'vote result' })
    assert(true, 'vote result is shown after commit')

    await waitUntil(() => guestInput.isEnabled(), { timeout: 15000, message: 'player can speak again after commit' })
    // モックは速いので、送り直した直後にAIの手番が終わる。番号は送る前に記録しておく
    const aiRepliesBefore = lastMockNo(await bodyText(host))
    await guestSend.click()
    await waitUntil(async () => (await bodyText(host)).includes(draft), { timeout: 15000, message: 'resent text on host tab' })
    assert(true, 'C-1: the kept text can be sent after the vote is decided')

    await waitUntil(async () => lastMockNo(await bodyText(host)) > aiRepliesBefore,
      { timeout: 30000, message: 'AI turn advances automatically after the vote' })
    assert(true, 'C-2/C-3: auto-advance (turned on during the vote) continues to the next AI turn after the vote')

    // ── 後半: 弁明の途中で再読み込みし、取り消す ──
    // 自動進行を止め、AIの手番（ホストが「次の発言」を押せる状態）にする
    await autoBtn.click()
    const nextBtn = host.getByRole('button', { name: /次の発言/ })
    await waitUntil(async () => {
      if (await guestInput.isEnabled()) {
        await guestInput.fill('E2E: 後半の前の発言')
        await guestSend.click()
        await guest.waitForTimeout(1500)
        return false
      }
      return nextBtn.isEnabled()
    }, { timeout: 60000, interval: 500, message: "an AI's turn with the next button enabled" })

    await mockScript(AIS.map(a => mockRules.deliberation(a.name,
      { json: { dialogue: `弁明2: ${a.name}の遅い弁明`, emotion: 'neutral', tags: [] } },
      { name: `deliberation2:${a.name}`, delay_ms: 5000 })))
    await proposeTopicChange(host, 'E2Eの取り消すお題')
    await host.waitForTimeout(800)

    // C-4: 再読み込みして「次の発言」→ 理由と取り消しボタン
    await host.reload()
    await host.waitForTimeout(2500)
    await nextBtn.waitFor({ state: 'visible', timeout: 15000 })
    await nextBtn.click()
    const cancelBtn = host.getByRole('button', { name: '保留中の投票を取り消す' })
    await cancelBtn.waitFor({ state: 'visible', timeout: 10000 })
    assert((await bodyText(host)).includes(BLOCKED_TEXT), 'C-4: the reason and the cancel button appear after reload')

    // C-5: 取り消す
    await cancelBtn.click()
    for (const [label, p] of [['host', host], ['guest', guest]]) {
      await waitUntil(async () => (await bodyText(p)).includes(CANCELLED_TEXT),
        { timeout: 15000, message: `cancel notice on ${label} tab` })
    }
    assert(true, 'C-4: "pending vote cancelled" appears on both tabs')

    // 遅らせた弁明が実際に呼ばれたこと（台本が当たったこと）を確かめ、最後の呼び出しの返事
    // （delay_ms 後）がサーバーに届いて処理されるまで待ってから、「流れ込まない」を見る。
    // 台本が当たっていなければ、そもそも流れ込む余地が無く、確かめたことにならない。
    const delib2 = async () => (await mockCalls()).filter(c => c.matched.startsWith('deliberation2:')).length
    await waitUntil(async () => (await delib2()) >= 1, { timeout: 15000, message: 'delayed deliberation was requested' })
    let seen = await delib2()
    for (let i = 0; ; i++) {
      // 弁明が止まらない不具合なら、CIのタイムアウトではなく、ここで明確に落とす
      if (i >= 5) throw new Error(`C-5: deliberation calls keep coming after cancel (${seen} calls)`)
      await host.waitForTimeout(7000) // delay_ms（5秒）＋処理の余裕
      const now = await delib2()
      if (now === seen) break
      seen = now
    }
    assert(seen >= 1, `C-5: the delayed deliberation was actually generated (${seen} calls)`)
    for (const [label, p] of [['host', host], ['guest', guest]]) {
      const t = await bodyText(p)
      assert(!t.includes('弁明2:'), `C-5: no deliberation flows in after cancel on the ${label} tab`)
      assert(await p.getByRole('button', { name: '✅ 賛成' }).count() === 0, `C-5: no vote buttons remain on the ${label} tab`)
    }

    const beforeNext = lastMockNo(await bodyText(host))
    await nextBtn.click()
    await waitUntil(async () => lastMockNo(await bodyText(host)) > beforeNext,
      { timeout: 30000, message: 'session advances after cancel' })
    assert(true, 'C-4: the session advances with the next button after cancel')

    console.log('vote_flow.js: all assertions passed')
  } finally {
    await browser.close()
    await mockReset().catch(() => {})
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
