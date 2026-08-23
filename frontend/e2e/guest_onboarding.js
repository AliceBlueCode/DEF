// 【回帰防止テスト】招待コードで参加するゲストが、公開ポート(dual_run.pyの
// --public-port、frontend/distを直接配信する経路)経由で新設のTERMS同意
// オンボーディング画面(GuestGate→GuestOnboardingFlow)へ振り分けられること・
// TERMS同意チェックボックスが「続ける」をゲートすること・招待コード参加が
// 成功すること・join後はサイドバー/タブバーを持たない最小シェルへ遷移すること・
// 公開ポート経由のWSでセッションデータが実際に届くこと(AIキャラの実名表示)・
// ホスト側もPLAYER_JOINEDを受け取ること(双方向WS)、を一気通貫で確認する。
//
// 2026-08-23、TODO.md「参加者向けのTERMS同意導線」の実装。この経路(public_main.py
// が配信するfrontend/dist)はCIで一度も検証されていなかったため、
// .github/workflows/e2e.ymlをnpm run build + dual_run.py起動に変更してこの
// シナリオを追加した。既存のJoinDialog経由の詳細な参加フローedge case
// (スロット再選択・オンライン+空スロット判定等)はuseJoinFlow.tsへのロジック
// 共有により他シナリオ(joinAsPlayer経由)で既にカバーされているため、ここでは
// 重複検証しない。
//
// 実行: node frontend/e2e/guest_onboarding.js
// 前提: `npm run build`済み・`python -m def_kari.api.dual_run --local-port 8511
// --public-port 8512 --no-trust-cloudflare-tunnel`起動済み（README参照）。
import { chromium } from 'playwright'
import { assert, GUEST_BASE_URL, GUEST_CHAR_JSON, createOnlineSession, startSession } from './helpers.js'

;(async () => {
  const browser = await chromium.launch()
  try {
    const { page: host, inviteCode } = await createOnlineSession(browser, { characterName: 'ChatGPT', selectMockBackend: true })
    await startSession(host)

    const guestCtx = await browser.newContext({ viewport: { width: 420, height: 860 } })
    const guest = await guestCtx.newPage()
    await guest.goto(GUEST_BASE_URL)
    await guest.waitForTimeout(800)

    // ゲスト判定が発火し、専用オンボーディング画面が出ること
    // （App.tsxのサイドバー/タブバーは一切マウントされない）
    await guest.getByText('DEF(kari)').first().waitFor({ timeout: 10000 })
    assert(await guest.locator('.tabs').count() === 0, 'guest onboarding screen renders without App.tsx tab bar')
    assert(await guest.locator('.sidebar').count() === 0, 'guest onboarding screen renders without App.tsx sidebar')

    // ステップ1: 招待コード
    await guest.getByPlaceholder('SFW-ABK-492').fill(inviteCode)
    await guest.getByRole('button', { name: '続ける' }).click()
    await guest.waitForTimeout(600)

    // ステップ2: TERMS同意（チェック前は「続ける」が無効、チェック後に有効化）
    const termsScroll = guest.locator('.guest-terms-scroll')
    await termsScroll.waitFor({ state: 'visible', timeout: 10000 })
    const termsText = await termsScroll.innerText()
    assert(termsText.includes('利用規約'), 'TERMS.md content is fetched and rendered')
    assert(termsText.includes('18歳以上'), 'TERMS.md age-restriction clause is rendered')
    const continueBtn = guest.getByRole('button', { name: '続ける' })
    assert(await continueBtn.isDisabled(), 'continue button is disabled before consent checkbox is checked')
    await guest.locator('.guest-terms-consent input[type=checkbox]').check()
    assert(!(await continueBtn.isDisabled()), 'continue button is enabled after checking consent')
    await continueBtn.click()
    await guest.waitForTimeout(400)

    // ステップ3: キャラ選択（プレイヤーとして参加＋JSON持ち込み）
    await guest.locator('input[type=radio][value=__player__]').check()
    await guest.waitForTimeout(200)
    await guest.locator('input[type=file][accept=".json"]').setInputFiles(GUEST_CHAR_JSON)
    await guest.waitForTimeout(300)
    const joinResponsePromise = guest.waitForResponse(res => res.url().endsWith('/api/session/join'), { timeout: 15000 })
    await guest.getByRole('button', { name: '参加する' }).click()
    const joinResponse = await joinResponsePromise
    assert(joinResponse.status() === 200, `join succeeded over the public port (status ${joinResponse.status()})`)
    await guest.waitForTimeout(1500)

    // join後: サイドバー・タブバーを持たない最小シェルへ遷移していること
    assert(await guest.locator('.tabs').count() === 0, 'post-join guest shell has no App.tsx tab bar')
    assert(await guest.locator('.sidebar').count() === 0, 'post-join guest shell has no App.tsx sidebar')

    // 公開ポート経由のWSで実際にセッションデータが届いていること
    // （AIキャラの実名"ChatGPT"が表示される。生ID表示のままなら
    // name_map解決の失敗を意味する）
    const guestBodyText = await guest.locator('body').innerText()
    assert(guestBodyText.includes('ChatGPT'), "guest's page resolves the AI character's real name over the public-port WS/session data")

    // ホスト側もゲスト参加(PLAYER_JOINED)を認識していること（双方向WS確認）
    await host.waitForTimeout(500)
    const hostBodyText = await host.locator('body').innerText()
    assert(hostBodyText.includes('テストゲスト'), "host's page reflects the guest's character via PLAYER_JOINED across the port boundary")

    console.log('guest_onboarding.js: all assertions passed')
  } finally {
    await browser.close()
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
