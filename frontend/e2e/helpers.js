// マルチプレイヤー機能のE2Eテスト用ヘルパー。
//
// 前提: バックエンド(127.0.0.1:8511)とフロントエンドdevサーバー(localhost:3000)が
// 起動していること、LLMバックエンド(設定タブ)が疎通可能なAPIキー等で設定済みであること。
// `npm run dev`と`uvicorn def_kari.api.main:app --port 8511`を別ターミナルで
// 起動してから各シナリオを実行する。
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// ローカルで別環境に流すとき（scripts/e2e_local.py）は環境変数で宛先を変える。
export const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:3000'
// dual_run.pyの公開ポート（`--no-trust-cloudflare-tunnel`でloopback直起動、CI/ローカル
// e2e向け）。ホストのnpm run devプロキシ経由のBASE_URLとは別物で、frontend/dist（要
// npm run build）をpublic_main.pyが直接配信する経路——実ゲストが辿るのと同じ経路を
// 検証するために存在する（guest_onboarding.js参照、2026-08-23）。
export const GUEST_BASE_URL = process.env.E2E_GUEST_BASE_URL || 'http://127.0.0.1:8512'
export const GUEST_CHAR_JSON = path.join(__dirname, 'fixtures', 'test_guest_char.json')

export function assert(cond, message) {
  if (!cond) {
    console.error(`FAIL: ${message}`)
    process.exitCode = 1
    throw new Error(message)
  }
  console.log(`OK: ${message}`)
}

// テキストに部分一致する<span>のうち、実際に画面上で見えているものをクリックする。
// キャラクター選択ドロップダウンのように同名要素がメッセージ履歴等にも存在する場面向け。
export async function clickVisibleSpan(page, text) {
  const candidates = page.locator('span', { hasText: text })
  const n = await candidates.count()
  for (let i = 0; i < n; i++) {
    const el = candidates.nth(i)
    if (await el.isVisible()) {
      await el.click()
      return true
    }
  }
  throw new Error(`visible span not found: ${text}`)
}

export async function openSessionTab(page) {
  await page.getByRole('button', { name: '🎭 セッション' }).click()
  await page.waitForTimeout(400)
}

export async function openSettingsTab(page) {
  await page.getByRole('button', { name: /^⚙.*設定$/ }).click()
  await page.waitForTimeout(400)
}

// 数値入力設定(切断タイムアウト等)をラベルテキストで探して変更する。
export async function setNumberSetting(page, labelText, value) {
  const row = page.locator('.settings-row', { has: page.locator('label', { hasText: labelText }) })
  const input = row.locator('input[type=number]')
  await input.fill(String(value))
  await input.blur()
  await page.waitForTimeout(300)
}

// サイドバーのトグルスイッチ(投票強制賛成等)をラベルテキストで探してON/OFFする。
export async function setToggle(page, labelText, checked) {
  const row = page.locator('div', { has: page.locator('span', { hasText: labelText }) }).last()
  const input = row.locator('input[type=checkbox]')
  const current = await input.isChecked()
  if (current !== checked) await row.locator('label.toggle-switch').click()
}

// ホストとしてオンラインセッションを作成し、ロビー画面(招待コード発行済み)まで進める。
// selectMockBackend: trueならセッション作成前にtextgen_webui(モックLLM)へ切り替える
// (session["backend"]はstart時点のスナップショットのため、作成後の切り替えでは
// 反映されない——AIターン生成が実際に走ることまで検証したいシナリオ向け)。
export async function createOnlineSession(browser, { characterName = 'ChatGPT', viewport = { width: 1400, height: 900 }, selectMockBackend = false } = {}) {
  const ctx = await browser.newContext({ viewport })
  const page = await ctx.newPage()
  await page.goto(BASE_URL)
  await page.waitForTimeout(600)
  if (selectMockBackend) {
    await selectTextgenWebuiBackend(page)
  }
  await openSessionTab(page)
  await page.getByPlaceholder('キャラクターを選択...').click()
  await page.waitForTimeout(300)
  await clickVisibleSpan(page, characterName)
  await page.waitForTimeout(300)
  await page.locator('h2, h1').first().click({ force: true }).catch(() => {})
  await page.waitForTimeout(300)
  await page.getByRole('button', { name: /オンラインセッション作成/ }).click()
  await page.waitForTimeout(1200)

  const bodyText = await page.locator('body').innerText()
  const m = bodyText.match(/[A-Z0-9]{2,4}-[A-Z0-9]{3}-\d{3}/)
  const inviteCode = m ? m[0] : null
  assert(!!inviteCode, 'invite code issued')
  return { ctx, page, inviteCode }
}

