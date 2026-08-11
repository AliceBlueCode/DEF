import { useState } from 'react'
import { useT } from '../i18n'

const RATING_COLORS: Record<string, string> = {
  SFW: '#4caf50', R15: '#ff9800', R18: '#f44336', UNL: '#9c27b0',
}

export default function InviteCodeDisplay({ inviteCode }: { inviteCode: string }) {
  const t = useT()
  const [copied, setCopied] = useState(false)
  const rating = inviteCode.split('-')[0] ?? 'SFW'

  const copy = () => {
    navigator.clipboard.writeText(inviteCode).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="invite-code-row">
      <span className="invite-code" style={{ color: RATING_COLORS[rating] ?? '#4caf50', fontWeight: 700, letterSpacing: '0.05em' }}>
        {inviteCode}
      </span>
      <button className="invite-copy-btn" onClick={copy}>
        {copied ? `✓ ${t('session.invite.copied')}` : t('session.invite.copy')}
      </button>
    </div>
  )
}
