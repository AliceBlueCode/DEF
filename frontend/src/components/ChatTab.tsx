import { useState, useEffect, useRef } from 'react'

type Character = { id: string; name: string }
type Message = {
  role: 'user' | 'assistant'
  content: string
  emotion?: string
  audioUrl?: string
}

type Props = {
  characters: Character[]
  selectedChar: string
  backend: string
}

export default function ChatTab({ characters, selectedChar, backend }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setMessages([])
  }, [selectedChar])

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
          backend,
          history: messages.map(m => ({ role: m.role, content: m.content })),
        }),
      })
      const data = await res.json()
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.text || '(no response)',
        emotion: data.emotion,
      }])
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
        body: JSON.stringify({ text, character_id: selectedChar }),
      })
      if (!res.ok) return
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      setMessages(prev =>
        prev.map((m, i) => (i === index ? { ...m, audioUrl: url } : m))
      )
      new Audio(url).play()
    } catch (e) {
      console.error('TTS error:', e)
    }
  }

  const charName = characters.find(c => c.id === selectedChar)?.name || ''
  const iconUrl = selectedChar ? `/api/characters/${selectedChar}/icon` : ''

  return (
    <div className="tab-content chat-tab">
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
                  <button className="tts-btn" onClick={() => playTTS(m.content, i)}>🔊</button>
                  {m.audioUrl && <audio controls src={m.audioUrl} className="audio-player" />}
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