// このタブのApp.tsx側selectedBackend stateをtextgen_webui(モックLLM)へ
// 明示的に切り替える。data/llm_services.jsonがgit管理下にopenaiエントリを
// 持つため(APIキー未設定)、CIのDEFAULT_LLM_BACKENDは実は"openai"のまま
// フォールバックが効いていない(2026-08-22、実CIでai_keeperのAPIキー
// 未設定エラーから発覚——他のe2eシナリオはAI発言の中身を検証しないため
// この問題が表面化していなかった)。data/settings.jsonへ直接POSTしても
// このstateには反映されない(App.tsxは起動時にlocalStorage→
// /api/settings/backendsのdefaultしか見ておらず、永続化済みuser設定を
// 読み返す経路が無い)ため、実際に設定タブのセレクトを操作する。
// textgen_webuiは既にモックが「起動中」と応答するため、launchBackend()が
// 実プロセス起動を試みることはない(already_running扱い)。
export async function selectTextgenWebuiBackend(page) {
  await openSettingsTab(page)
  // 非表示タブもdisplay:noneでDOMに残り続ける(App.tsxのタブ切替方式)ため、
  // NovelTab.tsx側のバックエンドセレクト(novel-backend-sel)も同じ
  // option[value="textgen_webui"]を持ち、素の絞り込みだと2件ヒットして
  // strict modeエラーになる。:visibleで現在表示中のタブのセレクトだけに絞る。
  const llmBackendSelect = page.locator('select:visible').filter({ has: page.locator('option[value="textgen_webui"]') })
  await llmBackendSelect.waitFor({ state: 'visible', timeout: 10000 })
  await llmBackendSelect.selectOption('textgen_webui')
  await page.waitForTimeout(300)
}

// ホストとしてTRPGモードのオンラインセッションを作成し、ロビー画面(招待コード
// 発行済み)まで進める。createOnlineSessionと違いホストはキャラを選ばない
// (「オンラインセッション作成」ボタンはselectedChars件数では無効化されない、
// startOnlineSession呼び出し元のJSX参照)——ホストはキーパー専任のまま、
// 参加者のキャラだけがinitiativeに乗る決定的な状態を作るため。
// rulebook: 指定すればTRPGモードON後にルールブック選択(<select>、value=ルールブックID)を
// 明示的に選ぶ(2026-08-23、ゲストのキャラクターシート選択機能のe2e向けに追加。
// 未指定時は挙動不変=デフォルト選択のまま)。
export async function createOnlineTrpgSession(browser, { viewport = { width: 1400, height: 900 }, rulebook = '' } = {}) {
  const ctx = await browser.newContext({ viewport })
  const page = await ctx.newPage()
  await page.goto(BASE_URL)
  await page.waitForTimeout(600)
  await selectTextgenWebuiBackend(page)
  await openSessionTab(page)
  await page.getByRole('button', { name: /TRPGモード/ }).click()
  await page.waitForTimeout(300)
  if (rulebook) {
    const rulebookSelect = page.locator('.session-field', { has: page.locator('label', { hasText: 'ルールブック' }) }).locator('select')
    await rulebookSelect.waitFor({ state: 'visible', timeout: 5000 })
    await rulebookSelect.selectOption(rulebook)
    await page.waitForTimeout(200)
  }
  await page.getByRole('button', { name: /オンラインセッション作成/ }).click()
  await page.waitForTimeout(1200)

  const bodyText = await page.locator('body').innerText()
  const m = bodyText.match(/[A-Z0-9]{2,4}-[A-Z0-9]{3}-\d{3}/)
  const inviteCode = m ? m[0] : null
  assert(!!inviteCode, 'invite code issued (TRPG mode)')
  return { ctx, page, inviteCode }
}

