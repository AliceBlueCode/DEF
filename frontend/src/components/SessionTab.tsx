import { useState } from 'react'

type Character = { id: string; name: string }

type SessionMessage = {
  character_id: string
  character_name: string
  text: string
  emotion: string
  isHuman?: boolean
}

type Props = {
  characters: Character[]
  backend: string
}

export default function SessionTab({ characters, backend }: Props) {
  const [selectedChars, setSelectedChars] = useState<string[]>([])
  const [topic, setTopic] = useState('')
  const [sessionId, setSessionId] = useState('')
  const [messages, setMessages] = useState<SessionMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [round, setRound] = useState(1)
  const [humanInput, setHumanInput] = useState('')
  const [initiative, setInitiative] = useState<string[]>([])

  const toggleChar = (id: string) => {
    setSelectedChars(prev =>
      prev.includes(id) ? prev.filter(c => c !== id) : [...prev, id]
    )
  }

  const startSession = async () => {
    if (selectedChars.length < 1) return
    setLoading(true)
    try {
      const res = await fetch('/api/session/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          character_ids: selectedChars,
          topic,
          backend,
        }),
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

  const nextTurn = async () => {
    if (!sessionId) return
    setLoading(true)
    try {
      const res = await fetch('/api/session/next', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, backend }),
      })
      const data = await res.json()
      if (data.error) {
        console.error(data.error)
        return
      }
      setMessages(prev => [...prev, {
        character_id: data.character_id,
        character_name: data.character_name,
        text: data.text,
        emotion: data.emotion,
      }])
      setRound(data.round)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
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
      isHuman: true,
    }])
    setHumanInput('')
  }

  const endSession = () => {
    setSessionId('')
    setMessages([])
    setInitiative([])
    setRound(1)
  }

  if (!sessionId) {
    return (
      <div className="tab-content session-tab">
        <h2>セッション</h2>
        <div className="session-setup">
          <div className="session-topic">
            <h3>トピック</h3>
            <input
              type="text"
              value={topic}
              onChange={e => setTopic(e.target.value)}
              placeholder="例: 思想ではなく個人的な体験を語れ"
            />
          </div>
          <div className="session-chars">
            <h3>参加キャラクター</h3>
            <div className="char-grid">
              {characters.map(c => (
                <label key={c.id} className={`char-chip ${selectedChars.includes(c.id) ? 'selected' : ''}`}>
                  <input
                    type="checkbox"
                    checked={selectedChars.includes(c.id)}
                    onChange={() => toggleChar(c.id)}
                  />
                  <img src={`/api/characters/${c.id}/icon`} alt="" className="chip-icon" />
                  {c.name}
                </label>
              ))}
            </div>
          </div>
          <button className="start-btn" onClick={startSession} disabled={selectedChars.length < 1 || loading}>
            セッション開始
          </button>
        </div>
      </div>
    )
  }

  const nameMap = Object.fromEntries(characters.map(c => [c.id, c.name]))

  return (
    <div className="tab-content session-tab">
      <div className="session-header">
        <span className="session-info">
          Round {round} | {initiative.map(id => nameMap[id] || id).join(' → ')}
        </span>
        <button className="end-btn" onClick={endSession}>セッション終了</button>
      </div>

      <div className="session-messages">
        {messages.map((m, i) => (
          <div key={i} className={`session-msg ${m.isHuman ? 'human' : ''}`}>
            {!m.isHuman && (
              <img src={`/api/characters/${m.character_id}/icon`} alt="" className="avatar" />
            )}
            <div className="session-msg-body">
              <span className="session-msg-name">
                {m.character_name}
                {m.emotion && m.emotion !== 'neutral' && (
                  <span className="emotion"> ({m.emotion})</span>
                )}
              </span>
              <div className="session-msg-text">{m.text}</div>
            </div>
          </div>
        ))}
        {loading && <div className="session-msg"><div className="session-msg-body"><div className="typing">...</div></div></div>}
      </div>

      <div className="session-controls">
        <input
          type="text"
          value={humanInput}
          onChange={e => setHumanInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && sendHuman()}
          placeholder="発言する..."
        />
        <button onClick={sendHuman}>送信</button>
        <button onClick={nextTurn} disabled={loading} className="next-btn">▶ 次の発言</button>
      </div>
    </div>
  )
}
