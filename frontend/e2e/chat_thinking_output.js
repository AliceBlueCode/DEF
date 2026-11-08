// 【v4.2.1 実機確認手順 A-3】1人用チャットで、思考モデルの出力（推論…</think>本文）を表示する。
//
// 1人用画面の最初のE2E（4.x 完了条件 D）。モックLLMの台本で、思考モデルが返しがちな形を
// 1つずつ返し、吹き出しに推論や </think> が出ないことを確かめる。
// - 推論…</think>{JSON}            → JSON の dialogue だけが出る
// - 推論…</think>プレーンな本文     → 本文だけが出る（JSON で返さないモデル）
// - {"dialogue": "</think> は…"}   → セリフの中の </think> は消さない（説明を頼んだ場合など）
// - <think>推論…（閉じない＝打ち切り） → 推論は吹き出しに出ない
//
// 実行: venv/Scripts/python scripts/e2e_local.py chat_thinking_output
import { chromium } from 'playwright'
import { assert, BASE_URL, mockCalls, mockReset, mockScript, mockRules, selectTextgenWebuiBackend, waitUntil } from './helpers.js'

const REASONING = 'ユーザーの意図を考えている途中の推論'

const CASES = [
  {
    label: 'reasoning then JSON',
    content: `${REASONING}。丁寧に返そう。</think>{"dialogue":"思考の後のJSONの本文です","emotion":"neutral","tags":[]}`,
    expect: '思考の後のJSONの本文です',
  },
  {
    label: 'reasoning then plain text',
    content: `${REASONING}。短く返そう。</think>思考の後のプレーンな本文です`,
    expect: '思考の後のプレーンな本文です',
  },
  {
    label: 'literal </think> inside the dialogue',
    content: '{"dialogue":"</think> は思考の終わりを示すタグです","emotion":"neutral","tags":[]}',
    expect: '</think> は思考の終わりを示すタグです',
    allowThinkTag: true,
  },
]

;(async () => {
  await mockReset()
  const browser = await chromium.launch()
  try {
    const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } })
    const page = await ctx.newPage()
    page.on('pageerror', e => console.log(`[pageerror] ${e.message}`))
    await page.goto(BASE_URL)
    await page.waitForTimeout(600)
    await selectTextgenWebuiBackend(page)
    await page.getByRole('button', { name: /チャット$/ }).click()
    await page.waitForTimeout(400)

    const input = page.getByPlaceholder('メッセージを入力...')
    const messages = page.locator('.message-text')

    for (const c of CASES) {
      await mockScript([mockRules.chatReply({ content: c.content }, { name: `chat:${c.label}`, times: 1 })])
      const before = await messages.count()
      await input.fill(`テスト: ${c.label}`)
      await page.getByRole('button', { name: '送信', exact: true }).click()
      await waitUntil(async () => {
        const texts = await messages.allInnerTexts()
        return texts.slice(before).some(t => t.includes(c.expect))
      }, { timeout: 30000, message: `reply for "${c.label}"` })

      const texts = (await messages.allInnerTexts()).slice(before)
      const reply = texts.find(t => t.includes(c.expect))
      assert(!reply.includes(REASONING), `${c.label}: reasoning is not shown in the bubble`)
      if (!c.allowThinkTag) assert(!reply.includes('</think>'), `${c.label}: no </think> in the bubble`)
      else assert(reply.includes(c.expect), `${c.label}: the literal </think> in the dialogue is kept`)
    }

    // 閉じない <think>（max_tokens で打ち切られた）: 推論が吹き出しに出ない
    // times を付けない: 構造化出力のフォールバックが再試行しても、同じ打ち切られた出力を返す
    // （times: 1 だと再試行に既定の「モック応答」が返り、閉じない <think> の処理が壊れていても通ってしまう）
    await mockScript([mockRules.chatReply({ content: `<think>${REASONING}。まだ考えて` }, { name: 'chat:truncated' })])
    const before = await messages.count()
    await input.fill('テスト: truncated')
    await page.getByRole('button', { name: '送信', exact: true }).click()
    await waitUntil(async () => (await input.isEnabled()) && (await messages.count()) > before,
      { timeout: 30000, message: 'response to the truncated reply' })
    await page.waitForTimeout(500)
    const all = (await messages.allInnerTexts()).slice(before).join('\n')
    const truncatedCalls = (await mockCalls()).filter(c => c.matched === 'chat:truncated').length
    assert(truncatedCalls >= 1, `truncated: the truncated output was actually returned (${truncatedCalls} calls)`)
    assert(!all.includes('モック応答'), 'truncated: no call fell through to the default mock reply')
    assert(!all.includes(REASONING), 'truncated: unfinished reasoning is not shown as dialogue')

    console.log('chat_thinking_output.js: all assertions passed')
  } finally {
    await browser.close()
    await mockReset().catch(() => {})
  }
})().catch(e => {
  console.error(e)
  process.exitCode = 1
})
