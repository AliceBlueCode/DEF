import { useState, useEffect, useRef } from 'react'
import ChatTab from './components/ChatTab'
import CharacterTab from './components/CharacterTab'
import SessionTab from './components/SessionTab'
import NovelTab from './components/NovelTab'
import SettingsTab from './components/SettingsTab'
import DebugTab from './components/DebugTab'
import ThoughtTab from './components/ThoughtTab'
import Sidebar from './components/Sidebar'
import { LanguageProvider, useT, useLanguage } from './i18n'
import './App.css'

type Character = { id: string; name: string; image_color?: string; player_type?: string }
type BackendInfo = {
  backends: string[]
  labels: Record<string, string>
  default: string
}

type TabId = 'character' | 'chat' | 'session' | 'novel' | 'thought' | 'settings' | 'debug'

const TAB_IDS: { id: TabId; key: string; icon: string }[] = [
  { id: 'character', key: 'tab.character', icon: '👤' },
  { id: 'chat', key: 'tab.chat', icon: '💬' },
  { id: 'session', key: 'tab.session', icon: '🎭' },
  { id: 'novel', key: 'tab.novel', icon: '📖' },
  { id: 'thought', key: 'tab.thought', icon: '💭' },
  { id: 'settings', key: 'tab.settings', icon: '⚙️' },
  { id: 'debug', key: 'tab.debug', icon: '🐛' },
]

const LS_KEY_LLM = 'def_llm_backend'
const LS_KEY_T2I = 'def_t2i_backend'
const LS_KEY_TTS = 'def_tts_backend'
const LS_KEY_CANDIDATES = 'def_candidate_count'
const LS_KEY_THEME = 'def_theme'
const LS_KEY_CHAR = 'def_selected_char'
// SessionTab.tsxと同じキー文字列を使う(セッション参加/作成時に書き込み、
// 終了/退室時に消去する)。リロード直後にsessionタブへ自動で戻すためだけに
// ここで参照し、内容の読み書き自体はSessionTab.tsx側が担う。
const SS_KEY_ACTIVE_SESSION = 'def_active_session'

