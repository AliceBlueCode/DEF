import { useEffect, useRef, useState } from 'react'
import { useT } from '../i18n'
import { useJoinFlow, type JoinResult, type Slot } from './useJoinFlow'
import { markGuestMode, readTheme } from './sessionUtils'
import TermsPanel from './TermsPanel'
import GuestSessionShell from './GuestSessionShell'
import '../GuestOnboarding.css'

type Step = 'invite' | 'terms' | 'char'

// 招待コードで参加するゲスト専用のオンボーディング画面。招待コード→TERMS同意→
// キャラ選択/持ち込みの3ステップを経て、join成功後はサイドバー・他タブを持たない
// 最小シェル（SessionTabのみ）へ遷移する（2026-08-23、TODO.md「参加者向けのTERMS
// 同意導線」の実装）。ゲスト判定自体（GuestGate.tsx）より下の階層で、判定後に
// 実際にマウントされる側。
export default function GuestOnboardingFlow() {
  const t = useT()
  const f = useJoinFlow()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [step, setStep] = useState<Step>('invite')
  const [termsChecked, setTermsChecked] = useState(false)
  const [joinResult, setJoinResult] = useState<JoinResult | null>(null)
  const [inviteError, setInviteError] = useState('')
  const themeClass = readTheme() === 'light' ? ' light-mode' : ''

  // ステップを移動するたびに前のステップで出たエラー（例: char画面での
  // 「JSON未選択」エラー）を持ち越さない。join()自体は新規呼び出し時にしか
  // f.errorをクリアしないため、「戻る→また進む」だけでは消えず、何もしていない
  // のに古いエラーが再表示されていた（2026-09-06、リリース前レビューで発覚）。
  useEffect(() => {
    f.setError('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step])

  if (joinResult) {
    return <GuestSessionShell initialJoinResult={joinResult} />
  }

  const goToTerms = async () => {
    if (!f.inviteCode.trim() || f.loading) return
    setInviteError('')
    const data = await f.fetchSlots(f.inviteCode)
    // fetchSlotsは「同一コードを直前と重複取得しない」ための重複防止ガードとして
    // 意図的にnullを返すことがある（例: 「戻る」で招待コード画面に戻り、コードを
    // 変えずにもう一度「続ける」を押した場合）。この場合f.slotsLoadedは前回取得済み
    // のtrueのままなので、実際の失敗（無効なコード・通信エラー、いずれもnull返却と
    // 同時にslotsLoadedをfalseに落とす）と区別できる。区別せずnull即エラー扱いに
    // していると、正常な「戻る→再度続ける」操作がデッドエンドになっていた
    // （2026-09-06、リリース前レビューで発覚）。
    if (!data && !f.slotsLoaded) { setInviteError(t('session.join.errorFailed')); return }
    setStep('terms')
  }

  const submit = async () => {
    const result = await f.join()
    if (result) {
      markGuestMode()
      setJoinResult(result)
    }
  }

  return (
    <div className={`guest-onboarding-root${themeClass}`}>
    <div className="guest-onboarding">
      <h1 className="guest-onboarding-title">{t('guestOnboarding.title')}</h1>

      {step === 'invite' && (
        <div className="guest-onboarding-step">
          <h2>{t('guestOnboarding.stepInviteTitle')}</h2>
          <input
            className="guest-onboarding-input"
            placeholder="SFW-ABK-492"
            value={f.inviteCode}
            onChange={e => {
              f.setInviteCode(e.target.value)
              f.setSlotsLoaded(false)
              f.lastFetchedCode.current = ''
            }}
            onKeyDown={e => { if (e.key === 'Enter') void goToTerms() }}
            autoFocus
          />
          {inviteError && <div className="guest-onboarding-error">{inviteError}</div>}
          <button
            className="guest-onboarding-btn-primary"
            onClick={() => void goToTerms()}
            disabled={!f.inviteCode.trim() || f.loading}
          >
            {t('guestOnboarding.continueBtn')}
          </button>
        </div>
      )}

      {step === 'terms' && (
        <div className="guest-onboarding-step">
          <h2>{t('guestOnboarding.stepTermsTitle')}</h2>
          <TermsPanel checked={termsChecked} onCheckedChange={setTermsChecked} />
          <div className="guest-onboarding-actions">
            <button className="guest-onboarding-btn-secondary" onClick={() => setStep('invite')}>
              {t('guestOnboarding.backBtn')}
            </button>
            <button
              className="guest-onboarding-btn-primary"
              onClick={() => setStep('char')}
              disabled={!termsChecked}
              title={!termsChecked ? t('guestOnboarding.consentRequired') : undefined}
            >
              {t('guestOnboarding.continueBtn')}
            </button>
          </div>
        </div>
      )}

      {step === 'char' && (
        <div className="guest-onboarding-step">
          <h2>{t('guestOnboarding.stepCharTitle')}</h2>

          <div className="guest-onboarding-slots">
            <label className="guest-onboarding-slot-option">
              <input type="radio" name="slot" value="__observer__" checked={f.selectedSlot === '__observer__'} onChange={() => f.setSelectedSlot('__observer__')} />
              <span>👁 {t('session.join.observerSlot')}</span>
            </label>

            {f.onlineMode ? (
              <>
                {f.waitingForGm && (
                  <label className="guest-onboarding-slot-option" style={{ opacity: f.gmTaken ? 0.4 : 1 }}>
                    <input type="radio" name="slot" value="__gm__" disabled={f.gmTaken} checked={f.selectedSlot === '__gm__'} onChange={() => !f.gmTaken && f.setSelectedSlot('__gm__')} />
                    <span>{t('session.join.gmSlot')}</span>
                    {f.gmTaken && <span className="guest-onboarding-badge">{t('session.join.gmTakenBadge')}</span>}
                  </label>
                )}
                <label className="guest-onboarding-slot-option">
                  <input type="radio" name="slot" value="__player__" checked={f.selectedSlot === '__player__'} onChange={() => f.setSelectedSlot('__player__')} />
                  <span>{t('session.join.playerSlot')}</span>
                </label>
              </>
            ) : (
              f.slots.map((slot: Slot) => (
                <label key={slot.char_id} className="guest-onboarding-slot-option" style={{ opacity: slot.available ? 1 : 0.4 }}>
                  <input
                    type="radio"
                    name="slot"
                    value={slot.char_id}
                    disabled={!slot.available}
                    checked={f.selectedSlot === slot.char_id}
                    onChange={() => slot.available && f.setSelectedSlot(slot.char_id)}
                  />
                  <span>🎭 {slot.char_name}</span>
                  {!slot.available && <span className="guest-onboarding-badge">{t('session.join.slotTaken')}</span>}
                </label>
              ))
            )}
          </div>

          {f.onlineMode && f.selectedSlot === '__player__' && (
            <div className="guest-onboarding-charjson">
              <div className="guest-onboarding-label">{t('session.join.charJsonLabel')}</div>
              <input ref={fileInputRef} type="file" accept=".json" style={{ display: 'none' }} onChange={f.handleFileSelect} />
              <button type="button" className="guest-onboarding-btn-secondary" onClick={() => fileInputRef.current?.click()}>
                {f.charJsonName ? `✓ ${f.charJsonName}` : t('session.join.selectJsonBtn')}
              </button>
              {f.trpgMode && f.charJson && f.sheetOptions.length > 0 && (
                <div className="guest-onboarding-sheet">
                  <div className="guest-onboarding-label">{t('session.join.sheetLabel')}</div>
                  <select className="guest-onboarding-input" value={f.selectedSheetId} onChange={e => f.setSelectedSheetId(e.target.value)}>
                    <option value="">{t('trpg.gameChar.noSheet')}</option>
                    {f.sheetOptions.map(sid => <option key={sid} value={sid}>{sid}</option>)}
                  </select>
                </div>
              )}
              {f.trpgMode && f.charJson && f.sheetOptions.length === 0 && (
                <div className="guest-onboarding-label">{t('session.join.noSheetMatch')}</div>
              )}
            </div>
          )}

          {f.error && <div className="guest-onboarding-error">{f.error}</div>}

          <div className="guest-onboarding-actions">
            <button className="guest-onboarding-btn-secondary" onClick={() => setStep('terms')}>
              {t('guestOnboarding.backBtn')}
            </button>
            <button className="guest-onboarding-btn-primary" onClick={() => void submit()} disabled={f.loading}>
              {f.loading ? '...' : t('session.join.submit')}
            </button>
          </div>
        </div>
      )}
    </div>
    </div>
  )
}
