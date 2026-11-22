// ルールシステムの画面部品（ui の口。差し込み口 11、B-052、基本設計書 11.5）。
// 描く中身（盤面・用語・文言・ログ・選択肢）は、サーバーが形を確かめた ui_state をそのまま描く。
// 文字はすべて文字として描く（HTML として扱わない。dangerouslySetInnerHTML を使わない）。
// 部品のボタンなど、DEF が持つ文字列だけを i18n のキーで出す。
import { useCallback, useEffect, useState } from 'react'
import { useT } from '../i18n'

type Pos = [number, number]
type Style = 'primary' | 'secondary' | 'info' | 'ok' | 'blocked' | 'dimmed'
type Choice = { id: string; label: string }

type GridBoard = {
  type: 'grid_board'; id: string; cols: number; rows: number
  col_labels: string[] | null; row_labels: string[] | null
  terrains: Record<string, { label: string; color: string; height: number | null }>
  cells: { pos: Pos; terrain: string }[]
  tokens: { id: string; pos: Pos; label: string; side: string | null; marks: Style[] }[]
  overlays: { cells: Pos[]; style: Style; label: string | null }[]
  lines: { from: Pos; to: Pos; style: Style; label: string | null }[]
  selectable: { cells: Pos[]; tokens: string[] }
}
type StatusPanel = {
  type: 'status_panel'; id: string
  order: { label: string; value: string | number | null }[]
  groups: { title: string; rows: { label: string; items: { label: string; value: string | number; max: string | number | null }[] }[] }[]
}
type CheckLog = { type: 'check_log'; id: string; entries: { id: string; text: string; tags: string[]; cancelled: boolean }[] }
type Approval = { type: 'approval'; id: string; summary: string[]; choices: Choice[]; inputs: { id: string; label: string; value: string | number | null }[] }
type Question = { type: 'question'; id: string; prompt: string; choices: Choice[]; free_text: boolean }
type Component = GridBoard | StatusPanel | CheckLog | Approval | Question
type UiState = { ui_schema: number; title: string; revision: number | null; components: Component[] }

// 見た目の種類（決まった名前だけ）→ 色。色そのものをプラグインが決められるのは地形だけ
const STYLE_COLOR: Record<Style, string> = {
  primary: '#3b82f6', secondary: '#a855f7', info: '#06b6d4', ok: '#22c55e', blocked: '#ef4444', dimmed: '#9ca3af',
}
const CELL = 28
const LABEL = 22

type SendAction = (component: string, action: string, data: Record<string, unknown>) => void

function posLabel(b: GridBoard, p: Pos): string {
  const c = b.col_labels?.[p[0]] ?? String(p[0] + 1)
  const r = b.row_labels?.[p[1]] ?? String(p[1] + 1)
  return `${c}${r}`
}

