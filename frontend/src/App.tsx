import { useState, useEffect, useRef } from 'react'
import './App.css'

type Character = { id: string; name: string }
type Message = {
  role: 'user' | 'assistant'
  content: string
  emotion?: string
  audioUrl?: string
}
type BackendInfo = {
  backends: string[]
  labels: Record<string, string>
  default: string
}

function App() {
  const [characters, setCharacters] = useState<Character[]>([])
  const [selectedChar, setSelectedChar] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [llmBackends, setLlmBackends] = useState<BackendInfo | null>(null)
  const [selectedBackend, setSelectedBackend] = useState('')
  const chatEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch('/api/characters/')
      .then(r => r.json())
      .then(data => {
        setCharacters(data.characters || [])
        if (data.characters?.length > 0) {
          setSelectedChar(data.characters[0].id)
        }
      })
    fetch('/api/settings/backends')
      .then(r => r.json())
      .then(data => {
        if (data.llm) {
          setLlmBackends(data.llm)
          setSelectedBackend(data.llm.default)
        }
      })
  }, [])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

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
          backend: selectedBackend,
          history: messages.map(m => ({ role: m.role, content: m.content })),
        }),
      })
      const data = await res.json()
      const assistantMsg: Message = {
        role: 'assistant',
        content: data.text || '(no response)',
        emotion: data.emotion,
      }
      setMessages(prev => [...prev, assistantMsg])
    } catch (e) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${e}` }])
    } finally {
      setLoading(false)
    }
  }

  const playTTS = async (text: string, index: number) => {
    try {
      const res = await fetch('/api/tts/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          character_id: selectedChar,
        }),
      })
      if (!res.ok) return
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      setMessages(prev =>
        prev.map((m, i) => (i === index ? { ...m, audioUrl: url } : m))
      )
      const audio = new Audio(url)
      audio.play()
    } catch (e) {
      console.error('TTS error:', e)
    }
  }

  const charName = characters.find(c => c.id === selectedChar)?.name || ''
  const iconUrl = selectedChar ? `/api/characters/${selectedChar}/icon` : ''

  return (
    <div className="app">
      <header className="header">
        <h1>DEF(kari)</h1>
        <select
          value={selectedChar}
          onChange={e => {
            setSelectedChar(e.target.value)
            setMessages([])
          }}
        >
          {characters.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        {llmBackends && (
          <select
            value={selectedBackend}
            onChange={e => setSelectedBackend(e.target.value)}
            className="backend-select"
          >
            {llmBackends.backends.map(b => (
              <option key={b} value={b}>{llmBackends.labels[b] || b}</option>
            ))}
          </select>
        )}
      </header>

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
              {m.role === 'assistant' && (
                <div className="message-actions">
                  <button className="tts-btn" onClick={() => playTTS(m.content, i)}>
                    🔊
                  </button>
                  {m.audioUrl && (
                    <audio controls src={m.audioUrl} className="audio-player" />
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="message assistant">
            {iconUrl && <img src={iconUrl} alt="" className="avatar" />}
            <div className="message-body">
              <div className="message-text typing">...</div>
            </div>
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

export default App
