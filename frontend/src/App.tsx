import { useState, useEffect } from 'react'
import ChatTab from './components/ChatTab'
import CharacterTab from './components/CharacterTab'
import SessionTab from './components/SessionTab'
import EpisodeTab from './components/EpisodeTab'
import SettingsTab from './components/SettingsTab'
import './App.css'

type Character = { id: string; name: string }
type BackendInfo = {
  backends: string[]
  labels: Record<string, string>
  default: string
}

type TabId = 'character' | 'chat' | 'session' | 'episode' | 'settings'

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: 'character', label: 'キャラクター', icon: '👤' },
  { id: 'chat', label: 'チャット', icon: '💬' },
  { id: 'session', label: 'セッション', icon: '🎭' },
  { id: 'episode', label: 'エピソード', icon: '📖' },
  { id: 'settings', label: '設定', icon: '⚙️' },
]

function App() {
  const [characters, setCharacters] = useState<Character[]>([])
  const [selectedChar, setSelectedChar] = useState('')
  const [llmBackends, setLlmBackends] = useState<BackendInfo | null>(null)
  const [selectedBackend, setSelectedBackend] = useState('')
  const [activeTab, setActiveTab] = useState<TabId>('chat')

  useEffect(() => {
    fetch('/api/characters/')
      .then(r => r.json())
      .then(data => {
        setCharacters(data.characters || [])
        if (data.characters?.length > 0) setSelectedChar(data.characters[0].id)
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

  return (
    <div className="app">
      <header className="header">
        <h1>DEF(kari)</h1>
        <select value={selectedChar} onChange={e => setSelectedChar(e.target.value)}>
          {characters.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        {llmBackends && (
          <span className="backend-label">
            {llmBackends.labels[selectedBackend] || selectedBackend}
          </span>
        )}
      </header>

      <div className="tabs">
        {TABS.map(tab => (
          <button
            key={tab.id}
            className={`tab ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'chat' && (
        <ChatTab characters={characters} selectedChar={selectedChar} backend={selectedBackend} />
      )}
      {activeTab === 'character' && (
        <CharacterTab selectedChar={selectedChar} />
      )}
      {activeTab === 'session' && (
        <SessionTab characters={characters} backend={selectedBackend} />
      )}
      {activeTab === 'episode' && (
        <EpisodeTab backend={selectedBackend} />
      )}
      {activeTab === 'settings' && (
        <SettingsTab llmBackend={selectedBackend} onLlmBackendChange={setSelectedBackend} />
      )}
    </div>
  )
}

export default App
