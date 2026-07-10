import { useState, useEffect } from 'react'
import { useT } from '../i18n'

type BackendDef = {
  id: string
  label: string
  dir_env: string | null
  url_env: string | null
  default_url: string | null
}

type Props = {
  onClose: () => void
}

export default function BackendDirDialog({ onClose }: Props) {
  const t = useT()
  const [backends, setBackends] = useState<BackendDef[]>([])
  const [values, setValues] = useState<Record<string, string>>({})
  const [selectedId, setSelectedId] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    fetch('/api/settings/backend-dirs')
      .then(r => r.json())
      .then(data => {
        const bs: BackendDef[] = data.backends || []
        setBackends(bs)
        setValues(data.values || {})
        if (bs.length > 0) setSelectedId(bs[0].id)
      })
  }, [])

  const showMsg = (text: string) => {
    setMsg(text)
    setTimeout(() => setMsg(''), 2000)
  }

  const save = async () => {
    setSaving(true)
    await fetch('/api/settings/backend-dirs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values }),
    })
    showMsg(t('backendDir.msg.saved'))
    setSaving(false)
  }

  const selected = backends.find(b => b.id === selectedId)

  const hasValue = (b: BackendDef) =>
    (b.dir_env && values[b.dir_env]) || (b.url_env && values[b.url_env])

  return (
    <div className="dialog-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="dialog apikey-dialog">
        <div className="dialog-header">
          <h3>{t('backendDir.heading')}</h3>
          <button className="dialog-close" onClick={onClose}>✕</button>
        </div>

        <div className="apikey-list-header">{t('backendDir.list.header')}</div>
        <div className="apikey-list">
          {backends.map(b => (
            <div
              key={b.id}
              className={`apikey-list-row ${selectedId === b.id ? 'selected' : ''}`}
              onClick={() => { setSelectedId(b.id); setMsg('') }}
            >
              <span className={`apikey-dot ${hasValue(b) ? 'set' : 'unset'}`}>●</span>
              <span className="apikey-list-label">{b.label}</span>
              <span className={`apikey-list-status ${hasValue(b) ? 'set' : 'unset'}`}>
                {hasValue(b) ? '✓' : t('dialog.status.unset')}
              </span>
            </div>
          ))}
        </div>

        {selected && (
          <div className="backend-dir-form">
            {selected.dir_env && (
              <div className="backend-dir-row">
                <label className="backend-dir-label">{t('backendDir.installDir')}</label>
                <input
                  type="text"
                  className="backend-dir-input"
                  placeholder="例: C:\tools\textgen-webui"
                  value={values[selected.dir_env] ?? ''}
                  onChange={e => setValues(prev => ({ ...prev, [selected.dir_env!]: e.target.value }))}
                />
              </div>
            )}
            {selected.url_env && (
              <div className="backend-dir-row">
                <label className="backend-dir-label">URL</label>
                <input
                  type="text"
                  className="backend-dir-input"
                  placeholder={selected.default_url ?? ''}
                  value={values[selected.url_env] ?? ''}
                  onChange={e => setValues(prev => ({ ...prev, [selected.url_env!]: e.target.value }))}
                />
              </div>
            )}
            <div className="backend-dir-actions">
              <button onClick={save} disabled={saving}>{t('dialog.saveBtn')}</button>
              {msg && <span className="apikey-msg">{msg}</span>}
            </div>
          </div>
        )}

        <div className="dialog-footer">
          <button onClick={onClose}>{t('dialog.closeBtn')}</button>
        </div>
      </div>
    </div>
  )
}
