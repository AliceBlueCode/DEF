import { useState, useEffect } from 'react'
import ApiKeyDialog from './ApiKeyDialog'

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

export default function SettingsTab({
  llmBackend, onLlmBackendChange,
  t2iBackend, onT2iBackendChange,
  ttsBackend, onTtsBackendChange,
  candidateCount, onCandidateCountChange,
}: Props) {
  const [llmBackends, setLlmBackends] = useState<BackendInfo | null>(null)
  const [t2iBackends, setT2iBackends] = useState<BackendInfo | null>(null)
  const [showApiKeyDialog, setShowApiKeyDialog] = useState(false)

  useEffect(() => {
    fetch('/api/settings/backends')
      .then(r => r.json())
      .then(data => {
        if (data.llm) setLlmBackends(data.llm)
        if (data.t2i) setT2iBackends(data.t2i)
      })
  }, [])

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
        <h3>APIキー</h3>
        <button className="api-key-open-btn" onClick={() => setShowApiKeyDialog(true)}>
          🔑 APIキー管理を開く
        </button>
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

      {showApiKeyDialog && <ApiKeyDialog onClose={() => setShowApiKeyDialog(false)} />}
    </div>
  )
}
