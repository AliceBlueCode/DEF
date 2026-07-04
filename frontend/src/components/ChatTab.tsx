import { useState, useEffect, useRef } from 'react'

type Character = { id: string; name: string }
type Message = {
  role: 'user' | 'assistant'
  content: string
  emotion?: string
  audioUrl?: string
  imageUrl?: string
  imageStatus?: 'generating' | 'error'
  imageError?: string
}

type Props = {
  characters: Character[]
  selectedChar: string
  onCharChange: (id: string) => void
  backend: string
  ttsBackend: string
  t2iBackend: string
}

export default function ChatTab({ characters, selectedChar, onCharChange, backend, ttsBackend, t2iBackend }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [ttsEnabled, setTtsEnabled] = useState(true)
  const chatEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch('/api/settings/')
      .then(r => r.json())
      .then(data => {
        const s = data.settings || {}
        if ('tts_enabled' in s) setTtsEnabled(!!s.tts_enabled)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    setMessages([])
  }, [selectedChar])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const playTTS = async (text: string, index: number): Promise<string | null> => {
    try {
      const res = await fetch('/api/tts/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, character_id: selectedChar, backend: ttsBackend }),
      })
      if (!res.ok) return null
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      setMessages(prev =>
        prev.map((m, i) => (i === index ? { ...m, audioUrl: url } : m))
      )
      return url
    } catch (e) {
      console.error('TTS error:', e)
      return null
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
      const contentType = res.headers.get('content-type') || ''
      if (contentType.includes('application/json')) {
        const data = await res.json()
        const msg = data.error || 'T2I生成失敗'
        setMessages(prev => prev.map((m, i) => i === index ? { ...m, imageStatus: 'error', imageError: msg } : m))
        return
      }
      if (!res.ok) {
        setMessages(prev => prev.map((m, i) => i === index ? { ...m, imageStatus: 'error', imageError: `HTTP ${res.status}` } : m))
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      setMessages(prev => prev.map((m, i) => i === index ? { ...m, imageUrl: url, imageStatus: undefined } : m))
    } catch (e) {
      setMessages(prev => prev.map((m, i) => i === index ? { ...m, imageStatus: 'error', imageError: String(e) } : m))
    }
  }

  const sendMessage = async () => {
    if (!input.trim() || loading) return
    const userMsg: Message = { role: 'user', content: input }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)

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
        role: 'assistant',
        content: data.text || '(no response)',
        emotion: data.emotion,
      }
      const assistantIdx = messages.length + 1
      setMessages(prev => [...prev, assistantMsg])
      if (ttsEnabled && data.text) {
        playTTS(data.text, assistantIdx)
      }
      if (data.image_prompt_en && t2iBackend) {
        generateImage(data.image_prompt_en, assistantIdx)
      }
    } catch (e) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${e}` }])
    } finally {
      setLoading(false)
    }
  }

  const charName = characters.find(c => c.id === selectedChar)?.name || ''
  const iconUrl = selectedChar ? `/api/characters/${selectedChar}/icon` : ''

  return (
    <div className="tab-content chat-tab">
      <div className="chat-char-bar">
        <select value={selectedChar} onChange={e => onCharChange(e.target.value)}>
          {characters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      <div className="chat-area">
        {messages.map((m, i) => (
          <div key={i} className={`message ${m.role}`}>
            {m.role === 'assistant' && iconUrl && (
              <img src={iconUrl} alt="" className="avatar" />
            )}
            <div className="message-body">
              <div className="message-sender">
                {m.role === 'user' ? 'You' : charName}
                {m.emotion && m.emotion !== 'neutral' && (
                  <span className="emotion"> ({m.emotion})</span>
                )}
              </div>
              <div className="message-text">{m.content}</div>
              {m.imageStatus === 'generating' && (
                <div className="t2i-status">🎨 生成中...</div>
              )}
              {m.imageStatus === 'error' && (
                <div className="t2i-status t2i-error">⚠ {m.imageError}</div>
              )}
              {m.imageUrl && (
                <img src={m.imageUrl} alt="" className="generated-image" />
              )}
              {m.role === 'assistant' && (
                <div className="message-actions">
                  {m.audioUrl
                    ? <audio key={m.audioUrl} controls autoPlay src={m.audioUrl} className="audio-player" />
                    : <button className="tts-btn" onClick={() => playTTS(m.content, i)}>🔊</button>
                  }
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

      <div className="input-area">
        <input
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
