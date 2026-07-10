import { useState, useEffect, useCallback } from 'react'
import { useT } from '../i18n'

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
  character_name?: string
  backend?: string
  topic?: string
  round?: number
  user_text?: string
  error?: string
}

type T2IDebugInfo = {
  backend?: string
  model?: string
  workflow?: string
  prompt_input?: string
  quality_tags?: string
  prompt_final?: string
  negative_prompt?: string
  width?: number
  height?: number
  seed?: number
  steps?: number
  cfg_scale?: number
  url?: string
  error?: string
}

type TFn = (key: string, vars?: Record<string, string | number>) => string

function buildSummaryText(debug: DebugInfo, label: string, t: TFn): string {
  const lines: string[] = []
  lines.push(t('debug.summary.rawResponse', { label }))
  lines.push(debug.raw || t('debug.none'))
  lines.push('')
  lines.push(t('debug.summary.processed'))
  lines.push(`text: ${debug.text ?? ''}`)
  lines.push(`emotion: ${debug.emotion ?? ''}`)
  lines.push(`image_prompt_en: ${debug.image_prompt_en ?? ''}`)
  lines.push(`tags: ${JSON.stringify(debug.tags ?? [])}`)
  lines.push(t('debug.summary.verdict', { result: debug.success ? t('debug.status.success') : t('debug.status.failure') }))
  lines.push('')
  lines.push(t('debug.summary.fallbackChain'))
  for (const a of debug.attempts ?? []) {
    lines.push(`[${a.stage ?? ''}]`)
    if (a.raw) lines.push(a.raw.slice(0, 500))
    for (const e of a.errors ?? []) lines.push(`  ${t('debug.error', { message: e })}`)
    lines.push('')
  }
  return lines.join('\n')
}

function DebugSection({ debug, label }: { debug: DebugInfo; label: string }) {
  const t = useT()
  const [copied, setCopied] = useState(false)
  const summaryText = buildSummaryText(debug, label, t)

  const copy = () => {
    navigator.clipboard.writeText(summaryText).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="debug-mode-section">
      <h2 className="debug-mode-title">{label}</h2>

      <div className="debug-meta">
        {debug.character_id && <span>{t('debug.meta.char', { name: debug.character_name || debug.character_id })}</span>}
        {debug.backend && <span>{t('debug.meta.backend', { backend: debug.backend })}</span>}
        {debug.topic && <span>{t('debug.meta.topic', { topic: debug.topic })}</span>}
        {debug.round != null && <span>{t('debug.meta.round', { round: debug.round })}</span>}
        <span className={debug.success ? 'debug-ok' : 'debug-fail'}>
          {debug.success ? t('debug.status.success') : t('debug.status.failure')}
        </span>
      </div>

      {debug.user_text && (
        <section className="debug-section">
          <h3>{t('debug.section.userText')}</h3>
          <pre className="debug-code small">{debug.user_text}</pre>
        </section>
      )}

      <section className="debug-section">
        <h3>{t('debug.section.rawResponse')}</h3>
        <pre className="debug-code">{debug.raw || t('debug.none')}</pre>
      </section>

      <section className="debug-section">
        <h3>{t('debug.section.processed')}</h3>
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
          <h3>{t('debug.section.fallbackChain')}</h3>
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
          <h3>{t('debug.section.copyText')}</h3>
          <button onClick={copy} className="debug-copy-btn">
            {copied ? t('debug.copyBtn.copied') : t('debug.copyBtn')}
          </button>
        </div>
        <pre className="debug-code">{summaryText}</pre>
      </section>
    </div>
  )
}

