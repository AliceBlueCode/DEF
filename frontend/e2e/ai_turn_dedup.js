// 【回帰防止テスト】/human_turn (action=send) の多重送信ガード。
//
// 当初は「並列連打してもAIターンが二重起動しない」(session.py の ai_task.done()
// ガード) ことの確認を意図していたが、実際に8並列で叩いたところ、そのガードが
// 防いでいる範囲より手前で問題が起きることが判明した(2026-08-08)。
//
// 最初は「turnの読み取り〜書き戻しの間に割り込まれるTOCTOU」と診断したが、これは
// 誤りだった。human_turn_action は async def だが本体に await が一切無いため、
// asyncioの協調スケジューリング上この関数は呼ばれたら他コルーチンに横入りされず
// 単一イベントループ上でアトミックに完走する(＝真の並行処理レースは起きない)。
//
// 実体は2つの認可・防御の欠落だった:
//   1. current_char_idが呼び出しトークンの本人かを検証していなかった(オーナー
//      シップ漏れ) → 修正済み(human_char_idsチェック＋player role時のchar_id一致)。
//   2. initiativeに人間が1人しかいない(AI不在の)ソロセッションでは、_run_ai_turns
//      側の巻き戻り(turn>=len(initiative)時にround+1・turn=0)がLLM呼び出し無しで
//      同一イベントループtick内に即完了し、次の巻き戻り後もcurrent_char_idは同じ
//      本人のキャラのままなのでオーナーシップチェックだけでは何度でも一致して
//      しまう → 修正済み(WAITING_FOR_HUMANで配布したroundをクライアントが
//      expected_roundとして送り返し、サーバーの現在roundと不一致なら拒否)。
//
// このテストはガードが効いていること(8並列送信のうち1件だけが処理される)を
// 確認する回帰防止テスト。
//
// 実行: node frontend/e2e/ai_turn_dedup.js
import { chromium } from 'playwright'
import { assert, createOnlineSession, joinAsPlayer, startSession } from './helpers.js'

const MARKER_TEXT = `dedup-check-${Date.now()}`
const N_PARALLEL = 8

// JWTペイロード(署名検証なし、session_id claim読み取り専用)をブラウザ側でdecodeする。
async function decodeJwtSessionId(page, token) {
  return page.evaluate(t => {
    const payload = t.split('.')[1]
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(json).session_id
  }, token)
}

;(async () => {
  const browser = await chromium.launch()
  try {
  const { page: host, inviteCode } = await createOnlineSession(browser)
  const { page: guest, playerToken: guestToken } = await joinAsPlayer(browser, inviteCode)
  assert(!!guestToken, 'player_token captured from join response')
  guest.on('pageerror', e => console.log(`[guest pageerror] ${e.message}`))
  guest.on('console', msg => { if (msg.type() === 'error') console.log(`[guest console.error] ${msg.text()}`) })

  await startSession(host)

  const sendBtn = guest.getByRole('button', { name: /発言完/ })
  await sendBtn.waitFor({ state: 'visible', timeout: 30000 })
  const sessionId = await decodeJwtSessionId(guest, guestToken)
  assert(!!sessionId, `session_id decoded from guest JWT: ${sessionId}`)

  // 正規クライアント(SessionTab.tsx)が実際に送るのと同じ値を再現するため、
  // GET /{session_id}で現在のroundを取得してから8並列送信に載せる
  // (「本物のUIから見えている値を、うっかり/意図的に多重送信した」状況の再現。
  // expected_roundを省略/でたらめにするのは「対応していない旧クライアント」の
  // シナリオであり別物 — それは常に拒否されるだけなので検証価値が薄い)。
  // GET /{session_id}は参加者認証必須(require_participant、2026-08-11)のため
  // ゲスト自身のトークンを付ける。
  const before = await guest.evaluate(
    async ({ sid, token }) =>
      (await fetch(`/api/session/${sid}`, { headers: { 'Authorization': `Bearer ${token}` } })).json(),
    { sid: sessionId, token: guestToken },
  )
  const expectedRound = before.session?.round
  assert(typeof expectedRound === 'number', `current round fetched before send: ${expectedRound}`)

  // UIのボタン連打ではなく、同一トークン・同一expected_roundでの生fetchをN回
  // 同時発火させる(ブラウザのクリックデバウンス等の影響を受けない、サーバー側
  // ガードそのものの検証)。
  const results = await guest.evaluate(async ({ token, text, n, sessionId, expectedRound }) => {
    const calls = Array.from({ length: n }, () =>
      fetch(`/api/session/${sessionId}/human_turn`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ action: 'send', text, expected_round: expectedRound }),
      }).then(r => r.status).catch(() => -1)
    )
    return Promise.all(calls)
  }, { token: guestToken, text: MARKER_TEXT, n: N_PARALLEL, sessionId, expectedRound })

  const successCount = results.filter(s => s === 200).length
  const conflictCount = results.filter(s => s === 409).length
  console.log(`human_turn responses: ${JSON.stringify(results)}`)
  assert(successCount === 1, `exactly 1 of ${N_PARALLEL} parallel send calls should succeed (got ${successCount})`)
  assert(conflictCount === N_PARALLEL - 1, `the other ${N_PARALLEL - 1} should be rejected as stale (409), got ${conflictCount}`)

  // ターン処理完了を待つ
  await guest.waitForTimeout(6000)

  const hostBodyText = await host.locator('body').innerText()
  const markerOccurrences = hostBodyText.split(MARKER_TEXT).length - 1
  console.log(`marker occurrences on host's screen: ${markerOccurrences} (of ${N_PARALLEL} parallel calls)`)
  assert(markerOccurrences === 1, `marker text should appear exactly once on host's screen despite ${N_PARALLEL} parallel sends (found ${markerOccurrences})`)

  // 注: このテストはUI経由のクリックではなく生fetchでサーバーガードそのものを
  // 検証しているため、送信者(ゲスト)自身の画面には何も表示されない。
  // HUMAN_ACTIONはWS経由では「自分以外」にしか配信されない設計で、送信者本人の
  // 画面はsubmitHumanTurn()内のHTTPレスポンス直接処理(setMessages)でしか
  // 更新されない。生fetchはsubmitHumanTurn()を経由しないため、8回のうち
  // 200が返った1回についても本人の画面には反映されない — これはこのテストの
  // 検証手法(UIを経由しない)が持つ既知の限界であり、以前「送信者本人の画面が
  // 壊れる」と記録していたのはこの限界の誤診断だった可能性が高い(実UIクリックでの
  // 単発送信は他のe2eテストで正常動作を別途確認済み)。よってここでは検証しない。

  console.log('ai_turn_dedup.js: regression guard passed (duplicate /human_turn sends are correctly rejected)')
  } finally {
    // try本体のどこで例外が出てもbrowserを確実に閉じる。以前はbrowser.close()を
    // 成功パスの最後にしか呼んでおらず、assert失敗時にPlaywrightのハンドルが
    // 残ってNodeプロセスが終了せず、実CI実行でtimeout-minutesの上限まで無駄に
    // 占有する事態が実際に起きた(2026-08-22、ai_turn_dedup.js自身の8並列送信
    // タイミングflakeがこのハングを誘発しCI全体を8分ブロックした)。
    await browser.close()
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
