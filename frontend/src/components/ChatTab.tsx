import { useState, useEffect, useRef } from 'react'

type Character = { id: string; name: string }

type MessageSnapshot = {
  content: string
  emotion?: string
  audioUrl?: string
  imageUrl?: string
  imageStatus?: 'generating' | 'error'
  imageError?: string
  imagePromptEn?: string
  tags?: string[]
}

type Message = MessageSnapshot & {
  id?: string
  role: 'user' | 'assistant'
  undoStack?: MessageSnapshot[]
  redoStack?: MessageSnapshot[]
  isRevealed?: boolean
  autoPlayAudio?: boolean
}

const SEXUAL_TAGS = ['sfw', 'nsfw', 'hentai']
const VIOLENCE_TAGS = ['violence', 'gore', 'extreme']

function isContentBlocked(tags: string[], allowedSexual: string[], allowedViolence: string[]): boolean {
  return tags.some(tag =>
    (SEXUAL_TAGS.includes(tag) && !allowedSexual.includes(tag)) ||
    (VIOLENCE_TAGS.includes(tag) && !allowedViolence.includes(tag))
  )
}

type Props = {
  characters: Character[]
  selectedChar: string
  backend: string
  ttsBackend: string
  t2iBackend: string
  reloadTrigger?: number
}

