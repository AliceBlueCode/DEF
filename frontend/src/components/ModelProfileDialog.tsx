import { useState, useEffect } from 'react'
import { useT } from '../i18n'

type Props = {
  model: string
  onClose: () => void
}

const NATIVE_LANGS = ['ja', 'en', 'zh', 'ko']
const NSFW_LEVELS = ['sfw', 'nsfw', 'hentai']
const MODEL_TYPES = ['chat', 'novel', 'instruct']

export default function ModelProfileDialog({ model, onClose }: Props) {
  const t = useT()
  const [profile, setProfile] = useState<Record<string, unknown>>({})
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    if (!model) return
    fetch(`/api/settings/llm-profile?model=${encodeURIComponent(model)}`)
      .then(r => r.json())
      .then(data => setProfile(data.profile || {}))
  }, [model])

  const showMsg = (text: string) => {
    setMsg(text)
    setTimeout(() => setMsg(''), 2000)
  }

  const get = <T,>(key: string, def: T): T =>
    (key in profile ? profile[key] : def) as T

  const set = (key: string, value: unknown) =>
    setProfile(prev => ({ ...prev, [key]: value }))

  const getQuirk = (key: string): boolean =>
    ((profile.quirks as Record<string, boolean> | undefined)?.[key]) ?? (key === 'json_capable')

  const setQuirk = (key: string, value: boolean) =>
    setProfile(prev => ({
      ...prev,
      quirks: { ...(prev.quirks as object || {}), [key]: value },
    }))

  const getGen = (key: string, def: number): number =>
    ((profile.generation_params as Record<string, number> | undefined)?.[key]) ?? def

  const setGen = (key: string, value: number) =>
    setProfile(prev => ({
      ...prev,
      generation_params: { ...(prev.generation_params as object || {}), [key]: value },
    }))

  const save = async () => {
    setSaving(true)
    await fetch('/api/settings/llm-profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, profile }),
    })
    showMsg(t('dialog.msg.saved'))
    setSaving(false)
  }

  return (
    <div className="dialog-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="dialog apikey-dialog">
        <div className="dialog-header">
          <h3>{t('modelProfile.heading')}</h3>
          <button className="dialog-close" onClick={onClose}>✕</button>
        </div>

        <div className="model-profile-body">
          <div className="model-profile-model">{model}</div>

          <div className="profile-section-title">{t('modelProfile.section.basic')}</div>
          <div className="profile-row">
            <label>{t('modelProfile.label.nativeLang')}</label>
            <select value={get('native_language', 'en')} onChange={e => set('native_language', e.target.value)}>
              {NATIVE_LANGS.map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
          <div className="profile-row">
            <label>{t('modelProfile.label.nsfwTolerance')}</label>
            <select value={get('nsfw_tolerance', 'sfw')} onChange={e => set('nsfw_tolerance', e.target.value)}>
              {NSFW_LEVELS.map(l => <option key={l} value={l}>{l}</option>)}
            </select>
          </div>
          <div className="profile-row">
            <label>{t('modelProfile.label.modelType')}</label>
            <select value={get('model_type', 'chat')} onChange={e => set('model_type', e.target.value)}>
              {MODEL_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
          <div className="profile-row">
            <label>{t('modelProfile.label.maxTokens')}</label>
            <input type="number" min={64} max={16384} step={64}
              value={get('max_tokens', 512) as number}
              onChange={e => set('max_tokens', Number(e.target.value))} />
          </div>

          <div className="profile-section-title">Quirks</div>
          {([
            ['json_capable', 'modelProfile.quirk.jsonCapable'],
            ['appends_meta_text', 'modelProfile.quirk.appendsMeta'],
            ['outputs_url_in_prompt', 'modelProfile.quirk.outputsUrl'],
            ['emotion_in_text', 'modelProfile.quirk.emotionInText'],
          ] as [string, string][]).map(([key, i18nKey]) => (
            <div key={key} className="profile-row">
              <label>{t(i18nKey)}</label>
              <input type="checkbox" checked={getQuirk(key)}
                onChange={e => setQuirk(key, e.target.checked)} />
            </div>
          ))}

          <div className="profile-section-title">{t('modelProfile.section.genParams')}</div>
          <div className="profile-row">
            <label>Temperature <span className="profile-val">{getGen('temperature', 0.7).toFixed(1)}</span></label>
            <input type="range" min={0.1} max={2.0} step={0.1}
              value={getGen('temperature', 0.7)}
              onChange={e => setGen('temperature', Number(e.target.value))} />
          </div>
          <div className="profile-row">
            <label>Top P <span className="profile-val">{getGen('top_p', 0.9).toFixed(2)}</span></label>
            <input type="range" min={0.1} max={1.0} step={0.05}
              value={getGen('top_p', 0.9)}
              onChange={e => setGen('top_p', Number(e.target.value))} />
          </div>
          <div className="profile-row">
            <label>Repetition Penalty <span className="profile-val">{getGen('repetition_penalty', 1.1).toFixed(2)}</span></label>
            <input type="range" min={1.0} max={2.0} step={0.05}
              value={getGen('repetition_penalty', 1.1)}
              onChange={e => setGen('repetition_penalty', Number(e.target.value))} />
          </div>

          <div className="profile-actions">
            <button onClick={save} disabled={saving}>{t('dialog.saveBtn')}</button>
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
