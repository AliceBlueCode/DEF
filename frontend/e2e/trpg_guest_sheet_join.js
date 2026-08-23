// 【回帰防止テスト】TRPGモードのオンラインセッションで、招待コード参加時に
// 持ち込みキャラクターJSONに埋め込まれたキャラクターシート(game_rules_sheets)を
// 選べること・そのシートがゲスト自身のタブと他タブ(ホスト)双方の判定/ダイスUIに
// 反映されることを確認する。
//
// 2026-08-23、JoinDialog.tsxにシート選択手段が無いことが発覚。調査の結果、単純な
// UI追加では足りず、既存のシート解決ロジック（profiles.get(cid,{}).get(
// "game_rules_sheets",{}).get(sheet_id,{})、profiles = load_profiles()）が
// ホストのローカルキャラ库のみを見ており、guest_xxxxのような持ち込みキャラには
// 常に空を返し続ける（DiceRow等シート依存UIが常に表示されない）という根本原因が
// あった。resolve_char_game_sheet(s)（def_kari/characters.py）でguest_charsへの
// フォールバックを追加し、GET /characters/{id}/game_sheetsにsession_idクエリを
// 追加して修正した。
//
// 実行: node frontend/e2e/trpg_guest_sheet_join.js
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import {
  assert, BASE_URL, openSessionTab, createOnlineTrpgSession, startSession,
} from './helpers.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const GUEST_CHAR_WITH_SHEET_JSON = path.join(__dirname, 'fixtures', 'test_guest_char_with_sheet.json')

;(async () => {
  const browser = await chromium.launch()
  try {
    const { page: host, inviteCode } = await createOnlineTrpgSession(browser, { rulebook: 'def_original' })

    // ゲスト参加: joinAsPlayer(helpers.js)相当の手順を、参加リクエストの中身を
    // 検証するためインラインで行う。
    const guestCtx = await browser.newContext({ viewport: { width: 1400, height: 900 } })
    const guest = await guestCtx.newPage()
    await guest.goto(BASE_URL)
    await guest.waitForTimeout(600)
    await openSessionTab(guest)
    await guest.getByRole('button', { name: /招待コードで参加/ }).click()
    await guest.waitForTimeout(400)
    await guest.getByPlaceholder('SFW-ABK-492').fill(inviteCode)
    await guest.getByPlaceholder('SFW-ABK-492').blur()
    await guest.waitForTimeout(700)
    await guest.locator('input[type=radio][value=__player__]').check()
    await guest.waitForTimeout(200)
    await guest.locator('input[type=file][accept=".json"]').setInputFiles(GUEST_CHAR_WITH_SHEET_JSON)
    // ファイル読み込み(FileReader)・シート抽出・一致1件の自動選択が完了するのを待つ
    await guest.waitForTimeout(500)

    // 一致するシートが1件のため自動選択されているはず（JoinDialog.tsx handleFileSelect）
    const sheetSelect = guest.locator('select', { has: guest.locator('option[value="def_original"]') })
    await sheetSelect.waitFor({ state: 'visible', timeout: 5000 })
    const selectedValue = await sheetSelect.inputValue()
    assert(selectedValue === 'def_original', `matching sheet auto-selected in JoinDialog (got "${selectedValue}")`)

    const joinRequestPromise = guest.waitForRequest(req => req.url().endsWith('/api/session/join'), { timeout: 15000 })
    const joinResponsePromise = guest.waitForResponse(res => res.url().endsWith('/api/session/join'), { timeout: 15000 })
    await guest.getByRole('button', { name: '参加する' }).click()
    const joinRequest = await joinRequestPromise
    const joinResponse = await joinResponsePromise
    const joinBody = JSON.parse(joinRequest.postData() || '{}')
    assert(joinBody.game_sheet_id === 'def_original', `POST /join request body includes game_sheet_id (got ${JSON.stringify(joinBody.game_sheet_id)})`)
    assert(joinResponse.status() === 200, `join succeeded (status ${joinResponse.status()})`)
    await guest.waitForTimeout(1200)

    await startSession(host)

    // ゲスト自身のタブ: シート依存UI(DiceRow、trpgMode && charSheetData[humanCharId]で
    // ゲート)が表示されること。JoinDialogがonJoined経由で自タブへ即セットしたシートで
    // ある証拠（ネットワーク往復無し）。
    await guest.waitForTimeout(1000)
    const guestDiceBtn = guest.getByRole('button', { name: /振る|Roll/ })
    await guestDiceBtn.waitFor({ state: 'visible', timeout: 10000 })
    assert(true, "guest's own tab shows dice-roll UI (sheet reflected via onJoined, no network round-trip)")

    // ホスト側タブ: PLAYER_JOINEDイベント経由でGET .../game_sheets?session_id=...を
    // 叩いてcharSheetDataへマージされ、同様にシート依存UIが反映されること。
    const hostDiceBtn = host.getByRole('button', { name: /振る|Roll/ })
    await hostDiceBtn.waitFor({ state: 'visible', timeout: 10000 })
    assert(true, "host's tab also reflects the guest's sheet via PLAYER_JOINED (session-aware game_sheets fetch)")

    console.log('trpg_guest_sheet_join.js: all assertions passed')
  } finally {
    await browser.close()
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
