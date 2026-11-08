// 【v4.2.1 実機確認手順 B-1 / B-2 / B-3】TRPGモードで、AIの自発スキップ・指名と、ラウンドの終わりのキーパー。
//
// 構成: TRPGのオンラインセッション（ホスト＝キーパー、AIキーパーの語りはモックLLM）、
// AI 3人（ChatGPT・Claude・Gemini）、プレイヤー 1人。自動進行オン。
// AIの行動選択（Round 2以降）に台本で「skip」「designate」を返させる。
//
// - B-1  AIが自分からスキップした後も、自動進行が止まらずに次へ進む
// - B-3  指名されたキャラが次に話し、その後は本来の順番（指名したキャラの直後）に戻る
//        指名には発言力1以上が要るので、指名するキャラには先に1回スキップさせる（+1）。
//        手番の順は開始時にシャッフルされるため、開始後に initiative を読み、指名したキャラの
//        直後ではないキャラを指名させる（直後だと、指名が効いたのか区別できない）。
// - B-2  キーパーの語りは、ラウンドごとに1回（2回続けて語らない）
//
// 判定は画面の表示と、モックの呼び出しの記録（誰の行動選択・発言が、どの順で来たか）で行う。
//
// 実行: venv/Scripts/python scripts/e2e_local.py trpg_skip_designate
import { chromium } from 'playwright'
import {
  assert, createOnlineTrpgSession, joinAsPlayer, lobbyAddAi, mockCalls, mockReset, mockRules, mockScript,
  openSessionTab, selectTextgenWebuiBackend, sessionApi, startSession, waitUntil,
} from './helpers.js'

const AIS = [
  { id: 'character_chatgpt_001', name: 'ChatGPT' },
  { id: 'character_claude_001', name: 'Claude' },
  { id: 'character_gemini_001', name: 'Gemini' },
]
const NARRATION = 'E2Eのキーパーの語りです。'

const bodyText = page => page.locator('body').innerText()

// モックの呼び出し1件が「誰の、何の」呼び出しか
function classify(call) {
  if (call.matched === 'keeper-narration' || call.last_user.includes('キーパーとして、直近の状況を踏まえて')) return { kind: 'narration' }
  if (call.system.includes('判定要否決定システム')) return { kind: 'plan' }
  const act = call.last_user.match(/、(.+?)のターンです/)
  const round = call.last_user.match(/ラウンド(\d+)、/)
  if (call.last_user.includes('[TRPGアクション選択]') && act) return { kind: 'action', who: act[1], round: round ? Number(round[1]) : null }
  if (call.speaker) return { kind: 'dialogue', who: call.speaker }
  return { kind: 'other' }
}