function Board({ b, send }: { b: GridBoard; send: SendAction }) {
  const t = useT()
  const terrainAt = new Map(b.cells.map(c => [`${c.pos[0]},${c.pos[1]}`, c.terrain]))
  const selCells = new Set(b.selectable.cells.map(p => `${p[0]},${p[1]}`))
  const selTokens = new Set(b.selectable.tokens)
  const w = LABEL + b.cols * CELL
  const h = LABEL + b.rows * CELL
  const center = (p: Pos) => [LABEL + p[0] * CELL + CELL / 2, LABEL + p[1] * CELL + CELL / 2]
  const cells = []
  for (let r = 0; r < b.rows; r++) {
    for (let c = 0; c < b.cols; c++) {
      const key = `${c},${r}`
      const terrain = b.terrains[terrainAt.get(key) ?? '']
      const selectable = selCells.has(key)
      cells.push(
        <rect key={key} x={LABEL + c * CELL} y={LABEL + r * CELL} width={CELL} height={CELL}
          fill={terrain?.color ?? 'transparent'} stroke="rgba(128,128,128,0.4)" strokeWidth={0.5}
          style={{ cursor: selectable ? 'pointer' : 'default' }}
          onClick={selectable ? () => send(b.id, 'select_cell', { pos: [c, r] }) : undefined}>
          <title>{posLabel(b, [c, r])}{terrain ? ` ${terrain.label}${terrain.height != null ? ` (${terrain.height})` : ''}` : ''}</title>
        </rect>,
      )
    }
  }
  return (
    <div className="rule-ui-board">
      <div style={{ overflowX: 'auto' }}>
        <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', maxWidth: w * 1.6, minWidth: Math.min(w, 320) }} role="img">
          {Array.from({ length: b.cols }, (_, c) => (
            <text key={`c${c}`} x={LABEL + c * CELL + CELL / 2} y={LABEL - 6} fontSize={10} textAnchor="middle" fill="currentColor">
              {b.col_labels?.[c] ?? c + 1}
            </text>
          ))}
          {Array.from({ length: b.rows }, (_, r) => (
            <text key={`r${r}`} x={LABEL - 4} y={LABEL + r * CELL + CELL / 2 + 3} fontSize={10} textAnchor="end" fill="currentColor">
              {b.row_labels?.[r] ?? r + 1}
            </text>
          ))}
          {cells}
          {b.overlays.map((o, i) => o.cells.map(p => (
            <rect key={`o${i}-${p[0]},${p[1]}`} x={LABEL + p[0] * CELL + 2} y={LABEL + p[1] * CELL + 2}
              width={CELL - 4} height={CELL - 4} fill={STYLE_COLOR[o.style]} fillOpacity={0.25}
              stroke={STYLE_COLOR[o.style]} strokeWidth={1.5} pointerEvents="none" />
          )))}
          {Array.from(selCells).map(k => {
            const [c, r] = k.split(',').map(Number)
            return <rect key={`s${k}`} x={LABEL + c * CELL + 1} y={LABEL + r * CELL + 1} width={CELL - 2} height={CELL - 2}
              fill="none" stroke="currentColor" strokeDasharray="3 2" strokeWidth={1} pointerEvents="none" />
          })}
          {b.lines.map((l, i) => {
            const [x1, y1] = center(l.from)
            const [x2, y2] = center(l.to)
            return <line key={`l${i}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke={STYLE_COLOR[l.style]} strokeWidth={2}
              strokeDasharray={l.style === 'blocked' ? '4 3' : undefined} pointerEvents="none" />
          })}
          {b.tokens.map(tk => {
            const [x, y] = center(tk.pos)
            const color = tk.marks[0] ? STYLE_COLOR[tk.marks[0]] : '#6b7280'
            const selectable = selTokens.has(tk.id)
            return (
              <g key={tk.id} style={{ cursor: selectable ? 'pointer' : 'default' }}
                onClick={selectable ? () => send(b.id, 'select_token', { token: tk.id }) : undefined}>
                <circle cx={x} cy={y} r={CELL / 2 - 3} fill={color} fillOpacity={tk.marks.includes('dimmed') ? 0.4 : 0.9}
                  stroke={selectable ? 'currentColor' : 'white'} strokeWidth={selectable ? 2 : 1} />
                <text x={x} y={y + 3} fontSize={8} textAnchor="middle" fill="white">{tk.label.slice(0, 3)}</text>
                <title>{tk.label} {posLabel(b, tk.pos)}</title>
              </g>
            )
          })}
        </svg>
      </div>
      <ul className="rule-ui-legend" style={{ listStyle: 'none', padding: 0, margin: '4px 0', fontSize: '0.8em', display: 'flex', flexWrap: 'wrap', gap: '2px 12px' }}>
        {b.tokens.map(tk => <li key={tk.id}>{tk.label}: {posLabel(b, tk.pos)}</li>)}
        {Object.entries(b.terrains).map(([k, tr]) => (
          <li key={`t${k}`}><span style={{ display: 'inline-block', width: 10, height: 10, background: tr.color, marginRight: 4 }} />{tr.label}</li>
        ))}
        {b.overlays.filter(o => o.label).map((o, i) => (
          <li key={`ol${i}`}><span style={{ color: STYLE_COLOR[o.style] }}>■</span> {o.label}</li>
        ))}
        {b.lines.filter(l => l.label).map((l, i) => (
          <li key={`ll${i}`}><span style={{ color: STYLE_COLOR[l.style] }}>—</span> {l.label} ({posLabel(b, l.from)}→{posLabel(b, l.to)})</li>
        ))}
      </ul>
      {b.selectable.cells.length + b.selectable.tokens.length > 0 && (
        <p style={{ fontSize: '0.78em', opacity: 0.7, margin: 0 }}>{t('trpg.ruleUi.selectHint')}</p>
      )}
    </div>
  )
}

function Status({ s }: { s: StatusPanel }) {
  return (
    <div className="rule-ui-status" style={{ fontSize: '0.85em' }}>
      {s.order.length > 0 && (
        <ol style={{ margin: '0 0 6px', paddingLeft: 20 }}>
          {s.order.map((o, i) => <li key={i}>{o.label}{o.value != null ? ` (${o.value})` : ''}</li>)}
        </ol>
      )}
      {s.groups.map((g, gi) => (
        <div key={gi} style={{ marginBottom: 6 }}>
          <div style={{ fontWeight: 600 }}>{g.title}</div>
          {g.rows.map((r, ri) => (
            <div key={ri} style={{ display: 'flex', flexWrap: 'wrap', gap: '0 10px' }}>
              <span style={{ minWidth: 80 }}>{r.label}</span>
              {r.items.map((it, ii) => <span key={ii}>{it.label} {it.value}{it.max != null ? `/${it.max}` : ''}</span>)}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function Log({ l }: { l: CheckLog }) {
  return (
    <ol className="rule-ui-log" style={{ fontSize: '0.82em', margin: 0, paddingLeft: 20, maxHeight: 220, overflowY: 'auto' }}>
      {l.entries.map(e => (
        <li key={e.id} style={{ textDecoration: e.cancelled ? 'line-through' : undefined, opacity: e.cancelled ? 0.5 : 1, whiteSpace: 'pre-wrap' }}>
          {e.text}
          {e.tags.length > 0 && <span style={{ opacity: 0.6 }}> [{e.tags.join(', ')}]</span>}
        </li>
      ))}
    </ol>
  )
}

function ApprovalBox({ a, send }: { a: Approval; send: SendAction }) {
  const [inputs, setInputs] = useState<Record<string, string>>({})
  useEffect(() => {
    setInputs(Object.fromEntries(a.inputs.map(i => [i.id, i.value == null ? '' : String(i.value)])))
  }, [a])
  return (
    <div className="rule-ui-approval" style={{ border: '1px solid var(--border-color, #888)', borderRadius: 6, padding: 8 }}>
      {a.summary.map((line, i) => <p key={i} style={{ margin: '0 0 4px', whiteSpace: 'pre-wrap' }}>{line}</p>)}
      {a.inputs.map(i => (
        <label key={i.id} style={{ display: 'flex', gap: 6, alignItems: 'center', margin: '4px 0', fontSize: '0.85em' }}>
          <span>{i.label}</span>
          <input value={inputs[i.id] ?? ''} onChange={e => setInputs(v => ({ ...v, [i.id]: e.target.value }))} />
        </label>
      ))}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
        {a.choices.map(c => (
          <button key={c.id} onClick={() => send(a.id, 'choose', { choice: c.id, inputs })}>{c.label}</button>
        ))}
      </div>
    </div>
  )
}

function QuestionBox({ q, send }: { q: Question; send: SendAction }) {
  const t = useT()
  const [text, setText] = useState('')
  return (
    <div className="rule-ui-question" style={{ border: '1px solid var(--border-color, #888)', borderRadius: 6, padding: 8 }}>
      <p style={{ margin: '0 0 6px', whiteSpace: 'pre-wrap' }}>{q.prompt}</p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {q.choices.map(c => <button key={c.id} onClick={() => send(q.id, 'answer', { choice: c.id })}>{c.label}</button>)}
      </div>
      {q.free_text && (
        <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
          <input style={{ flex: 1 }} value={text} placeholder={t('trpg.ruleUi.freeTextPlaceholder')} onChange={e => setText(e.target.value)} />
          <button disabled={!text.trim()} onClick={() => { send(q.id, 'answer', { text }); setText('') }}>{t('trpg.ruleUi.send')}</button>
        </div>
      )}
    </div>
  )
}

export function RuleUiPanel({ sessionId, token, refreshKey }: { sessionId: string; token: string; refreshKey: number }) {
  const t = useT()
  const [ui, setUi] = useState<UiState | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [error, setError] = useState('')
  const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {}

  const load = useCallback(async () => {
    try {
      const res = await fetch(`/api/session/${sessionId}/rule_ui`, { headers })
      const data = await res.json()
      if (!res.ok || !data.ui) return
      setUi(data.ui as UiState)
      setProblems(Array.isArray(data.problems) ? data.problems : [])
    } catch { /* 次の更新で取り直す */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, token])

  useEffect(() => { void load() }, [load, refreshKey])

  const send: SendAction = async (component, action, data) => {
    setError('')
    try {
      const res = await fetch(`/api/session/${sessionId}/rule_ui/action`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ component, action, data, base_revision: ui?.revision ?? null }),
      })
      if (!res.ok) {
        const d = await res.json().catch(() => ({}))
        setError(typeof d.detail === 'string' ? d.detail : t('trpg.ruleUi.refused'))
      }
    } catch {
      setError(t('trpg.ruleUi.refused'))
    }
    void load()
  }

  if (!ui) return null
  return (
    // 画面の高さに収まらなければ縮み、部品の中でスクロールする（中身の高さのまま伸びると、セッションの画面の
    // 縦の並びからはみ出して、盤面などの下の部分に届かなかった。2026-11-22 の実機確認）
    <section className="rule-ui-panel" style={{ padding: '6px 10px', display: 'flex', flexDirection: 'column', gap: 8,
                                                flex: '0 1 auto', minHeight: 0, overflowY: 'auto' }}>
      {ui.title && <h3 style={{ margin: 0, fontSize: '1em' }}>{ui.title}</h3>}
      {problems.length > 0 && (
        <details style={{ fontSize: '0.78em', color: 'var(--error-color, #e74c3c)' }}>
          <summary>{t('trpg.ruleUi.problems').replace('{n}', String(problems.length))}</summary>
          <ul style={{ margin: 0 }}>{problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
        </details>
      )}
      {error && <p role="alert" style={{ margin: 0, fontSize: '0.82em', color: 'var(--error-color, #e74c3c)' }}>{error}</p>}
      {ui.components.map(c => {
        switch (c.type) {
          case 'grid_board': return <Board key={c.id} b={c} send={send} />
          case 'status_panel': return <Status key={c.id} s={c} />
          case 'check_log': return <Log key={c.id} l={c} />
          case 'approval': return <ApprovalBox key={c.id} a={c} send={send} />
          case 'question': return <QuestionBox key={c.id} q={c} send={send} />
          default: return null
        }
      })}
    </section>
  )
}
