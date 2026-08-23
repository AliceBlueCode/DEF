import { useRef } from 'react'
import { useT } from '../i18n'
import { useJoinFlow, type JoinResult } from './useJoinFlow'

type Props = {
  onJoined: (result: JoinResult) => void
  onClose: () => void
}

const S = {
  overlay: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 } as React.CSSProperties,
  box: { background: 'var(--bg-color, #fff)', border: '1px solid var(--border-color, #ddd)', borderRadius: 12, padding: '28px 32px', minWidth: 340, maxWidth: 460, width: '90vw', boxShadow: '0 8px 32px rgba(0,0,0,0.15)', display: 'flex', flexDirection: 'column', gap: 16 } as React.CSSProperties,
  title: { margin: 0, fontSize: '1.1em', fontWeight: 700 } as React.CSSProperties,
  label: { fontSize: '0.82em', opacity: 0.55, marginBottom: 4 } as React.CSSProperties,
  input: { width: '100%', boxSizing: 'border-box', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'var(--input-bg, #f5f5f5)', color: 'inherit', fontSize: '0.95em' } as React.CSSProperties,
  error: { color: 'var(--danger-color, #d32)', fontSize: '0.85em' } as React.CSSProperties,
  actions: { display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 4 } as React.CSSProperties,
  cancelBtn: { padding: '7px 18px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'transparent', color: 'inherit', cursor: 'pointer' } as React.CSSProperties,
  submitBtn: { padding: '7px 20px', borderRadius: 6, border: 'none', background: '#4a6cf7', color: '#fff', cursor: 'pointer', fontWeight: 600 } as React.CSSProperties,
}

export default function JoinDialog({ onJoined, onClose }: Props) {
  const t = useT()
  const f = useJoinFlow()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const submit = async () => {
    const result = await f.join()
    if (result) onJoined(result)
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
            value={f.inviteCode}
            onChange={e => {
              f.setInviteCode(e.target.value)
              f.setSlotsLoaded(false)
              f.lastFetchedCode.current = ''
            }}
            onBlur={() => void f.fetchSlots(f.inviteCode)}
            onKeyDown={e => {
              if (e.key === 'Enter') void f.fetchSlots(f.inviteCode)
            }}
            autoFocus
          />
        </div>

        {f.slotsLoaded && (
          <div>
            <div style={S.label}>{t('session.join.slotLabel')}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', padding: '6px 8px', borderRadius: 6, background: f.selectedSlot === '__observer__' ? 'var(--input-bg, rgba(128,128,128,0.15))' : 'transparent' }}>
                <input type="radio" name="slot" value="__observer__" checked={f.selectedSlot === '__observer__'} onChange={() => f.setSelectedSlot('__observer__')} />
                <span style={{ fontSize: '0.9em' }}>👁 {t('session.join.observerSlot')}</span>
              </label>

              {f.onlineMode ? (
                <>
                  {/* キーパーとして参加（ホストが「参加者を待つ」を選んだ時のみ表示） */}
                  {f.waitingForGm && (
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: f.gmTaken ? 'not-allowed' : 'pointer', opacity: f.gmTaken ? 0.4 : 1, padding: '6px 8px', borderRadius: 6, background: f.selectedSlot === '__gm__' ? 'var(--input-bg, rgba(128,128,128,0.15))' : 'transparent' }}>
                      <input type="radio" name="slot" value="__gm__" disabled={f.gmTaken} checked={f.selectedSlot === '__gm__'} onChange={() => !f.gmTaken && f.setSelectedSlot('__gm__')} />
                      <span style={{ fontSize: '0.9em' }}>{t('session.join.gmSlot')}</span>
                      {f.gmTaken && <span style={{ fontSize: '0.75em', opacity: 0.6 }}>{t('session.join.gmTakenBadge')}</span>}
                    </label>
                  )}
                  {/* プレイヤーとして参加（キャラJSON持ち込み） */}
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', padding: '6px 8px', borderRadius: 6, background: f.selectedSlot === '__player__' ? 'var(--input-bg, rgba(128,128,128,0.15))' : 'transparent' }}>
                    <input type="radio" name="slot" value="__player__" checked={f.selectedSlot === '__player__'} onChange={() => f.setSelectedSlot('__player__')} />
                    <span style={{ fontSize: '0.9em' }}>{t('session.join.playerSlot')}</span>
                  </label>
                </>
              ) : (
                f.slots.map(slot => (
                  <label
                    key={slot.char_id}
                    style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: slot.available ? 'pointer' : 'not-allowed', opacity: slot.available ? 1 : 0.4, padding: '6px 8px', borderRadius: 6, background: f.selectedSlot === slot.char_id ? 'var(--input-bg, rgba(128,128,128,0.15))' : 'transparent' }}
                  >
                    <input
                      type="radio"
                      name="slot"
                      value={slot.char_id}
                      disabled={!slot.available}
                      checked={f.selectedSlot === slot.char_id}
                      onChange={() => slot.available && f.setSelectedSlot(slot.char_id)}
                    />
                    <span style={{ fontSize: '0.9em' }}>🎭 {slot.char_name}</span>
                    {!slot.available && <span style={{ fontSize: '0.75em', opacity: 0.6 }}>{t('session.join.slotTaken')}</span>}
                  </label>
                ))
              )}
            </div>

            {f.onlineMode && f.selectedSlot === '__player__' && (
              <div style={{ marginTop: 10 }}>
                <div style={S.label}>{t('session.join.charJsonLabel')}</div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".json"
                  style={{ display: 'none' }}
                  onChange={f.handleFileSelect}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  style={{ padding: '7px 16px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'transparent', color: 'inherit', cursor: 'pointer', fontSize: '0.9em' }}
                >
                  {f.charJsonName ? `✓ ${f.charJsonName}` : t('session.join.selectJsonBtn')}
                </button>
                {f.trpgMode && f.charJson && f.sheetOptions.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <div style={S.label}>{t('session.join.sheetLabel')}</div>
                    <select
                      className="session-select"
                      style={S.input}
                      value={f.selectedSheetId}
                      onChange={e => f.setSelectedSheetId(e.target.value)}
                    >
                      <option value="">{t('trpg.gameChar.noSheet')}</option>
                      {f.sheetOptions.map(sid => (
                        <option key={sid} value={sid}>{sid}</option>
                      ))}
                    </select>
                  </div>
                )}
                {f.trpgMode && f.charJson && f.sheetOptions.length === 0 && (
                  <div style={{ ...S.label, marginTop: 10 }}>{t('session.join.noSheetMatch')}</div>
                )}
              </div>
            )}
          </div>
        )}

        {f.error && <div style={S.error}>{f.error}</div>}

        <div style={S.actions}>
          <button style={S.cancelBtn} onClick={onClose}>{t('common.cancel')}</button>
          <button style={{ ...S.submitBtn, opacity: f.loading ? 0.6 : 1 }} onClick={submit} disabled={f.loading || !f.inviteCode.trim()}>
            {f.loading ? '...' : t('session.join.submit')}
          </button>
        </div>
      </div>
    </div>
  )
}