;(async () => {
  await mockReset()
  await mockScript([mockRules.judgmentPlan([]), mockRules.keeperNarration(NARRATION)])

  const browser = await chromium.launch()
  try {
    const { page: host, inviteCode } = await createOnlineTrpgSession(browser)
    const { page: guest } = await joinAsPlayer(browser, inviteCode)
    // キーパーの語りを、どのタブが起こしてもモックに向くように（trpg_keeper_online_join.js 参照）
    await selectTextgenWebuiBackend(guest)
    await openSessionTab(guest)
    for (const [label, p] of [['host', host], ['guest', guest]]) {
      p.on('pageerror', e => console.log(`[${label} pageerror] ${e.message}`))
    }
    for (const a of AIS) await lobbyAddAi(host, a.id)
    await startSession(host) // 自動進行オン

    // 手番の順を読み、役を決める。どのラウンドにもプレイヤーの手番があり、プレイヤーが発言するまで
    // 進まないので、最初の発言の前に台本を足せば Round 2 の行動選択に間に合う。
    const { body } = await sessionApi(host, '', { method: 'GET' })
    const order = body.session.initiative
    const nameOf = id => AIS.find(a => a.id === id)?.name
    const aiOrder = order.filter(id => nameOf(id))
    const DESIGNATOR = nameOf(aiOrder[0])
    const DESIGNATED = nameOf(aiOrder[2])  // 最後のAI: 指名したキャラの直後ではない
    // 指名したキャラと指名されたキャラの間にいるAI。指名されたキャラが話し終えたら、
    // 指名したキャラの次へ戻るので、（間にプレイヤーがいてもLLMは呼ばれないため）
    // 次に行動選択が来るのはこのAI。同じラウンドのうちに来なければならない。
    const SKIPPER = nameOf(aiOrder[1])
    const RETURN_TO = SKIPPER
    console.log(`initiative: ${order.map(id => nameOf(id) || 'player').join(' → ')} / designate ${DESIGNATOR} → ${DESIGNATED}`)
    await mockScript([
      mockRules.actionSelect(SKIPPER, 'skip', {}, { name: `action:${SKIPPER}:skip`, times: 1 }),
      mockRules.actionSelect(DESIGNATOR, 'skip', {}, { name: `action:${DESIGNATOR}:skip-for-counter`, times: 1 }),
      mockRules.actionSelect(DESIGNATOR, 'designate', { target_name: DESIGNATED }, { times: 1 }),
    ])

    const guestInput = guest.locator('input.keeper-input')
    const guestSend = guest.getByRole('button', { name: /発言完/ })
    let guestLines = 0

    // プレイヤーの手番が来たら発言しつつ、スキップと指名が両方起きて、その後も進むまで待つ
    const SKIP_TEXT = `⏭ ${SKIPPER} はスキップ`
    const DESIGNATE_TEXT = `👉 ${DESIGNATOR} が ${DESIGNATED} を指名`
    const designateDone = async () => (await mockCalls()).some(c => c.matched === `action:${DESIGNATOR}:designate`)
    let callsAtSkip = -1
    await waitUntil(async () => {
      if (await guestInput.isEnabled().catch(() => false)) {
        await guestInput.fill(`E2E: プレイヤーの発言${++guestLines}`)
        await guestSend.click()
      }
      const t = await bodyText(host)
      const calls = await mockCalls()
      if (callsAtSkip < 0 && t.includes(SKIP_TEXT)) callsAtSkip = calls.length
      // スキップの後に、AIの発言の呼び出しが2回以上あれば「止まらずに進んだ」
      const progressedAfterSkip = callsAtSkip >= 0 &&
        calls.slice(callsAtSkip).filter(c => classify(c).kind === 'dialogue').length >= 2
      // 指名の後、指名されたキャラの発言と、その次の手番まで進んだら判定する
      if (!(progressedAfterSkip && t.includes(DESIGNATE_TEXT) && await designateDone())) return false
      // 指名されたキャラが話し終えた後、別のキャラの行動選択が来るまで待つ
      const cs = calls.map(classify)
      const iD = calls.findIndex(c => c.matched === `action:${DESIGNATOR}:designate`)
      const after = cs.slice(iD + 1)
      const iSpoke = after.findIndex(c => c.kind === 'dialogue' && c.who === DESIGNATED)
      return iSpoke >= 0 && after.slice(iSpoke + 1).some(c => c.kind === 'action' && c.who !== DESIGNATED)
    }, { timeout: 120000, interval: 700, message: 'skip and designate happened and the session kept going' }).catch(async e => {
      // 調査用: 誰の行動選択・発言・語りが、どの順で来たか
      const seq = (await mockCalls()).map(c => { const k = classify(c); return `${k.kind}${k.who ? ':' + k.who : ''}${c.matched ? ' [' + c.matched + ']' : ''} | ${c.last_user.slice(0, 60).replace(/\n/g, ' ')}` })
      console.log(`call sequence:\n  ${seq.join('\n  ')}`)
      console.log(`host tail:\n${(await bodyText(host)).slice(-1500)}`)
      throw e
    })
    assert(true, 'B-1: after an AI skips voluntarily, auto-advance keeps going')

    const rawCalls = await mockCalls()
    const calls = rawCalls.map(c => ({ ...classify(c), matched: c.matched }))
    if (process.env.E2E_DEBUG) {
      console.log('call sequence:')
      for (const c of rawCalls) {
        const k = classify(c)
        console.log(`  ${k.kind}${k.who ? ':' + k.who : ''}${c.matched ? ' [' + c.matched + ']' : ''} | ${c.last_user.slice(0, 50).replace(/\n/g, ' ')}`)
      }
    }

    // B-3: 指名の後、次に話すのは指名されたキャラ
    const iDesignate = calls.findIndex(c => c.matched === `action:${DESIGNATOR}:designate`)
    assert(iDesignate >= 0, 'B-3: the designate action was used')
    const afterDesignate = calls.slice(iDesignate + 1).filter(c => c.kind === 'action' || c.kind === 'dialogue')
    const nextOther = afterDesignate.find(c => c.who !== DESIGNATOR)
    assert(nextOther?.who === DESIGNATED, `B-3: the designated character speaks next (got ${nextOther?.who})`)
    const iDesignatedDone = afterDesignate.findIndex(c => c.kind === 'dialogue' && c.who === DESIGNATED)
    const back = afterDesignate.slice(iDesignatedDone + 1).find(c => c.kind === 'action' && c.who !== DESIGNATED)
    assert(back?.who === RETURN_TO,
      `B-3: after the designated speaker, the turn returns to ${RETURN_TO} (got ${back?.who})`)
    const designateRound = calls[iDesignate].round
    assert(back?.round === designateRound,
      `B-3: the return happens in the same round as the designation (round ${designateRound}, got ${back?.round})`)

    // B-2: キーパーの語りが2回続かない（語りと語りの間に、必ず誰かの発言がある）
    let lastWasNarration = false
    let doubled = false
    for (const c of calls) {
      if (c.kind === 'narration') {
        if (lastWasNarration) doubled = true
        lastWasNarration = true
      } else if (c.kind === 'dialogue') {
        lastWasNarration = false
      }
    }
    const narrations = calls.filter(c => c.kind === 'narration').length
    assert(narrations >= 1, `B-2: the keeper narrated at the end of a round (${narrations} times)`)
    assert(!doubled, 'B-2: the keeper never narrates twice in a row')
    assert((await bodyText(host)).includes(NARRATION), 'B-2: the keeper narration is shown on the host tab')
    console.log('trpg_skip_designate.js: all assertions passed')
  } finally {
    await browser.close()
    await mockReset().catch(() => {})
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
