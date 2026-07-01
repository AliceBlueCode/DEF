import { useState, useEffect } from 'react'
import ChatTab from './components/ChatTab'
import CharacterTab from './components/CharacterTab'
import SessionTab from './components/SessionTab'
import EpisodeTab from './components/EpisodeTab'
import SettingsTab from './components/SettingsTab'
import DebugTab from './components/DebugTab'
import Sidebar from './components/Sidebar'
import './App.css'

type Character = { id: string; name: string }
type BackendInfo = {
  backends: string[]
  labels: Record<string, string>
  default: string
}

type TabId = 'character' | 'chat' | 'session' | 'episode' | 'settings' | 'debug'

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: 'character', label: 'キャラクター', icon: '👤' },
  { id: 'chat', label: 'チャット', icon: '💬' },
  { id: 'session', label: 'セッション', icon: '🎭' },
  { id: 'episode', label: 'エピソード', icon: '📖' },
  { id: 'settings', label: '設定', icon: '⚙️' },
  { id: 'debug', label: 'デバッグ', icon: '🐛' },
]

const LS_KEY_LLM = 'def_llm_backend'
const LS_KEY_T2I = 'def_t2i_backend'
const LS_KEY_TTS = 'def_tts_backend'
const LS_KEY_CANDIDATES = 'def_candidate_count'
const LS_KEY_THEME = 'def_theme'

function App() {
  const [characters, setCharacters] = useState<Character[]>([])
  const [selectedChar, setSelectedChar] = useState('')
  const [llmBackends, setLlmBackends] = useState<BackendInfo | null>(null)
  const [selectedBackend, setSelectedBackend] = useState(() => localStorage.getItem(LS_KEY_LLM) || '')
  const [selectedT2iBackend, setSelectedT2iBackend] = useState(() => localStorage.getItem(LS_KEY_T2I) || '')
  const [selectedTtsBackend, setSelectedTtsBackend] = useState(() => localStorage.getItem(LS_KEY_TTS) || 'voicevox')
  const [candidateCount, setCandidateCount] = useState(() => Number(localStorage.getItem(LS_KEY_CANDIDATES)) || 3)
  const [activeTab, setActiveTab] = useState<TabId>('chat')
  const [theme, setTheme] = useState<'dark' | 'light'>(() =>
    (localStorage.getItem(LS_KEY_THEME) as 'dark' | 'light') || 'dark'
  )

  const toggleTheme = () => {
    setTheme(prev => {
      const next = prev === 'dark' ? 'light' : 'dark'
      localStorage.setItem(LS_KEY_THEME, next)
      return next
    })
  }

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
          setSelectedBackend(prev => prev || data.llm.default)
        }
        if (data.t2i) {
          setSelectedT2iBackend(prev => prev || data.t2i.default)
        }
      })
  }, [])

  useEffect(() => {
    if (selectedBackend) localStorage.setItem(LS_KEY_LLM, selectedBackend)
  }, [selectedBackend])

  useEffect(() => {
    if (selectedT2iBackend) localStorage.setItem(LS_KEY_T2I, selectedT2iBackend)
  }, [selectedT2iBackend])

  useEffect(() => {
    if (selectedTtsBackend) localStorage.setItem(LS_KEY_TTS, selectedTtsBackend)
  }, [selectedTtsBackend])

  useEffect(() => {
    localStorage.setItem(LS_KEY_CANDIDATES, String(candidateCount))
  }, [candidateCount])

  return (
    <div className={`app${theme === 'light' ? ' light-mode' : ''}`}>
      <div className="main-layout">
        <Sidebar />
        <div className="main-content">
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
            <div className="header-backends">
              <span>{llmBackends?.labels[selectedBackend] || selectedBackend}</span>
              <span className="header-sep">×</span>
              <span>{selectedT2iBackend || '—'}</span>
              <span className="header-sep">×</span>
              <span>{selectedTtsBackend || '—'}</span>
            </div>
          </div>

          {activeTab === 'chat' && (
            <ChatTab characters={characters} selectedChar={selectedChar} onCharChange={setSelectedChar} backend={selectedBackend} />
          )}
          {activeTab === 'character' && (
            <CharacterTab selectedChar={selectedChar} />
          )}
          {activeTab === 'session' && (
            <SessionTab characters={characters} backend={selectedBackend} />
          )}
          {activeTab === 'episode' && (
            <EpisodeTab backend={selectedBackend} t2iBackend={selectedT2iBackend} candidateCount={candidateCount} />
          )}
          {activeTab === 'debug' && <DebugTab />}
          {activeTab === 'settings' && (
            <SettingsTab
              llmBackend={selectedBackend}
              onLlmBackendChange={setSelectedBackend}
              t2iBackend={selectedT2iBackend}
              onT2iBackendChange={setSelectedT2iBackend}
              ttsBackend={selectedTtsBackend}
              onTtsBackendChange={setSelectedTtsBackend}
              candidateCount={candidateCount}
              onCandidateCountChange={setCandidateCount}
              theme={theme}
              onThemeToggle={toggleTheme}
            />
          )}
        </div>
      </div>
    </div>
  )
}

export default App
