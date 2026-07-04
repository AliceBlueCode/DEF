import { useState, useEffect, useRef } from 'react'

type Character = { id: string; name: string; image_color?: string }

type SessionMessage = {
  character_id: string
  character_name: string
  text: string
  emotion: string
  tags: string[]
  imageColor?: string
  isHuman?: boolean
  isRevealed?: boolean
  audioUrl?: string
}

type SavedSession = {
  filename: string
  topic: string
  saved_at: string
  round: number
  character_names: string[]
}

type Props = {
  characters: Character[]
  backend: string
  ttsBackend: string
}

const SEXUAL_TAGS = ['sfw', 'nsfw', 'hentai']
const VIOLENCE_TAGS = ['violence', 'gore', 'extreme']

function isContentBlocked(tags: string[], allowedSexual: string[], allowedViolence: string[]): boolean {
  return tags.some(tag =>
    (SEXUAL_TAGS.includes(tag) && !allowedSexual.includes(tag)) ||
    (VIOLENCE_TAGS.includes(tag) && !allowedViolence.includes(tag))
  )
}

// ── マルチセレクト ────────────────────────────────────────────
function CharMultiSelect({
  characters,
  selected,
  onChange,
}: {
  characters: Character[]
  selected: string[]
  onChange: (ids: string[]) => void
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const unselected = characters.filter(c => !selected.includes(c.id))
  const filtered = search
    ? unselected.filter(c => c.name.includes(search))
    : unselected

  const add = (id: string) => { onChange([...selected, id]); setSearch('') }
  const remove = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    onChange(selected.filter(s => s !== id))
  }

  return (
    <div className="char-multiselect" ref={ref}>
      <div className="char-multiselect-input" onClick={() => setOpen(true)}>
        {selected.map(id => {
          const c = characters.find(c => c.id === id)
          if (!c) return null
          return (
            <span key={id} className="char-tag" style={c.image_color ? { borderColor: c.image_color } : undefined}>
              <img src={`/api/characters/${id}/icon`} alt="" className="char-tag-icon" />
              {c.name}
              <button className="char-tag-remove" onClick={e => remove(id, e)}>×</button>
            </span>
          )
        })}
        <input
          className="char-multiselect-search"
          placeholder={selected.length === 0 ? 'キャラクターを選択...' : ''}
          value={search}
          onChange={e => setSearch(e.target.value)}
          onFocus={() => setOpen(true)}
        />
      </div>
      {open && filtered.length > 0 && (
        <div className="char-multiselect-dropdown">
          {filtered.map(c => (
            <div key={c.id} className="char-option" onClick={() => add(c.id)}>
              <img src={`/api/characters/${c.id}/icon`} alt="" className="char-option-icon" />
              <span>{c.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── メインコンポーネント ──────────────────────────────────────
type RuleOption = { id: string; label: string }

export default function SessionTab({ characters, backend, ttsBackend }: Props) {
  const [selectedChars, setSelectedChars] = useState<string[]>([])
  const [topic, setTopic] = useState('')
  const [ruleSet, setRuleSet] = useState('default')
  const [ruleOptions, setRuleOptions] = useState<RuleOption[]>([])
  const [sessionId, setSessionId] = useState('')
  const [messages, setMessages] = useState<SessionMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [round, setRound] = useState(1)
  const [humanInput, setHumanInput] = useState('')
  const [initiative, setInitiative] = useState<string[]>([])
  const [allowedSexual, setAllowedSexual] = useState<string[]>(['sfw'])
  const [allowedViolence, setAllowedViolence] = useState<string[]>(['violence'])
  const [autoAdvance, setAutoAdvance] = useState(false)
  const autoAdvanceRef = useRef(false)
  const [actionsPerTurn, setActionsPerTurn] = useState(3)
  const actionsPerTurnRef = useRef(3)
  const [ttsEnabled, setTtsEnabled] = useState(false)
  const ttsEnabledRef = useRef(false)
  const prefetchRef = useRef<any>(null)
  const [standingFallback, setStandingFallback] = useState<Set<string>>(new Set())
  const [savedSessions, setSavedSessions] = useState<SavedSession[]>([])
  const [saveStatus, setSaveStatus] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const fetchSavedSessions = () => {
    fetch('/api/session/saved')
      .then(r => r.json())
      .then(d => setSavedSessions(d.sessions || []))
      .catch(() => {})
  }

  useEffect(() => {
    fetch('/api/settings')
      .then(r => r.json())
      .then(res => {
        const s = res.settings ?? res
        if (s.allowed_rating_sexual) setAllowedSexual(s.allowed_rating_sexual)
        if (s.allowed_rating_violence) setAllowedViolence(s.allowed_rating_violence)
        if (s.session_actions_per_turn) {
          setActionsPerTurn(s.session_actions_per_turn)
          actionsPerTurnRef.current = s.session_actions_per_turn
        }
        if ('tts_enabled' in s) {
          setTtsEnabled(!!s.tts_enabled)
          ttsEnabledRef.current = !!s.tts_enabled
        }
      })
      .catch(() => {})

    const onSettingsChange = (e: Event) => {
      const { key, value } = (e as CustomEvent).detail
      if (key === 'tts_enabled') {
        setTtsEnabled(!!value)
        ttsEnabledRef.current = !!value
      }
    }
    window.addEventListener('def-settings-change', onSettingsChange)
    fetch('/api/session/rules')
      .then(r => r.json())
      .then(d => {
        if (d.rules?.length) {
          setRuleOptions(d.rules)
          setRuleSet(d.rules[0].id)
        }
      })
      .catch(() => {})
    fetchSavedSessions()
    return () => window.removeEventListener('def-settings-change', onSettingsChange)
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const charMap = Object.fromEntries(characters.map(c => [c.id, c]))

  const startSession = async () => {
    if (selectedChars.length < 1) return
    setLoading(true)
    try {
      const res = await fetch('/api/session/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character_ids: selectedChars, topic, backend, rule_set: ruleSet, actions_per_turn: actionsPerTurn }),
      })
      const data = await res.json()
      setSessionId(data.session_id)
      setInitiative(data.initiative || [])
      setMessages([])
      setRound(1)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const generateTTSUrl = async (text: string, characterId: string): Promise<string | null> => {
    if (!ttsEnabledRef.current || !ttsBackend) return null
    try {
      const res = await fetch('/api/tts/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, character_id: characterId, backend: ttsBackend }),
      })
      if (!res.ok) return null
      const blob = await res.blob()
      const form = new FormData()
      form.append('file', blob, 'audio.wav')
      const saveRes = await fetch('/api/tts/save', { method: 'POST', body: form })
      const saveData = await saveRes.json()
      return saveData.url as string
    } catch (e) {
      console.error('TTS generate error:', e)
      return null
    }
  }

  const playAudio = (url: string): Promise<void> =>
    new Promise(resolve => {
      const audio = new Audio(url)
      audio.onended = () => resolve()
      audio.onerror = () => resolve()
      audio.play().catch(() => resolve())
    })

  const fetchNextData = (sid: string) =>
    fetch('/api/session/next', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sid, backend }),
    }).then(r => r.json()).catch(() => null)

  const nextTurn = async (sessionIdOverride?: string, batchRemaining?: number) => {
    const sid = sessionIdOverride ?? sessionId
    if (!sid) return
    const rem = batchRemaining ?? actionsPerTurnRef.current
    setLoading(true)
    try {
      // 先読みデータがあればそれを使い、なければ API 呼び出し
      let data: any
      if (prefetchRef.current) {
        data = prefetchRef.current
        prefetchRef.current = null
      } else {
        data = await fetchNextData(sid)
      }
      if (!data || data.error) { console.error(data?.error); return }

      const char = charMap[data.character_id]
      setMessages(prev => [...prev, {
        character_id: data.character_id,
        character_name: data.character_name,
        text: data.text,
        emotion: data.emotion,
        tags: data.tags || [],
        imageColor: char?.image_color ?? undefined,
      }])
      setRound(data.round)

      const nextRem = rem - 1
      const willContinue = nextRem > 0 || autoAdvanceRef.current

      // TTS 生成
      const ttsUrl = data.text ? await generateTTSUrl(data.text, data.character_id) : null
      if (ttsUrl) {
        setMessages(prev => {
          const last = prev.length - 1
          return last < 0 ? prev : prev.map((m, i) => i === last ? { ...m, audioUrl: ttsUrl } : m)
        })
        // 音声再生と並行して次セリフを先読み
        if (willContinue && !prefetchRef.current) {
          fetchNextData(sid).then(d => {
            if (d && !d.error) prefetchRef.current = d
          })
        }
        await playAudio(ttsUrl)
      }

      if (nextRem > 0) {
        setTimeout(() => nextTurn(sid, nextRem), 200)
      } else if (autoAdvanceRef.current) {
        setTimeout(() => nextTurn(sid, actionsPerTurnRef.current), 300)
      }
    } catch (e) {
      console.error(e)
      setAutoAdvance(false)
      autoAdvanceRef.current = false
    } finally {
      setLoading(false)
    }
  }

  const retakeTurn = async () => {
    if (!sessionId || loading) return
    setAutoAdvance(false)
    autoAdvanceRef.current = false
    prefetchRef.current = null
    const res = await fetch(`/api/session/${sessionId}/retake`, { method: 'POST' })
    const data = await res.json()
    if (data.error) { console.error(data.error); return }
    const removed = data.removed ?? 0
    if (removed > 0) {
      setMessages(prev => prev.slice(0, -removed))
    }
    nextTurn(sessionId, actionsPerTurnRef.current)
  }

  const toggleAutoAdvance = () => {
    const next = !autoAdvance
    setAutoAdvance(next)
    autoAdvanceRef.current = next
    if (next && !loading) nextTurn(undefined, actionsPerTurnRef.current)
  }

  const sendHuman = async () => {
    if (!humanInput.trim() || !sessionId) return
    await fetch('/api/session/human', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId, message: humanInput }),
    })
    setMessages(prev => [...prev, {
      character_id: 'human',
      character_name: 'You',
      text: humanInput,
      emotion: '',
      tags: [],
      isHuman: true,
    }])
    setHumanInput('')
  }

  const revealMessage = (index: number) => {
    setMessages(prev => prev.map((m, i) => i === index ? { ...m, isRevealed: true } : m))
  }

  const saveCurrentSession = async () => {
    if (!sessionId) return
    setSaveStatus('保存中...')
    try {
      const res = await fetch(`/api/session/${sessionId}/save`, { method: 'POST' })
      const data = await res.json()
      if (data.status === 'ok') {
        setSaveStatus('保存完了')
        fetchSavedSessions()
        setTimeout(() => setSaveStatus(''), 2000)
      } else {
        setSaveStatus('保存失敗')
        setTimeout(() => setSaveStatus(''), 2000)
      }
    } catch {
      setSaveStatus('保存失敗')
      setTimeout(() => setSaveStatus(''), 2000)
    }
  }

  const loadSavedSession = async (filename: string) => {
    setLoading(true)
    try {
      const res = await fetch('/api/session/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      })
      const data = await res.json()
      if (data.error) { console.error(data.error); return }

      const nameMap: Record<string, string> = data.name_map || {}
      const history: any[] = data.history || []
      const reconstructed: SessionMessage[] = history.map(h => {
        if (h.role === 'user') {
          return { character_id: 'human', character_name: 'You', text: h.content, emotion: '', tags: [], isHuman: true }
        }
        const name = nameMap[h.character_id] || h.character_id
        const prefix = name + ': '
        const text = h.content.startsWith(prefix) ? h.content.slice(prefix.length) : h.content
        return {
          character_id: h.character_id,
          character_name: name,
          text,
          emotion: h.emotion || '',
          tags: h.tags || [],
          imageColor: charMap[h.character_id]?.image_color,
        }
      })

      setSessionId(data.session_id)
      setInitiative(data.initiative || [])
      setRound(data.round || 1)
      setMessages(reconstructed)
      setStandingFallback(new Set())
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const endSession = () => {
    setSessionId('')
    setMessages([])
    setInitiative([])
    setRound(1)
    setAutoAdvance(false)
    autoAdvanceRef.current = false
    fetchSavedSessions()
  }

  // ── セットアップ画面 ──────────────────────────────────────
  if (!sessionId) {
    return (
      <div className="tab-content session-tab">
        <div className="session-setup">
          <h2>セッションモード</h2>

          <div className="session-field">
            <label className="session-label">参加キャラクター（1人以上選択）</label>
            <CharMultiSelect
              characters={characters}
              selected={selectedChars}
              onChange={setSelectedChars}
            />
          </div>

          {selectedChars.length > 0 && (
            <div className="session-participants">
              <div className="session-participants-header">
                <span>参加者: {selectedChars.length}</span>
              </div>
              <ul className="session-participants-list">
                {selectedChars.map(id => (
                  <li key={id}>{charMap[id]?.name ?? id}</li>
                ))}
              </ul>
            </div>
          )}

          {selectedChars.length === 0 && (
            <p className="session-hint">1人以上のキャラクターを選択してください。</p>
          )}

          {ruleOptions.length > 0 && (
            <div className="session-field">
              <label className="session-label">セッションルール</label>
              <select
                className="session-select"
                value={ruleSet}
                onChange={e => setRuleSet(e.target.value)}
              >
                {ruleOptions.map(r => (
                  <option key={r.id} value={r.id}>{r.label}</option>
                ))}
              </select>
            </div>
          )}

          <div className="session-field">
            <label className="session-label">セッションのお題</label>
            <input
              className="session-topic-input"
              type="text"
              value={topic}
              onChange={e => setTopic(e.target.value)}
              placeholder="例: わたしの恋愛 / 統治と信頼 / 星降る夜の物語"
            />
          </div>

          <button
            className="start-btn"
            onClick={startSession}
            disabled={selectedChars.length < 1 || loading}
          >
            セッション開始
          </button>

          {savedSessions.length > 0 && (
            <div className="session-field">
              <label className="session-label">保存済みセッション</label>
              <div className="session-saved-list">
                {savedSessions.map(s => (
                  <div key={s.filename} className="session-saved-item" onClick={() => loadSavedSession(s.filename)}>
                    <span className="saved-topic">{s.topic || '(無題)'}</span>
                    <span className="saved-meta">{s.character_names.join(' · ')} | Round {s.round}</span>
                    <span className="saved-date">{s.saved_at.replace('_', ' ')}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ── セッション中 ──────────────────────────────────────────
  const nameMap = Object.fromEntries(characters.map(c => [c.id, c.name]))

  return (
    <div className="tab-content session-tab">
      <div className="session-header">
        <span className="session-info">
          Round {round} | {initiative.map(id => nameMap[id] || id).join(' → ')}
        </span>
        <div className="session-header-actions">
          {saveStatus && <span className="save-status">{saveStatus}</span>}
          <button className="save-btn" onClick={saveCurrentSession} title="セッションを保存">💾</button>
          <button className="end-btn" onClick={endSession}>セッション終了</button>
        </div>
      </div>

      <div className="session-stage">
        {/* 立ち絵オーバーレイ */}
        <div className="session-standing">
          {initiative.map((cid, idx) => {
            const n = initiative.length
            const leftPct = n === 1 ? 50 : 10 + (idx / (n - 1)) * 80
            return (
              <img
                key={cid}
                src={standingFallback.has(cid) ? `/api/characters/${cid}/icon` : `/api/characters/${cid}/standing`}
                alt=""
                className={standingFallback.has(cid) ? 'standing-icon-fallback' : ''}
                style={{ left: `${leftPct}%` }}
                onError={e => {
                  if (!standingFallback.has(cid)) {
                    setStandingFallback(prev => new Set([...prev, cid]))
                  } else {
                    e.currentTarget.style.display = 'none'
                  }
                }}
              />
            )
          })}
        </div>

        {/* メッセージ履歴 */}
        <div className="session-messages">
          {messages.map((m, i) => {
            const blocked = !m.isHuman && !m.isRevealed && isContentBlocked(m.tags, allowedSexual, allowedViolence)
            const revealed = m.isRevealed && isContentBlocked(m.tags, allowedSexual, allowedViolence)
            return (
              <div key={i} className={`session-msg ${m.isHuman ? 'human' : ''}`}>
                {!m.isHuman && (
                  <img src={`/api/characters/${m.character_id}/icon`} alt="" className="avatar" />
                )}
                <div
                  className="session-msg-body"
                  style={m.imageColor && !m.isHuman ? { background: m.imageColor + '33', borderLeft: `3px solid ${m.imageColor}` } : undefined}
                >
                  <div className="session-msg-header">
                    <span
                      className="session-msg-name"
                      style={m.imageColor && !m.isHuman ? { color: m.imageColor } : undefined}
                    >
                      {m.character_name}
                      {m.emotion && m.emotion !== 'neutral' && (
                        <span className="emotion"> ({m.emotion})</span>
                      )}
                    </span>
                    {m.audioUrl && (
                      <audio key={m.audioUrl} controls src={m.audioUrl} className="session-msg-audio" />
                    )}
                  </div>
                  {blocked ? (
                    <div className="content-filter-overlay" onClick={() => revealMessage(i)}>
                      <span>🔞 フィルター中 [{m.tags.join(', ')}]</span>
                      <span className="filter-hint">クリックで表示</span>
                    </div>
                  ) : (
                    <>
                      {revealed && (
                        <div className="filter-warning">🔓 フィルター解除中 [{m.tags.join(', ')}]</div>
                      )}
                      <div className="session-msg-text">{m.text}</div>
                    </>
                  )}
                </div>
              </div>
            )
          })}
          {loading && (
            <div className="session-msg">
              <div className="session-msg-body">
                <div className="typing">...</div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      <div className="session-controls">
        <button
          className={`auto-advance-btn ${autoAdvance ? 'active' : ''}`}
          onClick={toggleAutoAdvance}
          title={autoAdvance ? '自動進行を停止' : '自動進行を開始'}
        >
          {autoAdvance ? '⏸ 停止' : '▶▶ 自動'}
        </button>
        <input
          type="text"
          value={humanInput}
          onChange={e => setHumanInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && sendHuman()}
          placeholder="発言する..."
        />
        <button onClick={sendHuman}>送信</button>
        <button onClick={retakeTurn} disabled={loading || autoAdvance} className="retake-btn" title="現在のターンをやり直す">↩ リテイク</button>
        <button onClick={() => nextTurn(undefined, actionsPerTurn)} disabled={loading || autoAdvance} className="next-btn">▶ 次の発言</button>
      </div>
    </div>
  )
}
