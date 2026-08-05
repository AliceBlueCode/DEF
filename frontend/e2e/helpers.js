// マルチプレイヤー機能のE2Eテスト用ヘルパー。
//
// 前提: バックエンド(127.0.0.1:8511)とフロントエンドdevサーバー(localhost:3000)が
// 起動していること、LLMバックエンド(設定タブ)が疎通可能なAPIキー等で設定済みであること。
// `npm run dev`と`uvicorn def_kari.api.main:app --port 8511`を別ターミナルで
// 起動してから各シナリオを実行する。
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export const BASE_URL = 'http://localhost:3000'
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
export async function createOnlineSession(browser, { characterName = 'ChatGPT', viewport = { width: 1400, height: 900 } } = {}) {
  const ctx = await browser.newContext({ viewport })
  const page = await ctx.newPage()
  await page.goto(BASE_URL)
  await page.waitForTimeout(600)
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

// 招待コードでプレイヤーとして参加する(キャラJSON持ち込み)。
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
  await page.getByRole('button', { name: '参加する' }).click()
  await page.waitForTimeout(1200)
  return { ctx, page }
}

export async function startSession(hostPage) {
  await hostPage.getByRole('button', { name: 'セッション開始' }).click()
  await hostPage.waitForTimeout(1800)
}
