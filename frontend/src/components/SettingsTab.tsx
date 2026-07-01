import { useState, useEffect } from 'react'

type BackendInfo = {
  backends: string[]
  labels: Record<string, string>
  default: string
}

type Props = {
  llmBackend: string
  onLlmBackendChange: (b: string) => void
  t2iBackend: string
  onT2iBackendChange: (b: string) => void
  ttsBackend: string
  onTtsBackendChange: (b: string) => void
  candidateCount: number
  onCandidateCountChange: (n: number) => void
}

const API_SERVICES: { id: string; label: string }[] = [
  { id: 'gemini', label: 'Gemini API' },
  { id: 'openai', label: 'OpenAI API' },
  { id: 'anthropic', label: 'Anthropic API' },
]

export default function SettingsTab({
  llmBackend, onLlmBackendChange,
  t2iBackend, onT2iBackendChange,
  ttsBackend, onTtsBackendChange,
  candidateCount, onCandidateCountChange,
}: Props) {
  const [llmBackends, setLlmBackends] = useState<BackendInfo | null>(null)
  const [t2iBackends, setT2iBackends] = useState<BackendInfo | null>(null)
  const [keyStatus, setKeyStatus] = useState<Record<string, boolean>>({})
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({})
  const [keySaving, setKeySaving] = useState<Record<string, boolean>>({})
  const [keyMsg, setKeyMsg] = useState<Record<string, string>>({})

  useEffect(() => {
    fetch('/api/settings/backends')
      .then(r => r.json())
      .then(data => {
        if (data.llm) setLlmBackends(data.llm)
        if (data.t2i) setT2iBackends(data.t2i)
      })
    loadKeyStatus()
  }, [])

  const loadKeyStatus = () => {
    fetch('/api/settings/api-keys')
      .then(r => r.json())
      .then(setKeyStatus)
  }

  const saveKey = async (service: string) => {
    const val = keyInputs[service]?.trim()
    if (!val) return
    setKeySaving(prev => ({ ...prev, [service]: true }))
    await fetch(`/api/settings/api-keys/${service}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: val }),
    })
    setKeyInputs(prev => ({ ...prev, [service]: '' }))
    setKeyMsg(prev => ({ ...prev, [service]: '保存しました' }))
    setTimeout(() => setKeyMsg(prev => ({ ...prev, [service]: '' })), 2000)
    setKeySaving(prev => ({ ...prev, [service]: false }))
    loadKeyStatus()
  }

  const deleteKey = async (service: string) => {
    if (!confirm(`${service} の APIキーを削除しますか？`)) return
    await fetch(`/api/settings/api-keys/${service}`, { method: 'DELETE' })
    setKeyMsg(prev => ({ ...prev, [service]: '削除しました' }))
    setTimeout(() => setKeyMsg(prev => ({ ...prev, [service]: '' })), 2000)
    loadKeyStatus()
  }

  return (
    <div className="tab-content settings-tab">
      <h2>設定</h2>

      <div className="settings-section">
        <h3>LLM バックエンド</h3>
        {llmBackends && (
          <select value={llmBackend} onChange={e => onLlmBackendChange(e.target.value)}>
            {llmBackends.backends.map(b => (
              <option key={b} value={b}>{llmBackends.labels[b] || b}</option>
            ))}
          </select>
        )}
      </div>

      <div className="settings-section">
        <h3>TTS バックエンド</h3>
        <select value={ttsBackend} onChange={e => onTtsBackendChange(e.target.value)}>
          <option value="voicevox">VOICEVOX (ローカル)</option>
          <option value="kokoro">Kokoro TTS (ローカル)</option>
          <option value="irodori">Irodori-TTS (ローカル)</option>
          <option value="gemini">Gemini TTS API</option>
        </select>
      </div>

      <div className="settings-section">
        <h3>T2I バックエンド</h3>
        {t2iBackends && (
          <select value={t2iBackend} onChange={e => onT2iBackendChange(e.target.value)}>
            {t2iBackends.backends.map(b => (
              <option key={b} value={b}>{t2iBackends.labels[b] || b}</option>
            ))}
          </select>
        )}
      </div>

      <div className="settings-section">
        <h3>APIキー管理</h3>
        <div className="api-keys-list">
          {API_SERVICES.map(({ id, label }) => (
            <div key={id} className="api-key-row">
              <div className="api-key-header">
                <span className="api-key-label">{label}</span>
                <span className={`api-key-status ${keyStatus[id] ? 'set' : 'unset'}`}>
                  {keyStatus[id] ? '✓ 設定済み' : '○ 未設定'}
                </span>
              </div>
              <div className="api-key-controls">
                <input
                  type="password"
                  className="api-key-input"
                  placeholder={keyStatus[id] ? '変更する場合は入力...' : 'APIキーを入力...'}
                  value={keyInputs[id] || ''}
                  onChange={e => setKeyInputs(prev => ({ ...prev, [id]: e.target.value }))}
                  onKeyDown={e => e.key === 'Enter' && saveKey(id)}
                />
                <button
                  onClick={() => saveKey(id)}
                  disabled={!keyInputs[id]?.trim() || keySaving[id]}
                >
                  保存
                </button>
                {keyStatus[id] && (
                  <button className="delete-btn" onClick={() => deleteKey(id)}>
                    削除
                  </button>
                )}
              </div>
              {keyMsg[id] && <p className="api-key-msg">{keyMsg[id]}</p>}
            </div>
          ))}
        </div>
      </div>

      <div className="settings-section">
        <h3>生成設定</h3>
        <div className="gen-setting-row">
          <label>AI候補数（エピソード）</label>
          <div className="candidate-count-controls">
            {[1, 2, 3, 4, 5].map(n => (
              <button
                key={n}
                className={`count-btn ${candidateCount === n ? 'active' : ''}`}
                onClick={() => onCandidateCountChange(n)}
              >
                {n}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="settings-section">
        <h3>バージョン</h3>
        <p className="version-info">DEF(kari) v1.0.0</p>
      </div>
    </div>
  )
}
