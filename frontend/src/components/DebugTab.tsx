import { useState, useEffect, useCallback } from 'react'

type Attempt = {
  stage?: string
  raw?: string
  errors?: string[]
}

type DebugInfo = {
  success?: boolean
  text?: string
  emotion?: string
  image_prompt_en?: string
  tags?: string[]
  raw?: string
  attempts?: Attempt[]
  character_id?: string
  backend?: string
  error?: string
}

export default function DebugTab() {
  const [debug, setDebug] = useState<DebugInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  const fetch_debug = useCallback(() => {
    setLoading(true)
    fetch('/api/chat/debug')
      .then(r => r.json())
      .then(data => setDebug(Object.keys(data).length ? data : null))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { fetch_debug() }, [fetch_debug])

  const summaryText = (() => {
    if (!debug) return ''
    const lines: string[] = []
    lines.push('=== LLM 生応答 ===')
    lines.push(debug.raw || '(なし)')
    lines.push('')
    lines.push('=== 加工後 ===')
    lines.push(`text: ${debug.text ?? ''}`)
    lines.push(`emotion: ${debug.emotion ?? ''}`)
    lines.push(`image_prompt_en: ${debug.image_prompt_en ?? ''}`)
    lines.push(`tags: ${JSON.stringify(debug.tags ?? [])}`)
    lines.push(`判定: ${debug.success ? '✅ 成功' : '❌ 失敗'}`)
    lines.push('')
    lines.push('=== フォールバックチェーン ===')
    for (const a of debug.attempts ?? []) {
      lines.push(`[${a.stage ?? ''}]`)
      if (a.raw) lines.push(a.raw.slice(0, 500))
      for (const e of a.errors ?? []) lines.push(`  エラー: ${e}`)
      lines.push('')
    }
    return lines.join('\n')
  })()

  const copy = () => {
    navigator.clipboard.writeText(summaryText).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="tab-content debug-tab">
      <div className="debug-header">
        <h2>デバッグ</h2>
        <button onClick={fetch_debug} disabled={loading} className="debug-refresh-btn">
          {loading ? '読込中...' : '🔄 更新'}
        </button>
      </div>

      {!debug ? (
        <p className="debug-empty">チャットを送信するとデバッグ情報が表示されます。</p>
      ) : (
        <>
          <div className="debug-meta">
            {debug.character_id && <span>キャラ: <b>{debug.character_id}</b></span>}
            {debug.backend && <span>バックエンド: <b>{debug.backend}</b></span>}
            <span className={debug.success ? 'debug-ok' : 'debug-fail'}>
              {debug.success ? '✅ 成功' : '❌ 失敗'}
            </span>
          </div>

          <section className="debug-section">
            <h3>LLM 生応答</h3>
            <pre className="debug-code">{debug.raw || '(なし)'}</pre>
          </section>

          <section className="debug-section">
            <h3>加工後</h3>
            <table className="debug-table">
              <tbody>
                <tr><th>text</th><td>{debug.text}</td></tr>
                <tr><th>emotion</th><td>{debug.emotion}</td></tr>
                <tr><th>image_prompt_en</th><td>{debug.image_prompt_en}</td></tr>
                <tr><th>tags</th><td>{JSON.stringify(debug.tags ?? [])}</td></tr>
              </tbody>
            </table>
          </section>

          {(debug.attempts?.length ?? 0) > 0 && (
            <section className="debug-section">
              <h3>フォールバックチェーン</h3>
              {debug.attempts!.map((a, i) => (
                <div key={i} className="debug-attempt">
                  <div className="debug-attempt-stage">[{a.stage ?? `attempt ${i + 1}`}]</div>
                  {a.raw && <pre className="debug-code small">{a.raw.slice(0, 500)}</pre>}
                  {a.errors?.map((e, j) => (
                    <div key={j} className="debug-error">⚠ {e}</div>
                  ))}
                </div>
              ))}
            </section>
          )}

          <section className="debug-section">
            <div className="debug-copy-header">
              <h3>コピー用テキスト</h3>
              <button onClick={copy} className="debug-copy-btn">
                {copied ? '✅ コピー済み' : '📋 コピー'}
              </button>
            </div>
            <pre className="debug-code">{summaryText}</pre>
          </section>
        </>
      )}
    </div>
  )
}
