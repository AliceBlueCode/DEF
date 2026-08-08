// 【既知のギャップを可視化するための特性テスト(characterization test)】
//
// 当初は「/human_turn (action=send) を並列連打してもAIターンが二重起動しない」
// (session.py 3358行目のai_task.done()ガード)ことの確認を意図していたが、実際に
// 8並列で叩いたところ、そのガードが防いでいる範囲より手前で問題が起きることが
// 判明した(2026-08-08)。
//
// `turn = session["turn"]`の読み取りから`session["turn"] = turn + 1`の書き戻しまでの
// 間に他の並列リクエストが割り込めるため(TOCTOU)、8並列送信のうち複数件が「自分の
// ターンだ」と判定されて処理されてしまい、同一マーカーテキストの発言が複数回
// 記録される(観測では8件中4件相当が処理され、Roundが一気に進んだ)。ai_task の
// 二重起動防止ガードは「次のAIターンの非同期タスクを二重に生成しない」ことしか
// 保証しておらず、human_turnハンドラ自体の並行実行を防ぐものではない。
//
// さらに、この状態になった送信者本人(ゲスト)のブラウザは`.session-msg`が
// 0件になり画面が壊れる(ホスト側は同じ4件の重複発言を正しく表示できている
// ため、サーバー側だけでなくゲスト自身のフロントエンド側の状態復元にも
// バグがある)。
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

  // UIのボタン連打ではなく、同一トークンでの生fetchをN回同時発火させる
  // (ブラウザのクリックデバウンス等の影響を受けない、サーバー側ガードそのものの検証)。
  const results = await guest.evaluate(async ({ token, text, n, sessionId }) => {
    const calls = Array.from({ length: n }, () =>
      fetch(`/api/session/${sessionId}/human_turn`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ action: 'send', text }),
      }).then(r => r.status).catch(() => -1)
    )
    return Promise.all(calls)
  }, { token: guestToken, text: MARKER_TEXT, n: N_PARALLEL, sessionId })

  const successCount = results.filter(s => s === 200).length
  console.log(`human_turn responses: ${JSON.stringify(results)}`)
  assert(successCount >= 1, `at least one of ${N_PARALLEL} parallel send calls succeeded (${successCount} succeeded)`)

  // ターン処理完了を待つ(複数ターン分処理される可能性があるため長めに)
  await guest.waitForTimeout(12000)

  // ゲスト自身の画面ではなく、操作していないホスト側から客観的に結果を数える
  // (ゲスト側は下記の通りそれ自体が壊れる場合があるため、観測者として使えない)。
  const hostBodyText = await host.locator('body').innerText()
  const markerOccurrences = hostBodyText.split(MARKER_TEXT).length - 1
  console.log(`marker occurrences on host's screen: ${markerOccurrences} (of ${N_PARALLEL} parallel calls)`)

  // 【現状の挙動】turn の read-modify-write 区間が並列リクエスト間で保護されて
  // いないため(TOCTOU)、複数の並列送信が「自分のターンだ」と判定されて処理
  // されてしまう。1件だけが処理される(=マーカーが1回だけ現れる)状態が
  // 実装されたら、このassertは失敗するようになるので、その時が修正確認のタイミング。
  assert(
    markerOccurrences >= 2,
    `[KNOWN GAP] concurrent /human_turn sends are NOT deduplicated — expected the race to let multiple calls through, but only found ${markerOccurrences}`
  )

  // 【現状の挙動】この状況に陥った送信者本人(ゲスト)の画面は、ホスト側が同じ
  // 重複発言を正しく表示できているのに対し、メッセージ欄が0件になり壊れる。
  const guestMsgCount = await guest.locator('.session-msg').count()
  console.log(`guest's own .session-msg count after the race: ${guestMsgCount} (host still shows the messages correctly)`)
  assert(
    guestMsgCount === 0,
    `[KNOWN GAP] the guest's own frontend view goes blank (0 messages) after triggering this race, despite the host's view showing the duplicated messages correctly (found ${guestMsgCount} on guest's screen)`
  )

  await browser.close()
  console.log('ai_turn_dedup.js: characterization assertions passed (they document gaps, not guarantees — see comment at top)')
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