function T2IDebugSection({ debug }: { debug: T2IDebugInfo }) {
  const t = useT()
  const [copied, setCopied] = useState(false)
  const summaryText = [
    `backend: ${debug.backend ?? ''}`,
    `model: ${debug.model ?? ''}`,
    `workflow: ${debug.workflow ?? ''}`,
    `size: ${debug.width ?? ''}x${debug.height ?? ''}`,
    `seed: ${debug.seed ?? -1}  steps: ${debug.steps ?? ''}  cfg: ${debug.cfg_scale ?? ''}`,
    '',
    t('debug.summary.inputPrompt'),
    debug.prompt_input ?? '',
    '',
    `quality_tags: ${debug.quality_tags ?? t('debug.none')}`,
    '',
    t('debug.summary.finalPrompt'),
    debug.prompt_final ?? '',
    '',
    t('debug.summary.negativePrompt'),
    debug.negative_prompt ?? '',
  ].join('\n')

  const copy = () => {
    navigator.clipboard.writeText(summaryText).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="debug-mode-section">
      <h2 className="debug-mode-title">{t('debug.section.t2i')}</h2>

      <div className="debug-meta">
        {debug.backend && <span>{t('debug.meta.backend', { backend: debug.backend })}</span>}
        {debug.model && <span>{t('debug.meta.model', { model: debug.model })}</span>}
        {debug.workflow && <span>{t('debug.meta.workflow', { workflow: debug.workflow })}</span>}
        {debug.width && <span>{t('debug.meta.size', { w: debug.width, h: debug.height ?? '' })}</span>}
        {debug.seed != null && <span>seed: <b>{debug.seed}</b></span>}
        {debug.url && <span><a href={debug.url} target="_blank" rel="noreferrer">{t('debug.meta.generatedImage')}</a></span>}
        {debug.error && <span className="debug-fail">❌ {debug.error}</span>}
      </div>

      <section className="debug-section">
        <h3>{t('debug.t2i.inputPromptLabel')}</h3>
        <pre className="debug-code">{debug.prompt_input || t('debug.none')}</pre>
      </section>

      {debug.quality_tags && (
        <section className="debug-section">
          <h3>{t('debug.t2i.qualityTagsLabel')}</h3>
          <pre className="debug-code small">{debug.quality_tags}</pre>
        </section>
      )}

      <section className="debug-section">
        <h3>{t('debug.t2i.finalPromptLabel')}</h3>
        <pre className="debug-code">{debug.prompt_final || t('debug.none')}</pre>
      </section>

      <section className="debug-section">
        <h3>{t('debug.t2i.negativePromptLabel')}</h3>
        <pre className="debug-code small">{debug.negative_prompt || t('debug.none')}</pre>
      </section>

      <section className="debug-section">
        <div className="debug-copy-header">
          <h3>{t('debug.section.copyText')}</h3>
          <button onClick={copy} className="debug-copy-btn">
            {copied ? t('debug.copyBtn.copied') : t('debug.copyBtn')}
          </button>
        </div>
        <pre className="debug-code">{summaryText}</pre>
      </section>
    </div>
  )
}

export default function DebugTab() {
  const t = useT()
  const [chatDebug, setChatDebug] = useState<DebugInfo | null>(null)
  const [sessionDebug, setSessionDebug] = useState<DebugInfo | null>(null)
  const [t2iDebug, setT2iDebug] = useState<T2IDebugInfo | null>(null)
  const [loading, setLoading] = useState(false)

  const fetchAll = useCallback(() => {
    setLoading(true)
    Promise.all([
      fetch('/api/chat/debug').then(r => r.json()),
      fetch('/api/session/debug').then(r => r.json()),
      fetch('/api/t2i/debug').then(r => r.json()),
    ]).then(([chat, session, t2i]) => {
      setChatDebug(Object.keys(chat).length ? chat : null)
      setSessionDebug(Object.keys(session).length ? session : null)
      setT2iDebug(Object.keys(t2i).length ? t2i : null)
    }).finally(() => setLoading(false))
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  return (
    <div className="tab-content debug-tab">
      <div className="debug-header">
        <h2>{t('debug.heading')}</h2>
        <button onClick={fetchAll} disabled={loading} className="debug-refresh-btn">
          {loading ? t('debug.refreshBtn.loading') : t('debug.refreshBtn')}
        </button>
      </div>

      <div className="debug-modes">
        {chatDebug && <DebugSection debug={chatDebug} label={t('debug.section.chat')} />}
        {sessionDebug && <DebugSection debug={sessionDebug} label={t('debug.section.session')} />}
        {t2iDebug
          ? <T2IDebugSection debug={t2iDebug} />
          : <div className="debug-mode-section"><p style={{color:'var(--text-muted,#888)'}}>{t('debug.t2i.notYetGenerated')}</p></div>
        }
      </div>
    </div>
  )
}