// 招待コードでプレイヤーとして参加する(キャラJSON持ち込み)。
// ゲストは以後ターン待ちの間WS受信のみで能動的な認証済みリクエストを出さない
// ことがあるため(trackAuthTokensでは拾えない場合がある)、join応答のplayer_token
// をここで直接捕まえて返す。
export async function joinAsPlayer(browser, inviteCode, { charJsonPath = GUEST_CHAR_JSON, viewport = { width: 1400, height: 900 } } = {}) {
  const ctx = await browser.newContext({ viewport })
  const page = await ctx.newPage()
  await page.goto(BASE_URL)
  await page.waitForTimeout(600)
  await openSessionTab(page)
  await page.getByRole('button', { name: /招待コードで参加/ }).click()
  await page.waitForTimeout(400)
  await page.getByPlaceholder('SFW-ABK-492').fill(inviteCode)
  await page.getByPlaceholder('SFW-ABK-492').blur()
  await page.waitForTimeout(700)
  await page.locator('input[type=radio][value=__player__]').check()
  await page.waitForTimeout(200)
  await page.locator('input[type=file][accept=".json"]').setInputFiles(charJsonPath)
  await page.waitForTimeout(200)
  const joinResponsePromise = page.waitForResponse(res => res.url().endsWith('/api/session/join'), { timeout: 15000 })
  await page.getByRole('button', { name: '参加する' }).click()
  const joinResponse = await joinResponsePromise
  let playerToken = null
  try {
    playerToken = (await joinResponse.json()).player_token || null
  } catch { /* ignore */ }
  await page.waitForTimeout(1200)
  return { ctx, page, playerToken }
}

// セッション開始後、initiativeの先頭がAIキャラクターだと自動では進行しない
// （SessionTab.tsxのコメント通り、オフライン同様「自動」トグルか「次の発言」で
// ホストが能動的に始める設計）。initiativeは開始時にシャッフルされるため、
// 先頭がAI/人間のどちらになるかは実行のたびに変わる——ローカルの手動テストでは
// 開発者のブラウザに前回操作分の「自動」設定がlocalStorageで残っていて気づかれ
// なかったが、Playwrightの毎回まっさらなブラウザコンテキストでは先頭がAIだと
// 誰のターンも進まないまま止まる。ホストとして明示的に「自動」を有効化し、
// AIターンを含めて確実に進行させる。
export async function startSession(hostPage) {
  await hostPage.getByRole('button', { name: 'セッション開始' }).click()
  await hostPage.waitForTimeout(1800)
  await hostPage.locator('button.auto-advance-btn').first().click()
}

// バックエンドのWS直接URL（フロントのViteプロキシを経由しない生WebSocket接続用）。
export const WS_URL = process.env.E2E_WS_URL || 'ws://127.0.0.1:8511'

// ページが送信するAuthorizationヘッダーからBearerトークンを継続的に収集する。
// createOnlineSession/joinAsPlayer が返した直後(何らかの認証済みリクエストが
// 飛ぶ前)に呼ぶこと。tokens配列は以後リアルタイムに追記される。
export function trackAuthTokens(page) {
  const tokens = []
  page.on('request', req => {
    const auth = req.headers()['authorization']
    if (auth && auth.startsWith('Bearer ')) {
      const t = auth.slice(7)
      if (!tokens.includes(t)) tokens.push(t)
    }
  })
  return tokens
}

// トークンが1件以上採取されるまで待つ。
export async function waitForToken(tokens, timeoutMs = 8000) {
  const t0 = Date.now()
  while (tokens.length === 0) {
    if (Date.now() - t0 > timeoutMs) throw new Error('no auth token captured in time')
    await new Promise(r => setTimeout(r, 100))
  }
  return tokens[tokens.length - 1]
}

