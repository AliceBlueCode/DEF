import { useState, useEffect } from 'react'

type Props = {
  onClose: () => void
}

const API_SERVICES: { id: string; label: string }[] = [
  { id: 'gemini', label: 'Gemini API' },
  { id: 'openai', label: 'OpenAI API' },
  { id: 'anthropic', label: 'Anthropic API' },
]

export default function ApiKeyDialog({ onClose }: Props) {
  const [keyStatus, setKeyStatus] = useState<Record<string, boolean>>({})
  const [keyInputs, setKeyInputs] = useState<Record<string, string>>({})
  const [keySaving, setKeySaving] = useState<Record<string, boolean>>({})
  const [keyMsg, setKeyMsg] = useState<Record<string, string>>({})

  useEffect(() => {
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
    <div className="dialog-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="dialog">
        <div className="dialog-header">
          <h3>APIキー管理</h3>
          <button className="dialog-close" onClick={onClose}>✕</button>
        </div>
        <div className="dialog-body">
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
                  <button className="delete-btn" onClick={() => deleteKey(id)}>削除</button>
                )}
              </div>
              {keyMsg[id] && <p className="api-key-msg">{keyMsg[id]}</p>}
            </div>
          ))}
        </div>
        <div className="dialog-footer">
          <button onClick={onClose}>閉じる</button>
        </div>
      </div>
    </div>
  )
}
