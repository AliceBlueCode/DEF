// 【回帰防止テスト】招待コードのレーティング照合。
//
// マルチプレイ設計書13章のテスト観点表の期待挙動: 「R18コードでSFWキャラを
// 持ち込んだら通過、R18キャラはSFWセッションで拒否」。当初は
// content_policy.rating_sexual/rating_violenceを招待コードのレーティングと
// 比較するロジックがどこにも存在せず、fail-openなLLM審査さえ通れば無条件で
// 参加できてしまっていたが、修正済み（2026-08-09）:
// def_kari/safety/filters.py の character_rating_exceeds_invite() が
// SFW/R15/R18/UNL each の許容rating_sexual/rating_violenceと照合し、
// join_session（character_json持ち込み・claim_char_id双方）とセッション内
// T2I生成（_generate_session_image_impl、持ち込みキャラのみ）の両方で
// このガードを通す。
//
// 実行: node frontend/e2e/invite_rating.js
import { chromium } from 'playwright'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { assert, createOnlineSession, openSessionTab, BASE_URL } from './helpers.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const R18_CHAR_JSON = path.join(__dirname, 'fixtures', 'test_r18_guest_char.json')

;(async () => {
  const browser = await chromium.launch()

  // オンラインセッション作成時の自動発行コードはSFW固定(session.py 1736行目)。
  const { inviteCode } = await createOnlineSession(browser)
  assert(inviteCode.startsWith('SFW-'), `invite code is SFW-rated by default: ${inviteCode}`)

  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } })
  const r18Guest = await ctx.newPage()
  const joinResponsePromise = r18Guest.waitForResponse(res => res.url().endsWith('/api/session/join'), { timeout: 15000 })

  await r18Guest.goto(BASE_URL)
  await r18Guest.waitForTimeout(600)
  await openSessionTab(r18Guest)
  await r18Guest.getByRole('button', { name: /招待コードで参加/ }).click()
  await r18Guest.waitForTimeout(400)
  await r18Guest.getByPlaceholder('SFW-ABK-492').fill(inviteCode)
  await r18Guest.getByPlaceholder('SFW-ABK-492').blur()
  await r18Guest.waitForTimeout(700)
  await r18Guest.locator('input[type=radio][value=__player__]').check()
  await r18Guest.waitForTimeout(200)
  await r18Guest.locator('input[type=file][accept=".json"]').setInputFiles(R18_CHAR_JSON)
  await r18Guest.waitForTimeout(200)
  await r18Guest.getByRole('button', { name: '参加する' }).click()

  const joinResponse = await joinResponsePromise
  const joinResponseStatus = joinResponse.status()

  assert(
    joinResponseStatus === 400,
    `R18-rated character (content_policy.rating_sexual="hentai") should be REJECTED (400) from an SFW-invite session, got HTTP ${joinResponseStatus}`
  )

  // JoinDialog.tsxはdata.detailをそのままエラー欄へ表示する設計。UI上にも
  // 拒否理由が見えていること(サイレントな拒否になっていないか)を確認する。
  await r18Guest.waitForTimeout(300)
  const bodyText = await r18Guest.locator('body').innerText()
  assert(/rating/i.test(bodyText), 'rejection reason is shown in the join dialog UI')

  await browser.close()
  console.log('invite_rating.js: regression guard passed (over-rated character is rejected at join time)')
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
