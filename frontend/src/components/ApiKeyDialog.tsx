import { useState, useEffect } from 'react'

type ApiService = {
  id: string
  label: string
  env_var?: string
  help?: string
}

type Props = {
  onClose: () => void
}

export default function ApiKeyDialog({ onClose }: Props) {
  const [services, setServices] = useState<ApiService[]>([])
  const [keyStatus, setKeyStatus] = useState<Record<string, boolean>>({})
  const [selectedId, setSelectedId] = useState('')
  const [keyInput, setKeyInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    fetch('/api/settings/api-services')
      .then(r => r.json())
      .then(data => {
        const svcs: ApiService[] = data.services || []
        setServices(svcs)
        if (svcs.length > 0) setSelectedId(svcs[0].id)
      })
    loadKeyStatus()
  }, [])

  const loadKeyStatus = () => {
    fetch('/api/settings/api-keys')
      .then(r => r.json())
      .then(setKeyStatus)
  }

  const showMsg = (text: string) => {
    setMsg(text)
    setTimeout(() => setMsg(''), 2000)
  }

  const saveKey = async () => {
    const val = keyInput.trim()
    if (!val || !selectedId) return
    setSaving(true)
    await fetch(`/api/settings/api-keys/${selectedId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api_key: val }),
    })
    setKeyInput('')
    showMsg('保存しました')
    setSaving(false)
    loadKeyStatus()
  }

  const deleteKey = async () => {
    if (!selectedId || !keyStatus[selectedId]) return
    const svc = services.find(s => s.id === selectedId)
    if (!confirm(`${svc?.label ?? selectedId} のAPIキーを削除しますか？`)) return
    await fetch(`/api/settings/api-keys/${selectedId}`, { method: 'DELETE' })
    showMsg('削除しました')
    loadKeyStatus()
  }

  const selectRow = (id: string) => {
    setSelectedId(id)
    setKeyInput('')
    setMsg('')
  }

  const selectedSvc = services.find(s => s.id === selectedId)

  return (
    <div className="dialog-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="dialog apikey-dialog">
        <div className="dialog-header">
          <h3>🔑 APIキー管理</h3>
          <button className="dialog-close" onClick={onClose}>✕</button>
        </div>

        <div className="apikey-input-area">
          <select
            className="apikey-service-select"
            value={selectedId}
            onChange={e => selectRow(e.target.value)}
          >
            {services.map(s => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
          <input
            type="password"
            className="apikey-value-input"
            placeholder={keyStatus[selectedId] ? '変更する場合は入力...' : 'APIキーを入力...'}
            value={keyInput}
            onChange={e => setKeyInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && saveKey()}
          />
          <button onClick={saveKey} disabled={!keyInput.trim() || saving}>
            登録
          </button>
          <button
            className="delete-btn"
            onClick={deleteKey}
            disabled={!keyStatus[selectedId]}
          >
            削除
          </button>
        </div>

        {(msg || selectedSvc?.help) && (
          <div className="apikey-hint-area">
            {msg
              ? <span className="apikey-msg">{msg}</span>
              : <span className="apikey-help">{selectedSvc?.help}</span>
            }
          </div>
        )}

        <div className="apikey-list-header">設定済みキー一覧</div>
        <div className="apikey-list">
          {services.map(({ id, label, env_var }) => (
            <div
              key={id}
              className={`apikey-list-row ${selectedId === id ? 'selected' : ''}`}
              onClick={() => selectRow(id)}
            >
              <span className={`apikey-dot ${keyStatus[id] ? 'set' : 'unset'}`}>●</span>
              <span className="apikey-list-label">{label}</span>
              {env_var && <span className="apikey-list-envvar">{env_var}</span>}
              <span className={`apikey-list-status ${keyStatus[id] ? 'set' : 'unset'}`}>
                {keyStatus[id] ? '✓' : '未設定'}
              </span>
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
