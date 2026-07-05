import { useState, useEffect } from 'react'
import { useT } from '../i18n'

type Props = {
  model: string
  onClose: () => void
}

export default function T2IModelProfileDialog({ model, onClose }: Props) {
  const t = useT()
  const [profile, setProfile] = useState<Record<string, unknown>>({})
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    if (!model) return
    fetch(`/api/settings/t2i-profile?model=${encodeURIComponent(model)}`)
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

  const save = async () => {
    setSaving(true)
    await fetch('/api/settings/t2i-profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, profile }),
    })
    showMsg('保存しました')
    setSaving(false)
  }

  return (
    <div className="dialog-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="dialog apikey-dialog">
        <div className="dialog-header">
          <h3>🎨 T2I モデルプロファイル</h3>
          <button className="dialog-close" onClick={onClose}>✕</button>
        </div>

        <div className="model-profile-body">
          <div className="model-profile-model">{model}</div>

          <div className="profile-section-title">プロンプト</div>
          <div className="profile-row">
            <label>タグ形式</label>
            <select value={get('tag_format', 'danbooru') as string} onChange={e => set('tag_format', e.target.value)}>
              {(['danbooru', 'e621', 'natural', 'other'] as const).map(v => (
                <option key={v} value={v}>{t(`settings.t2iFormat.${v}`)}</option>
              ))}
            </select>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
            <label>クオリティタグ</label>
            <textarea
              rows={2}
              style={{ resize: 'vertical', width: '100%', boxSizing: 'border-box' }}
              value={get('quality_tags', 'masterpiece, best quality') as string}
              onChange={e => set('quality_tags', e.target.value)}
            />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
            <label>ネガティブ</label>
            <textarea
              rows={2}
              style={{ resize: 'vertical', width: '100%', boxSizing: 'border-box' }}
              value={get('negative_prompt', 'lowres, bad anatomy, worst quality') as string}
              onChange={e => set('negative_prompt', e.target.value)}
            />
          </div>

          <div className="profile-section-title">生成パラメータ</div>
          <div className="profile-row">
            <label>Steps <span className="profile-val">{get('steps', 20) as number}</span></label>
            <input
              type="range" min={1} max={150} step={1}
              value={get('steps', 20) as number}
              onChange={e => set('steps', Number(e.target.value))}
            />
          </div>
          <div className="profile-row">
            <label>CFG Scale <span className="profile-val">{(get('cfg_scale', 7.0) as number).toFixed(1)}</span></label>
            <input
              type="range" min={1.0} max={30.0} step={0.5}
              value={get('cfg_scale', 7.0) as number}
              onChange={e => set('cfg_scale', Number(e.target.value))}
            />
          </div>

          <div className="profile-actions">
            <button onClick={save} disabled={saving}>💾 保存</button>
            {msg && <span className="apikey-msg">{msg}</span>}
          </div>
        </div>

        <div className="dialog-footer">
          <button onClick={onClose}>閉じる</button>
        </div>
      </div>
    </div>
  )
}
