import { useState, useEffect } from 'react'

type BackendInfo = {
  backends: string[]
  labels: Record<string, string>
  default: string
}

type Props = {
  llmBackend: string
  onLlmBackendChange: (b: string) => void
}

export default function SettingsTab({ llmBackend, onLlmBackendChange }: Props) {
  const [llmBackends, setLlmBackends] = useState<BackendInfo | null>(null)
  const [t2iBackends, setT2iBackends] = useState<BackendInfo | null>(null)
  const [ttsBackend, setTtsBackend] = useState('voicevox')
  const [t2iBackend, setT2iBackend] = useState('')

  useEffect(() => {
    fetch('/api/settings/backends')
      .then(r => r.json())
      .then(data => {
        if (data.llm) setLlmBackends(data.llm)
        if (data.t2i) {
          setT2iBackends(data.t2i)
          setT2iBackend(data.t2i.default)
        }
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
        <select value={ttsBackend} onChange={e => setTtsBackend(e.target.value)}>
          <option value="voicevox">VOICEVOX (ローカル)</option>
          <option value="kokoro">Kokoro TTS (ローカル)</option>
          <option value="irodori">Irodori-TTS (ローカル)</option>
          <option value="gemini">Gemini TTS API</option>
        </select>
      </div>

      <div className="settings-section">
        <h3>T2I バックエンド</h3>
        {t2iBackends && (
          <select value={t2iBackend} onChange={e => setT2iBackend(e.target.value)}>
            {t2iBackends.backends.map(b => (
              <option key={b} value={b}>{t2iBackends.labels[b] || b}</option>
            ))}
          </select>
        )}
      </div>

      <div className="settings-section">
        <h3>バージョン</h3>
        <p className="version-info">DEF(kari) v1.0.0</p>
      </div>
    </div>
  )
}
