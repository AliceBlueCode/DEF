import { useState, useEffect } from 'react'
import { useT } from '../i18n'

type CivitaiModel = {
  label: string
  model_air: string
}

type Props = {
  currentModel: string
  onSelect: (modelAir: string) => void
  onClose: () => void
}

export default function CivitaiDialog({ currentModel, onSelect, onClose }: Props) {
  const t = useT()
  const [models, setModels] = useState<CivitaiModel[]>([])
  const [input, setInput] = useState('')
  const [label, setLabel] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  const load = () => {
    fetch('/api/settings/civitai-models')
      .then(r => r.json())
      .then(data => setModels(data.models || []))
  }

  useEffect(() => { load() }, [])

  const showMsg = (text: string) => {
    setMsg(text)
    setTimeout(() => setMsg(''), 2500)
  }

  const add = async () => {
    const air = input.trim()
    if (!air) return
    setSaving(true)
    const res = await fetch('/api/settings/civitai-models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label: label.trim() || air, model_air: air }),
    })
    const data = await res.json()
    if (data.status === 'already_exists') {
      showMsg(t('dialog.msg.alreadyExists'))
    } else {
      setInput('')
      setLabel('')
      showMsg(t('dialog.msg.registered'))
      load()
    }
    setSaving(false)
  }

  const remove = async (index: number, modelLabel: string) => {
    if (!confirm(t('dialog.confirm.deleteModel', { label: modelLabel }))) return
    await fetch(`/api/settings/civitai-models/${index}`, { method: 'DELETE' })
    load()
  }

  return (
    <div className="dialog-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="dialog apikey-dialog">
        <div className="dialog-header">
          <h3>{t('civitai.heading')}</h3>
          <button className="dialog-close" onClick={onClose}>✕</button>
        </div>

        <div className="model-profile-body">
          <div className="profile-section-title">{t('civitai.addSection')}</div>
          <div className="backend-dir-row">
            <label className="backend-dir-label">{t('civitai.airLabel')}</label>
            <input
              type="text"
              className="backend-dir-input"
              placeholder="urn:air:..."
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && add()}
            />
          </div>
          <div className="backend-dir-row">
            <label className="backend-dir-label">{t('civitai.displayName')}</label>
            <input
              type="text"
              className="backend-dir-input"
              placeholder="例: Illustrious XL v1.0"
              value={label}
              onChange={e => setLabel(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && add()}
            />
          </div>
          <div className="backend-dir-actions">
            <button onClick={add} disabled={!input.trim() || saving}>{t('dialog.addBtn')}</button>
            {msg && <span className="apikey-msg">{msg}</span>}
          </div>

          <div className="profile-section-title" style={{ marginTop: 16 }}>{t('civitai.registeredSection')}</div>
          {models.length === 0
            ? <div className="profile-empty">{t('dialog.noEntries')}</div>
            : models.map((m, i) => (
              <div
                key={i}
                className={`civitai-model-row ${currentModel === m.model_air ? 'hf-model-selected' : ''}`}
                onClick={() => onSelect(m.model_air)}
                style={{ cursor: 'pointer' }}
              >
                <div className="civitai-model-info">
                  {m.label !== m.model_air && (
                    <div className="civitai-model-label">{m.label}</div>
                  )}
                  <div className="civitai-model-air">{m.model_air}</div>
                </div>
                {currentModel === m.model_air && (
                  <span className="hf-model-check">✓</span>
                )}
                <button
                  className="delete-btn"
                  onClick={e => { e.stopPropagation(); remove(i, m.label) }}
                >{t('dialog.deleteBtn')}</button>
              </div>
            ))
          }
        </div>

        <div className="dialog-footer">
          <button onClick={onClose}>{t('dialog.closeBtn')}</button>
        </div>
      </div>
    </div>
  )
}