export default function ChatTab({ characters, selectedChar, backend, ttsBackend, t2iBackend, reloadTrigger }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [ttsEnabled, setTtsEnabled] = useState(true)
  const [ttsHumanEnabled, setTtsHumanEnabled] = useState(false)
  const ttsHumanEnabledRef = useRef(false)
  const [undoMax, setUndoMax] = useState(5)
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [allowedSexual, setAllowedSexual] = useState<string[]>(['general'])
  const [allowedViolence, setAllowedViolence] = useState<string[]>(['general'])
  const [charColor, setCharColor] = useState('')
  const [userColor, setUserColor] = useState('#F0F8FF')
  const chatEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const characterGreetingRef = useRef(true)
  const isFirstMount = useRef(true)
  const prevCharIdRef = useRef('')
  const messagesRef = useRef<Message[]>([])

  useEffect(() => { messagesRef.current = messages }, [messages])

  const [standingVisible, setStandingVisible] = useState(true)

  useEffect(() => {
    fetch('/api/characters/character_i_001/raw-profile')
      .then(r => r.json())
      .then(data => { if (data.profile?.image_color) setUserColor(data.profile.image_color) })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (!selectedChar) { setCharColor(''); return }
    fetch(`/api/characters/${selectedChar}/raw-profile`)
      .then(r => r.json())
      .then(data => setCharColor((data.profile?.image_color as string) || ''))
      .catch(() => setCharColor(''))
    setStandingVisible(true)
  }, [selectedChar])

  useEffect(() => {
    if (reloadTrigger === undefined || reloadTrigger === 0) return
    setMessages([])
  }, [reloadTrigger])

  const saveHistory = (charId: string, msgs: Message[]) => {
    if (!charId || msgs.length === 0) return
    const payload = msgs.map(m => ({
      id: m.id || crypto.randomUUID(),
      role: m.role,
      content: m.content,
      emotion: m.emotion || 'neutral',
      image_prompt_en: m.imagePromptEn || '',
      image_url: m.imageUrl && !m.imageUrl.startsWith('blob:') ? m.imageUrl : undefined,
      audio_url: m.audioUrl && !m.audioUrl.startsWith('blob:') ? m.audioUrl : undefined,
      tags: m.tags || [],
      state: 'Persist',
    }))
    fetch(`/api/chat/history/${charId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: payload }),
    }).catch(() => {})
  }

  const fromHistory = (raw: Record<string, unknown>[]): Message[] =>
    raw
      .filter(m => m.role === 'user' || m.role === 'assistant')
      .map(m => ({
        id: m.id as string,
        role: m.role as 'user' | 'assistant',
        content: (m.content as string) || '',
        emotion: m.emotion as string | undefined,
        imagePromptEn: (m.image_prompt_en as string) || '',
        imageUrl: (m.image_url as string) || undefined,
        audioUrl: (m.audio_url as string) || undefined,
        tags: (m.tags as string[]) || [],
      }))

  useEffect(() => {
    fetch('/api/settings/')
      .then(r => r.json())
      .then(data => {
        const s = data.settings || {}
        if ('tts_enabled' in s) setTtsEnabled(!!s.tts_enabled)
        if ('tts_human_enabled' in s) { setTtsHumanEnabled(!!s.tts_human_enabled); ttsHumanEnabledRef.current = !!s.tts_human_enabled }
        if ('undo_max_history' in s) setUndoMax(Number(s.undo_max_history) || 5)
        if (s.allowed_rating_sexual) setAllowedSexual(s.allowed_rating_sexual)
        if (s.allowed_rating_violence) setAllowedViolence(s.allowed_rating_violence)
        if ('character_greeting' in s) characterGreetingRef.current = !!s.character_greeting
      })
      .catch(() => {})

    const onSettingsChange = (e: Event) => {
      const { key, value } = (e as CustomEvent).detail
      if (key === 'tts_enabled') setTtsEnabled(!!value)
      if (key === 'tts_human_enabled') { setTtsHumanEnabled(!!value); ttsHumanEnabledRef.current = !!value }
      if (key === 'character_greeting') characterGreetingRef.current = !!value
    }
    window.addEventListener('def-settings-change', onSettingsChange)
    return () => window.removeEventListener('def-settings-change', onSettingsChange)
  }, [])

  useEffect(() => {
    const prevCharId = prevCharIdRef.current
    prevCharIdRef.current = selectedChar
    const wasFirstMount = isFirstMount.current
    isFirstMount.current = false
    setMessages([])
    if (!selectedChar) return

    fetch(`/api/chat/history/${selectedChar}?tail=20`)
      .then(r => r.json())
      .then(data => {
        setHasMore(!!data.has_more)
        const loaded = fromHistory(data.messages || [])
        if (loaded.length > 0) {
          setMessages(loaded)
          return
        }
        if (wasFirstMount || !characterGreetingRef.current) return
        // 履歴なし + キャラ切り替え → 挨拶
        const charNameNew = characters.find(c => c.id === selectedChar)?.name || selectedChar
        const charNamePrev = characters.find(c => c.id === prevCharId)?.name || prevCharId
        const announcement: Message = {
          id: crypto.randomUUID(),
          role: 'user',
          content: `（キャラクターが${charNamePrev}から${charNameNew}に切り替わりました）`,
        }
        setMessages([announcement])
        setLoading(true)
        fetch('/api/chat/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: `こんにちは、${charNameNew}。調子はどう？`,
            character_id: selectedChar,
            backend,
            history: [],
          }),
        })
          .then(r => r.json())
          .then(data => {
            const greetMsg: Message = {
              id: crypto.randomUUID(),
              role: 'assistant',
              content: data.text || '(no response)',
              emotion: data.emotion,
              imagePromptEn: data.image_prompt_en || '',
              tags: data.tags || [],
            }
            const greetMsgs = [announcement, greetMsg]
            setMessages(greetMsgs)
            saveHistory(selectedChar, greetMsgs)
            if (ttsEnabled && data.text) playTTS(data.text, 1)
            if (data.image_prompt_en && t2iBackend) generateImage(data.image_prompt_en, 1)
          })
          .catch(() => {})
          .finally(() => setLoading(false))
      })
      .catch(() => {})
  }, [selectedChar])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') setTimeout(() => inputRef.current?.focus(), 250)
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => document.removeEventListener('visibilitychange', onVisible)
  }, [])

  const loadMore = async () => {
    if (loadingMore || !hasMore) return
    setLoadingMore(true)
    try {
      const loadedIds = messagesRef.current.map(m => m.id).filter(Boolean) as string[]
      const res = await fetch(`/api/chat/history/${selectedChar}/load-more`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ loaded_ids: loadedIds, batch: 20 }),
      })
      const data = await res.json()
      const older = fromHistory(data.messages || [])
      if (older.length > 0) {
        setMessages(prev => [...older, ...prev])
      }
      setHasMore(!!data.has_more)
    } catch (e) {
      console.error('load more error:', e)
    } finally {
      setLoadingMore(false)
    }
  }

  const playTTS = async (text: string, index: number): Promise<string | null> => {
    try {
      const res = await fetch('/api/tts/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, character_id: selectedChar, backend: ttsBackend }),
      })
      if (!res.ok) return null
      const blob = await res.blob()
      const form = new FormData()
      form.append('file', blob, 'audio.wav')
      const saveRes = await fetch('/api/tts/save', { method: 'POST', body: form })
      const saveData = await saveRes.json()
      const url: string = saveData.url
      setMessages(prev =>
        prev.map((m, i) => (i === index ? { ...m, audioUrl: url, autoPlayAudio: true } : m))
      )
      return url
    } catch (e) {
      console.error('TTS error:', e)
      return null
    }
  }

  const playUserTTS = async (text: string, index: number): Promise<void> => {
    try {
      const res = await fetch('/api/tts/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, character_id: 'character_i_001', backend: ttsBackend }),
      })
      if (!res.ok) return
      const blob = await res.blob()
      const form = new FormData()
      form.append('file', blob, 'audio.wav')
      const saveRes = await fetch('/api/tts/save', { method: 'POST', body: form })
      const saveData = await saveRes.json()
      const url: string = saveData.url
      setMessages(prev => prev.map((m, i) => (i === index ? { ...m, audioUrl: url, autoPlayAudio: true } : m)))
    } catch (e) {
      console.error('User TTS error:', e)
    }
  }

  const generateImage = async (prompt: string, index: number) => {
    if (!t2iBackend) return
    setMessages(prev => prev.map((m, i) => i === index ? { ...m, imageStatus: 'generating' } : m))
    try {
      const res = await fetch('/api/t2i/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, backend: t2iBackend }),
      })
      const data = await res.json()
      if (data.error) {
        setMessages(prev => prev.map((m, i) => i === index ? { ...m, imageStatus: 'error', imageError: data.error } : m))
        return
      }
      const updatedMsgs = messagesRef.current.map((m, i) =>
        i === index ? { ...m, imageUrl: data.url, imageStatus: undefined } : m
      )
      setMessages(updatedMsgs)
      saveHistory(selectedChar, updatedMsgs)
    } catch (e) {
      setMessages(prev => prev.map((m, i) => i === index ? { ...m, imageStatus: 'error', imageError: String(e) } : m))
    }
  }

  const sendMessage = async () => {
    if (!input.trim() || loading) return
    const userMsg: Message = { id: crypto.randomUUID(), role: 'user', content: input }
    const userIdx = messages.length
    const msgsWithUser = [...messages, userMsg]
    setMessages(msgsWithUser)
    setInput('')
    setLoading(true)
    if (ttsHumanEnabledRef.current) playUserTTS(input, userIdx)

    try {
      const res = await fetch('/api/chat/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: input,
          character_id: selectedChar,
          backend,
          history: messages.map(m => ({ role: m.role, content: m.content })),
        }),
      })
      const data = await res.json()
      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: data.text || '(no response)',
        emotion: data.emotion,
        imagePromptEn: data.image_prompt_en || '',
        tags: data.tags || [],
      }
      const assistantIdx = msgsWithUser.length
      // messagesRef.current を使うことで playUserTTS が設定した audioUrl を保持する
      const finalMsgs = [...messagesRef.current, assistantMsg]
      setMessages(finalMsgs)
      saveHistory(selectedChar, finalMsgs)
      if (ttsEnabled && data.text) playTTS(data.text, assistantIdx)
      if (data.image_prompt_en && t2iBackend) generateImage(data.image_prompt_en, assistantIdx)
    } catch (e) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${e}` }])
    } finally {
      setLoading(false)
    }
  }

  const snapshotMsg = (m: Message): MessageSnapshot => ({
    content: m.content,
    emotion: m.emotion,
    audioUrl: m.audioUrl,
    imageUrl: m.imageUrl,
    imageStatus: m.imageStatus,
    imageError: m.imageError,
    imagePromptEn: m.imagePromptEn,
  })

  const pushUndo = (prev: Message[], idx: number): Message[] => {
    return prev.map((m, i) => {
      if (i !== idx) return m
      const snap = snapshotMsg(m)
      const stack = [...(m.undoStack || []), snap]
      return { ...m, undoStack: stack.slice(-undoMax), redoStack: [] }
    })
  }

  const undoTurn = (idx: number) => {
    setMessages(prev => prev.map((m, i) => {
      if (i !== idx || !m.undoStack?.length) return m
      const stack = [...m.undoStack]
      const snap = stack.pop()!
      const redoStack = [...(m.redoStack || []), snapshotMsg(m)]
      return { ...m, ...snap, undoStack: stack, redoStack }
    }))
  }

  const redoTurn = (idx: number) => {
    setMessages(prev => prev.map((m, i) => {
      if (i !== idx || !m.redoStack?.length) return m
      const rstack = [...m.redoStack]
      const snap = rstack.pop()!
      const undoStack = [...(m.undoStack || []), snapshotMsg(m)]
      return { ...m, ...snap, undoStack: undoStack.slice(-undoMax), redoStack: rstack }
    }))
  }

  const deleteTurn = (assistantIdx: number) => {
    const next = [...messagesRef.current]
    const userIdx = assistantIdx - 1
    if (userIdx >= 0 && next[userIdx]?.role === 'user') {
      next.splice(userIdx, 2)
    } else {
      next.splice(assistantIdx, 1)
    }
    setMessages(next)
    saveHistory(selectedChar, next)
  }

  const regenTurn = async (assistantIdx: number) => {
    const userMsg = messages[assistantIdx - 1]
    console.log('[regenTurn] idx=', assistantIdx, 'userMsg=', userMsg)
    if (!userMsg || userMsg.role !== 'user') {
      console.warn('[regenTurn] abort: no user message at idx', assistantIdx - 1)
      return
    }
    setLoading(true)
    setMessages(prev => {
      const withUndo = pushUndo(prev, assistantIdx)
      return withUndo.map((m, i) =>
        i === assistantIdx ? { ...m, content: '...', audioUrl: undefined, imageUrl: undefined, imageStatus: undefined, imageError: undefined } : m
      )
    })
    try {
      const history = messages
        .slice(0, assistantIdx - 1)
        .map(m => ({ role: m.role, content: m.content }))
      console.log('[regenTurn] POST /api/chat/ message=', userMsg.content, 'history=', history)
      const res = await fetch('/api/chat/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: userMsg.content,
          character_id: selectedChar,
          backend,
          history,
        }),
      })
      const data = await res.json()
      console.log('[regenTurn] response=', data)
      const updated: Partial<Message> = {
        content: data.text || '(no response)',
        emotion: data.emotion,
        imagePromptEn: data.image_prompt_en || '',
        tags: data.tags || [],
        isRevealed: false,
      }
      const finalMsgs = messagesRef.current.map((m, i) =>
        i === assistantIdx ? { ...m, ...updated } : m
      )
      setMessages(finalMsgs)
      saveHistory(selectedChar, finalMsgs)
      if (ttsEnabled && data.text) playTTS(data.text, assistantIdx)
      if (data.image_prompt_en && t2iBackend) generateImage(data.image_prompt_en, assistantIdx)
    } catch (e) {
      setMessages(prev => prev.map((m, i) =>
        i === assistantIdx
          ? { ...m, content: `Error: ${e}`, audioUrl: undefined, imageUrl: undefined, imageStatus: undefined }
          : m
      ))
    } finally {
      setLoading(false)
    }
  }

  const regenImage = (m: Message, i: number) => {
    if (!m.imagePromptEn) return
    setMessages(prev => pushUndo(prev, i))
    generateImage(m.imagePromptEn, i)
  }

  const charName = characters.find(c => c.id === selectedChar)?.name || ''
  const iconUrl = selectedChar ? `/api/characters/${selectedChar}/icon` : ''

  const standingUrl = selectedChar ? `/api/characters/${selectedChar}/standing` : ''

  return (
    <div className="tab-content chat-tab">
      <div className="chat-body">
        {standingVisible && standingUrl && (
          <img
            src={standingUrl}
            alt=""
            className="chat-standing"
            onError={() => setStandingVisible(false)}
          />
        )}
      <div className="chat-area">
        {hasMore && (
          <div className="load-more-wrap">
            <button className="load-more-btn" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? '読み込み中...' : '▲ 過去ログを読み込む'}
            </button>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`message ${m.role}`}>
            {m.role === 'assistant' && iconUrl && (
              <img src={iconUrl} alt="" className="avatar" />
            )}
            <div className="message-body" style={
              m.role === 'assistant' && charColor
                ? { background: charColor + '33', borderLeft: `3px solid ${charColor}` }
                : m.role === 'user'
                  ? { background: userColor + '33', borderRight: `3px solid ${userColor}`, minWidth: '200px' }
                  : undefined
            }>
              <div className="message-header">
                <div
                  className="message-sender"
                  style={
                    m.role === 'assistant' && charColor ? { color: charColor }
                    : m.role === 'user' ? { color: userColor }
                    : undefined
                  }
                >
                  {m.role === 'user' ? 'あなた' : charName}
                  {m.emotion && m.emotion !== 'neutral' && (
                    <span className="emotion"> ({m.emotion})</span>
                  )}
                </div>
                {m.audioUrl && (
                  <audio key={m.audioUrl} controls autoPlay={!!m.autoPlayAudio} src={m.audioUrl} className="chat-msg-audio" />
                )}
              </div>
              {(() => {
                const blocked = m.role === 'assistant' && !m.isRevealed && !!m.tags && isContentBlocked(m.tags, allowedSexual, allowedViolence)
                if (blocked) {
                  return (
                    <div className="content-blocked">
                      <span>🔞 フィルター中 [{m.tags!.join(', ')}]</span>
                      <button className="turn-btn" onClick={() => setMessages(prev => prev.map((msg, j) => j === i ? { ...msg, isRevealed: true } : msg))}>表示する</button>
                    </div>
                  )
                }
                return (
                  <>
                    {m.role === 'assistant' && m.isRevealed && !!m.tags && isContentBlocked(m.tags, allowedSexual, allowedViolence) && (
                      <div className="content-revealed">
                        <span>🔓 フィルター解除中 [{m.tags.join(', ')}]</span>
                        <button className="turn-btn" onClick={() => setMessages(prev => prev.map((msg, j) => j === i ? { ...msg, isRevealed: false } : msg))}>隠す</button>
                      </div>
                    )}
                    <div className="message-text">{m.content}</div>
                    {/* T2I 画像 */}
                    {m.imageStatus === 'generating' && (
                      <div className="t2i-status">🎨 生成中...</div>
                    )}
                    {m.imageStatus === 'error' && (
                      <div className="t2i-status t2i-error">⚠ {m.imageError}</div>
                    )}
                    {m.imageUrl && (
                      <img
                        src={m.imageUrl}
                        alt=""
                        className="generated-image"
                        onDoubleClick={() => window.open(m.imageUrl, '_blank')}
                        style={{ cursor: 'zoom-in' }}
                      />
                    )}
                  </>
                )
              })()}
              {m.role === 'assistant' && (
                <div className="message-actions">
                  {!m.audioUrl && (
                    <button className="tts-btn" onClick={() => playTTS(m.content, i)}>🔊</button>
                  )}
                  <div className="turn-actions">
                    <button className="turn-btn" onClick={() => regenTurn(i)} disabled={loading} title="サイクル再生成">🔄 サイクル再生成</button>
                    <button className="turn-btn" onClick={() => playTTS(m.content, i)} title="音声を再生成">🔊 再生成</button>
                    {m.imagePromptEn && (
                      <button className="turn-btn" onClick={() => regenImage(m, i)} title="イラストを再生成">🖼 再生成</button>
                    )}
                    {(m.undoStack?.length ?? 0) > 0 && (
                      <button className="turn-btn" onClick={() => undoTurn(i)} title="元に戻す">
                        ↩️ 元に戻す ({m.undoStack!.length})
                      </button>
                    )}
                    {(m.redoStack?.length ?? 0) > 0 && (
                      <button className="turn-btn" onClick={() => redoTurn(i)} title="やり直す">
                        ↪️ やり直す ({m.redoStack!.length})
                      </button>
                    )}
                    <button className="turn-btn turn-btn-delete" onClick={() => deleteTurn(i)} title="このサイクルを削除">🗑</button>
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="message assistant">
            {iconUrl && <img src={iconUrl} alt="" className="avatar" />}
            <div className="message-body"><div className="message-text typing">...</div></div>
          </div>
        )}
        <div ref={chatEndRef} />
      </div>
      </div>

      <div className="input-area">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && sendMessage()}
          placeholder="メッセージを入力..."
          disabled={loading}
        />
        <button onClick={sendMessage} disabled={loading}>送信</button>
      </div>
    </div>
  )
}