// 生WebSocketをページコンテキスト内で開く。first-message authでtokenを送る
// (tokenがnullなら送らない＝未認証接続のテスト用)。戻り値はハンドルID。
export async function openRawWs(page, sessionId, token) {
  return page.evaluate(({ sessionId, token, wsUrl }) => {
    const id = `raw_${Math.random().toString(36).slice(2)}`
    const ws = new WebSocket(`${wsUrl}/api/session/${sessionId}/ws`)
    window.__rawWs = window.__rawWs || {}
    window.__rawWsLog = window.__rawWsLog || {}
    window.__rawWs[id] = ws
    window.__rawWsLog[id] = { messages: [], closeCode: null, closed: false, opened: false }
    ws.onopen = () => {
      window.__rawWsLog[id].opened = true
      if (token !== null) ws.send(JSON.stringify({ type: 'auth', token }))
    }
    ws.onmessage = e => window.__rawWsLog[id].messages.push(e.data)
    ws.onclose = e => { window.__rawWsLog[id].closed = true; window.__rawWsLog[id].closeCode = e.code }
    return id
  }, { sessionId, token, wsUrl: WS_URL })
}

export async function rawWsSend(page, id, obj) {
  await page.evaluate(({ id, obj }) => window.__rawWs[id].send(JSON.stringify(obj)), { id, obj })
}

export async function rawWsState(page, id) {
  return page.evaluate(id => window.__rawWsLog[id], id)
}

export async function rawWsClose(page, id) {
  await page.evaluate(id => { try { window.__rawWs[id].close() } catch {} }, id)
}

// ── モックLLMの台本（scripts/e2e_mock_llm.py、2026-11-08） ──────────────────
// 規則の形はモックの docstring を参照。シナリオの最初に mockReset() を呼び、
// 前のシナリオの規則と呼び出しの記録を消してから台本を足す。
export const MOCK_LLM_URL = process.env.MOCK_LLM_URL || 'http://127.0.0.1:5000'

