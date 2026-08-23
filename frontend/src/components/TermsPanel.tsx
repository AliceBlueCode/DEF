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

  return (
    <div className="guest-terms-panel">
      <div className="guest-terms-scroll">
        {error ? (
          <p className="guest-terms-error">{t('guestOnboarding.termsLoadFailed')}</p>
        ) : (
          renderTermsMarkdown(content)
        )}
      </div>
      <label className="guest-terms-consent">
        <input
          type="checkbox"
          checked={checked}
          onChange={e => onCheckedChange(e.target.checked)}
        />
        <span>{t('guestOnboarding.consentCheckbox')}</span>
      </label>
    </div>
  )
}
