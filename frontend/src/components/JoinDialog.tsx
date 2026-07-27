import { useState, useRef } from 'react'
import { useT } from '../i18n'

type Props = {
  onJoined: (sessionId: string, playerToken: string, charId: string, role: 'player' | 'observer') => void
  onClose: () => void
}

const S = {
  overlay: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 } as React.CSSProperties,
  box: { background: 'var(--bg-color, #fff)', border: '1px solid var(--border-color, #ddd)', borderRadius: 12, padding: '28px 32px', minWidth: 340, maxWidth: 460, width: '90vw', boxShadow: '0 8px 32px rgba(0,0,0,0.15)', display: 'flex', flexDirection: 'column', gap: 14 } as React.CSSProperties,
  title: { margin: 0, fontSize: '1.1em', fontWeight: 700 } as React.CSSProperties,
  label: { fontSize: '0.82em', opacity: 0.55, marginBottom: 4 } as React.CSSProperties,
  input: { width: '100%', boxSizing: 'border-box', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'var(--input-bg, #f5f5f5)', color: 'inherit', fontSize: '0.95em' } as React.CSSProperties,
  fileBtn: { padding: '6px 14px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'transparent', color: 'inherit', cursor: 'pointer', fontSize: '0.88em' } as React.CSSProperties,
  textarea: { width: '100%', boxSizing: 'border-box', padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'var(--input-bg, #f5f5f5)', color: 'inherit', fontSize: '0.78em', fontFamily: 'monospace', resize: 'vertical' } as React.CSSProperties,
  error: { color: 'var(--danger-color, #d32)', fontSize: '0.85em' } as React.CSSProperties,
  actions: { display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 4 } as React.CSSProperties,
  cancelBtn: { padding: '7px 18px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'transparent', color: 'inherit', cursor: 'pointer' } as React.CSSProperties,
  submitBtn: { padding: '7px 20px', borderRadius: 6, border: 'none', background: '#4a6cf7', color: '#fff', cursor: 'pointer', fontWeight: 600 } as React.CSSProperties,
}

export default function JoinDialog({ onJoined, onClose }: Props) {
  const t = useT()
  const [inviteCode, setInviteCode] = useState('')
  const [charJson, setCharJson] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = ev => setCharJson(ev.target?.result as string ?? '')
    reader.readAsText(file)
  }

  const join = async () => {
    setError('')
    const code = inviteCode.trim().toUpperCase()
    if (!code) { setError(t('session.join.errorNoCode')); return }

    let characterJson: Record<string, unknown> = {}
    if (charJson.trim()) {
      try {
        const parsed = JSON.parse(charJson)
        const keys = Object.keys(parsed)
        if (keys.length === 1 && parsed[keys[0]]?.base_profile) {
          const bp = parsed[keys[0]].base_profile
          characterJson = {
            name: bp.name ?? keys[0],
            identity_prompt: bp.identity_prompt ?? '',
            identity_detail: bp.identity_detail ?? '',
            persona_attributes: bp.persona_attributes ?? {},
            content_policy: bp.content_policy ?? {},
          }
        } else {
          characterJson = parsed
        }
      } catch {
        setError(t('session.join.errorBadJson'))
        return
      }
    }

    setLoading(true)
    try {
      const res = await fetch('/api/session/join', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invite_code: code, character_json: characterJson }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail ?? t('session.join.errorFailed'))
        return
      }
      onJoined(data.session_id, data.player_token, data.character_id, data.role ?? 'player')
    } catch {
      setError(t('session.join.errorFailed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={S.overlay} onClick={onClose}>
      <div style={S.box} onClick={e => e.stopPropagation()}>
        <h3 style={S.title}>{t('session.join.title')}</h3>

        <div>
          <div style={S.label}>{t('session.join.codeLabel')}</div>
          <input
            style={S.input}
            placeholder="SFW-ABK-492"
            value={inviteCode}
            onChange={e => setInviteCode(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') void join() }}
            autoFocus
          />
        </div>

        <div>
          <div style={S.label}>{t('session.join.charLabel')}</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button style={S.fileBtn} onClick={() => fileRef.current?.click()}>
              {t('session.join.fileBtn')}
            </button>
            <input ref={fileRef} type="file" accept=".json" style={{ display: 'none' }} onChange={handleFile} />
            {charJson && <span style={{ fontSize: '0.82em', opacity: 0.7 }}>✓ {t('session.join.charLoaded')}</span>}
          </div>
          {charJson && (
            <textarea
              style={{ ...S.textarea, marginTop: 8 }}
              rows={4}
              value={charJson}
              onChange={e => setCharJson(e.target.value)}
            />
          )}
        </div>

        {error && <div style={S.error}>{error}</div>}

        <div style={S.actions}>
          <button style={S.cancelBtn} onClick={onClose}>{t('common.cancel')}</button>
          <button style={{ ...S.submitBtn, opacity: loading ? 0.6 : 1 }} onClick={join} disabled={loading}>
            {loading ? '...' : t('session.join.submit')}
          </button>
        </div>
      </div>
    </div>
  )
}