async function mockPost(path, payload) {
  const res = await fetch(`${MOCK_LLM_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload ?? {}),
  })
  if (!res.ok) throw new Error(`mock LLM ${path} failed: ${res.status}`)
  return res.json()
}

export async function mockReset() {
  return mockPost('/_reset', {})
}

export async function mockScript(rules) {
  return mockPost('/_script', { rules })
}

// 呼び出しの記録 [{n, matched, text}]。matched は当たった規則の name（既定の応答なら ''）。
export async function mockCalls() {
  const res = await fetch(`${MOCK_LLM_URL}/_calls`)
  return res.json()
}

// 条件を満たすまで待つ（ポーリング）。満たさなければ message で失敗する。
export async function waitUntil(fn, { timeout = 30000, interval = 300, message = 'condition' } = {}) {
  const t0 = Date.now()
  for (;;) {
    const v = await fn()
    if (v) return v
    if (Date.now() - t0 > timeout) throw new Error(`timeout waiting for: ${message}`)
    await new Promise(r => setTimeout(r, interval))
  }
}

// 呼び出しの種類ごとの照合条件（DEFの日本語プロンプト基準。2026-11-08 の調査に基づく）。
// 会話の履歴に過去の指示が残るので、種類は「最後の user メッセージ」、話しているキャラは
// 「system の あなたの役割: 名前」で見分ける。プロンプトの文言を変えたら、ここも直す。
//   行動選択   session_turn_engine._ai_action_select（TRPG・Round 2以降。JSON・入れ子不可）
//   発言       _generate_ai_turn_reply → generate_structured_reply（JSON。RESPONSE_SCHEMA）
//   弁明       vote_deliberate（発言と同じ形。最後の user が deliberation_prompt）
//   判定計画   judgment_planner._decide_check_pairs（JSON {"judgments": [...]}）
//   語り       gm_agent.narrate（テキスト。【シーン進行】【セッション終了提案】で合図）
//   チャット   chat.py（発言と同じ形。あなたの役割: が無い）
export const mockRules = {
  // AIの行動選択。action: none|skip|extend|designate|vote。payload は target_name/vote_type/vote_detail/reason
  actionSelect: (name, action, payload = {}, extra = {}) => ({
    name: `action:${name}:${action}`,
    last_user_contains: ['[TRPGアクション選択]', `、${name}のターンです`],
    json: { action, target_name: '', vote_type: '', vote_detail: '', reason: '', ...payload },
    ...extra,
  }),
  // セッションでのAIの発言（弁明を除く）。reply は json か content を含むオブジェクト
  dialogue: (name, reply, extra = {}) => ({
    name: `dialogue:${name}`,
    system_contains: [`あなたの役割: ${name}`],
    last_user_not_contains: ['[TRPGアクション選択]', '今、投票が提案されています:'],
    json_mode: true,
    ...reply,
    ...extra,
  }),
  // 投票の弁明
  deliberation: (name, reply, extra = {}) => ({
    name: `deliberation:${name}`,
    system_contains: [`あなたの役割: ${name}`],
    last_user_contains: ['今、投票が提案されています:'],
    ...reply,
    ...extra,
  }),
  // キーパーの判定計画。judgments: [{character: 名前, skill: '察知'}]
  judgmentPlan: (judgments, extra = {}) => ({
    name: 'judgment-plan',
    system_contains: ['あなたはTRPGの判定要否決定システムです'],
    json: { judgments },
    ...extra,
  }),
  // キーパーの語り（テキスト）
  keeperNarration: (text, extra = {}) => ({
    name: 'keeper-narration',
    last_user_contains: ['キーパーとして、直近の状況を踏まえて場面を進めてください。'],
    json_mode: false,
    content: text,
    ...extra,
  }),
  // 1人用チャットの返事（セッションの文脈が無い = あなたの役割: が無い）
  chatReply: (reply, extra = {}) => ({
    name: 'chat',
    json_mode: true,
    not_contains: ['あなたの役割:', '[TRPGアクション選択]', 'あなたはTRPGの判定要否決定システムです'],
    ...reply,
    ...extra,
  }),
}

// このタブのセッションIDとトークン（作成・参加が成功した時点で sessionStorage に入る）。
export async function getSessionAuth(page) {
  const state = await page.evaluate(() => {
    try { return JSON.parse(sessionStorage.getItem('def_active_session') || 'null') } catch { return null }
  })
  if (!state?.sessionId || !state?.token) throw new Error('session restore state not found in sessionStorage')
  return state
}

// このタブの権限で、セッションのAPIを呼ぶ（Viteのプロキシ経由）。戻り値は {status, body}。
export async function sessionApi(page, path, { method = 'POST', body } = {}) {
  const { sessionId, token } = await getSessionAuth(page)
  return page.evaluate(async ({ url, method, body, token }) => {
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    let data = null
    try { data = await res.json() } catch { /* ignore */ }
    return { status: res.status, body: data }
  }, { url: `/api/session/${sessionId}${path}`, method, body, token })
}

// ロビーにAIキャラを追加する（ホストのタブで）。名前ではなくキャラID（data/public/characters の名前）。
export async function lobbyAddAi(hostPage, charId) {
  const r = await sessionApi(hostPage, '/lobby/add_ai', { body: { character_id: charId } })
  if (r.status !== 200) throw new Error(`lobby/add_ai ${charId} failed: ${r.status} ${JSON.stringify(r.body)}`)
  return r.body
}

// バックエンドを再起動する（scripts/e2e_local.py の制御用の窓口。CI の素の起動には無い）。
// 応答が返った時点で、新しいプロセスが /api/health に答えている。
export const E2E_CONTROL_URL = process.env.E2E_CONTROL_URL || ''
export async function restartBackend() {
  if (!E2E_CONTROL_URL) throw new Error('restartBackend needs scripts/e2e_local.py (E2E_CONTROL_URL is not set)')
  const res = await fetch(`${E2E_CONTROL_URL}/restart-backend`, { method: 'POST' })
  if (!res.ok) throw new Error(`backend restart failed: ${res.status}`)
}
