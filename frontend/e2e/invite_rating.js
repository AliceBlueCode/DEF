// 【既知のギャップを可視化するための特性テスト(characterization test)】
//
// マルチプレイ設計書13章のテスト観点表は「R18コードでSFWキャラを持ち込んだら通過、
// R18キャラはSFWセッションで拒否」という仕様を前提としている。しかし実際に
// session.py の join_session を読むと、招待コードの rating (session_rating) は
// audit_character_json() へLLM審査の文脈情報として渡されるだけで、キャラクター
// 自身の content_policy.rating_sexual / rating_violence と比較して拒否する
// ロジックはどこにも存在しない(2026-08-08 コードリーディングで確認。
// allowed_rating_sexual/allowed_rating_violence 設定はLLM生成物に対するフィルタ
// であり、参加時のキャラクターJSON自体のレーティング審査とは無関係)。
//
// このスクリプトは「あるべき挙動」ではなく「今実際に起きる挙動」を記録する。
// 以下のアサーションが失敗するようになったら、それはレーティングガードが
// 実装された合図であり、このテストとコメントを「拒否されることを検証する」
// 内容に書き換えること。
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

  // joinAsPlayer内部の「参加する」クリックで発火するPOST /api/session/joinの
  // レスポンスを捕まえたいが、リスナー登録がクリックに間に合わない可能性があるため
  // waitForResponseで確実に拾う(joinAsPlayerの完了を待つのと並行して仕込む)。
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

  // 【現状の挙動】content_policy.rating_sexual: "hentai" のキャラクターでも、
  // SFW招待コードへの参加が拒否されない(fail-openなLLM審査さえ通れば、
  // レーティングによる構造的なブロックは一切かからない)。
  assert(
    joinResponseStatus === 200,
    `[KNOWN GAP] R18-rated character (content_policy.rating_sexual="hentai") is currently ACCEPTED (HTTP ${joinResponseStatus}) into an SFW-invite session — no rating enforcement exists at join time`
  )

  await browser.close()
  console.log('invite_rating.js: characterization assertion passed (it documents a gap, not a guarantee — see comment at top)')
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
