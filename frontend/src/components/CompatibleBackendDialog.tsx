import { useState, useEffect } from 'react'
import { useT } from '../i18n'

type Backend = {
  name: string
  base_url: string
  model: string
  extra_headers: Record<string, string>
  capabilities: string[]
  label: string
  has_key: boolean
}

type Props = {
  editing: Backend | null  // null = 新規追加
  onClose: () => void
  onSaved: () => void
}

const CAPABILITIES = ['llm', 'vlm', 't2i', 'tts']

export default function CompatibleBackendDialog({ editing, onClose, onSaved }: Props) {
  const t = useT()
  const isNew = editing === null
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [capabilities, setCapabilities] = useState<string[]>(['llm'])
  const [extraHeadersText, setExtraHeadersText] = useState('{}')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [headersError, setHeadersError] = useState('')

  useEffect(() => {
    if (editing) {
      setName(editing.name)
      setBaseUrl(editing.base_url)
      setModel(editing.model)
      setCapabilities(editing.capabilities)
      setExtraHeadersText(JSON.stringify(editing.extra_headers || {}, null, 2))
      setApiKey('')
    }
  }, [editing])

  const showMsg = (text: string) => {
    setMsg(text)
    setTimeout(() => setMsg(''), 2500)
  }

  const toggleCap = (cap: string) => {
    setCapabilities(prev =>
      prev.includes(cap) ? prev.filter(c => c !== cap) : [...prev, cap]
    )
  }

  const parseHeaders = (): Record<string, string> | null => {
    try {
      const parsed = JSON.parse(extraHeadersText || '{}')
      setHeadersError('')
      return parsed
    } catch {
      setHeadersError(t('compatibleBackend.errorHeadersInvalid'))
      return null
    }
  }

  const save = async () => {
    if (!name.trim()) { showMsg(t('compatibleBackend.errorNameRequired')); return }
    if (!baseUrl.trim()) { showMsg(t('compatibleBackend.errorBaseUrlRequired')); return }
    const headers = parseHeaders()
    if (headers === null) return

    setSaving(true)
    const body = {
      name: name.trim(),
      label: name.trim(),
      base_url: baseUrl.trim(),
      model: model.trim(),
      extra_headers: headers,
      capabilities,
      api_key: apiKey || null,
    }
    const url = isNew
      ? '/api/settings/compatible-backends'
      : `/api/settings/compatible-backends/${editing!.name}`
    const method = isNew ? 'POST' : 'PUT'
    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    setSaving(false)
    if (data.error) { showMsg(data.error); return }
    onSaved()
    onClose()
    window.location.reload()
  }

  return (
    <div className="dialog-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="dialog apikey-dialog">
        <div className="dialog-header">
          <h3>{isNew ? t('compatibleBackend.heading.add') : t('compatibleBackend.heading.edit')}</h3>
          <button className="dialog-close" onClick={onClose}>✕</button>
        </div>

        <div className="model-profile-body">
          <div className="profile-row">
            <label>{t('compatibleBackend.nameLabel')}</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              disabled={!isNew}
              placeholder={t('compatibleBackend.namePlaceholder')}
            />
          </div>
          <div className="profile-row">
            <label>Base URL *</label>
            <input
              type="text"
              value={baseUrl}
              onChange={e => setBaseUrl(e.target.value)}
              placeholder="https://api.x.ai/v1"
            />
          </div>
          <div className="profile-row">
            <label>Model</label>
            <input
              type="text"
              value={model}
              onChange={e => setModel(e.target.value)}
              placeholder={t('compatibleBackend.modelPlaceholder')}
            />
          </div>
          <div className="profile-row">
            <label>API Key</label>
            <input
              type="password"
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              placeholder={!isNew && editing?.has_key ? t('compatibleBackend.apiKeyPlaceholder') : ''}
            />
          </div>

          <div className="profile-section-title">{t('compatibleBackend.capabilitiesTitle')}</div>
          {CAPABILITIES.map(cap => (
            <div key={cap} className="profile-row">
              <label>{cap.toUpperCase()}</label>
              <input
                type="checkbox"
                checked={capabilities.includes(cap)}
                onChange={() => toggleCap(cap)}
              />
            </div>
          ))}

          <div className="profile-section-title">{t('compatibleBackend.extraHeadersTitle')}</div>
          <textarea
            style={{ width: '100%', minHeight: 80, fontFamily: 'monospace', fontSize: 12 }}
            value={extraHeadersText}
            onChange={e => setExtraHeadersText(e.target.value)}
          />
          {headersError && <div style={{ color: 'var(--color-error, red)', fontSize: 12 }}>{headersError}</div>}

          <div className="profile-actions">
            <button onClick={save} disabled={saving}>
              {saving ? t('compatibleBackend.saving') : t('compatibleBackend.save')}
            </button>
            {msg && <span className="apikey-msg">{msg}</span>}
          </div>
        </div>

        <div className="dialog-footer">
          <button onClick={onClose}>{t('dialog.closeBtn')}</button>
        </div>
      </div>
    </div>
  )
}