function AppInner() {
  const t = useT()
  const { lang } = useLanguage()
  const [characters, setCharacters] = useState<Character[]>([])
  const [selectedChar, setSelectedChar] = useState(() => localStorage.getItem(LS_KEY_CHAR) || '')
  const [llmBackends, setLlmBackends] = useState<BackendInfo | null>(null)
  const [selectedBackend, setSelectedBackend] = useState(() => localStorage.getItem(LS_KEY_LLM) || '')
  const [selectedT2iBackend, setSelectedT2iBackend] = useState(() => localStorage.getItem(LS_KEY_T2I) || '')
  const [selectedTtsBackend, setSelectedTtsBackend] = useState(() => localStorage.getItem(LS_KEY_TTS) || 'openai_tts')
  const [candidateCount, setCandidateCount] = useState(() => Number(localStorage.getItem(LS_KEY_CANDIDATES)) || 3)
  const [activeTab, setActiveTab] = useState<TabId>(() =>
    sessionStorage.getItem(SS_KEY_ACTIVE_SESSION) ? 'session' : 'chat'
  )
  // 「ユーザーがSettingsTabで実際に変更した」場合だけサーバー設定への書き戻しを
  // 行うためのフラグ。複数タブ/複数プロファイルを開いていると、単にタブを開いた
  // (≠明示的にバックエンドを変更した)だけで各タブが自分のlocalStorageキャッシュ
  // 値をサーバーへPOSTし直し、他のタブや過去のセッションが意図して設定した
  // デフォルトを黙って上書きしてしまっていた(2026-08-09発覚)。
  // 当初はuseRefで「マウント後1回目のeffectだけスキップ」する案を試したが、
  // React StrictMode(main.tsxで有効)が開発時にeffectを意図的に二重発火させる
  // ため、1回目でrefをtrueにした直後の2回目の発火でPOSTしてしまい機能しなかった。
  // マウントのタイミングから推測するのではなく、変更のトリガー元(onXxxBackendChange
  // 経由の明示的な呼び出しか否か)を直接フラグで持つ方式にした。
  const llmUserChangedRef = useRef(false)
  const t2iUserChangedRef = useRef(false)
  const ttsUserChangedRef = useRef(false)
  const handleLlmBackendChange = (v: string) => { llmUserChangedRef.current = true; setSelectedBackend(v) }
  const handleT2iBackendChange = (v: string) => { t2iUserChangedRef.current = true; setSelectedT2iBackend(v) }
  const handleTtsBackendChange = (v: string) => { ttsUserChangedRef.current = true; setSelectedTtsBackend(v) }
  const [chatReloadTrigger, setChatReloadTrigger] = useState(0)
  const [theme, setTheme] = useState<'dark' | 'light'>(() =>
    (localStorage.getItem(LS_KEY_THEME) as 'dark' | 'light') || 'light'
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
        const chars: Character[] = data.characters || []
        setCharacters(chars)
        if (chars.length > 0) {
          const saved = localStorage.getItem(LS_KEY_CHAR)
          const valid = saved && chars.some(c => c.id === saved)
          setSelectedChar(valid ? saved : chars[0].id)
        }
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
    if (selectedChar) localStorage.setItem(LS_KEY_CHAR, selectedChar)
  }, [selectedChar])

  useEffect(() => {
    if (!selectedBackend) return
    localStorage.setItem(LS_KEY_LLM, selectedBackend)
    if (!llmUserChangedRef.current) return
    fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: { llm_backend: selectedBackend } }),
    }).catch(() => {})
  }, [selectedBackend])

  useEffect(() => {
    if (!selectedT2iBackend) return
    localStorage.setItem(LS_KEY_T2I, selectedT2iBackend)
    if (!t2iUserChangedRef.current) return
    fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: { t2i_backend: selectedT2iBackend } }),
    }).catch(() => {})
  }, [selectedT2iBackend])

  useEffect(() => {
    if (!selectedTtsBackend) return
    localStorage.setItem(LS_KEY_TTS, selectedTtsBackend)
    if (!ttsUserChangedRef.current) return
    fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: { tts_backend: selectedTtsBackend } }),
    }).catch(() => {})
  }, [selectedTtsBackend])

  useEffect(() => {
    localStorage.setItem(LS_KEY_CANDIDATES, String(candidateCount))
  }, [candidateCount])

  return (
    <div className={`app${theme === 'light' ? ' light-mode' : ''}`} lang={lang}>
      <div className="main-layout">
        <Sidebar />
        <div className="main-content">
          <div className="tabs">
            {TAB_IDS.map(tab => (
              <button
                key={tab.id}
                className={`tab ${activeTab === tab.id ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.icon} {t(tab.key)}
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

          <div style={{ display: activeTab === 'chat' ? 'contents' : 'none' }}>
            <ChatTab characters={characters} selectedChar={selectedChar} backend={selectedBackend} ttsBackend={selectedTtsBackend} t2iBackend={selectedT2iBackend} reloadTrigger={chatReloadTrigger} />
          </div>
          <div style={{ display: activeTab === 'character' ? 'contents' : 'none' }}>
            <CharacterTab characters={characters} selectedChar={selectedChar} onCharChange={setSelectedChar} onHistoryCleared={() => setChatReloadTrigger(t => t + 1)} ttsBackend={selectedTtsBackend} />
          </div>
          <div style={{ display: activeTab === 'session' ? 'contents' : 'none' }}>
            <SessionTab characters={characters} backend={selectedBackend} ttsBackend={selectedTtsBackend} t2iBackend={selectedT2iBackend} />
          </div>
          <div style={{ display: activeTab === 'novel' ? 'contents' : 'none' }}>
            <NovelTab backend={selectedBackend} t2iBackend={selectedT2iBackend} candidateCount={candidateCount} ttsBackend={selectedTtsBackend} selectedChar={selectedChar} llmBackends={llmBackends} />
          </div>
          <div style={{ display: activeTab === 'thought' ? 'contents' : 'none' }}>
            <ThoughtTab backend={selectedBackend} />
          </div>
          <div style={{ display: activeTab === 'debug' ? 'contents' : 'none' }}>
            <DebugTab />
          </div>
          <div style={{ display: activeTab === 'settings' ? 'contents' : 'none' }}>
            <SettingsTab
              llmBackend={selectedBackend}
              onLlmBackendChange={handleLlmBackendChange}
              t2iBackend={selectedT2iBackend}
              onT2iBackendChange={handleT2iBackendChange}
              ttsBackend={selectedTtsBackend}
              onTtsBackendChange={handleTtsBackendChange}
              candidateCount={candidateCount}
              onCandidateCountChange={setCandidateCount}
              theme={theme}
              onThemeToggle={toggleTheme}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

function App() {
  return (
    <LanguageProvider>
      <AppInner />
    </LanguageProvider>
  )
}

export default App
