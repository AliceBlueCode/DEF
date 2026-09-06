import { useEffect, useState } from 'react'
import { useT } from '../i18n'
import { renderTermsMarkdown } from './miniMarkdown'

type Props = {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}

export default function TermsPanel({ checked, onCheckedChange }: Props) {
  const t = useT()
  const [content, setContent] = useState('')
  const [error, setError] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetch('/api/terms')
      .then(r => { if (!r.ok) throw new Error('bad status'); return r.json() })
      .then(data => { if (!cancelled) setContent(data.content ?? '') })
      .catch(() => { if (!cancelled) setError(true) })
    return () => { cancelled = true }
  }, [])

  // 規約本文が読み込めていない間はチェックボックス自体を無効化する。読み込み失敗時
  // （error）は当然、まだ取得中（contentが空でerrorでもない）の間も、規約を実際に
  // 読める前に同意できてしまうのを防ぐ（2026-09-06、リリース前レビューで発覚:
  // /api/terms失敗時もチェックボックスが押せてしまい、規約を一度も見ずに
  // 「読み、同意しました」を成立させられた）。
  const canConsent = !error && content.length > 0
  useEffect(() => {
    if (!canConsent && checked) onCheckedChange(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canConsent])

  return (
    <div className="guest-terms-panel">
      <div className="guest-terms-scroll">
        {error ? (
          <p className="guest-terms-error">{t('guestOnboarding.termsLoadFailed')}</p>
        ) : content.length === 0 ? (
          <p className="guest-terms-loading">{t('guestOnboarding.loading')}</p>
        ) : (
          renderTermsMarkdown(content)
        )}
      </div>
      <label className="guest-terms-consent" style={canConsent ? undefined : { opacity: 0.5, cursor: 'not-allowed' }}>
        <input
          type="checkbox"
          checked={checked}
          disabled={!canConsent}
          onChange={e => onCheckedChange(e.target.checked)}
        />
        <span>{t('guestOnboarding.consentCheckbox')}</span>
      </label>
    </div>
  )
}
