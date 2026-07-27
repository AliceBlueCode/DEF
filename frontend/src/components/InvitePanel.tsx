import { useState } from 'react'
import { useT } from '../i18n'

type Props = {
  sessionId: string
  hostToken: string
}

const RATINGS = ['SFW', 'R15', 'R18', 'UNL'] as const
type Rating = typeof RATINGS[number]

const RATING_COLORS: Record<Rating, string> = {
  SFW: '#4caf50',
  R15: '#ff9800',
  R18: '#f44336',
  UNL: '#9c27b0',
}

export default function InvitePanel({ sessionId, hostToken }: Props) {
  const t = useT()
  const [rating, setRating] = useState<Rating>('SFW')
  const [inviteCode, setInviteCode] = useState('')
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  const issueCode = async () => {
    setLoading(true)
    try {
      const res = await fetch(`/api/session/${sessionId}/invite`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${hostToken}`,
        },
        body: JSON.stringify({ rating }),
      })
      if (!res.ok) throw new Error()
      const data = await res.json()
      setInviteCode(data.invite_code)
      setCopied(false)
    } catch {
      // エラーは表示しない（コードが空のままになる）
    } finally {
      setLoading(false)
    }
  }

  const copyCode = () => {
    if (!inviteCode) return
    navigator.clipboard.writeText(inviteCode).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="invite-panel">
      <div className="invite-rating-row">
        {RATINGS.map(r => (
          <button
            key={r}
            className={`invite-rating-btn${rating === r ? ' active' : ''}`}
            style={rating === r ? { borderColor: RATING_COLORS[r], color: RATING_COLORS[r] } : undefined}
            onClick={() => { setRating(r); setInviteCode('') }}
          >
            {r}
          </button>
        ))}
        <button className="invite-issue-btn" onClick={issueCode} disabled={loading}>
          {loading ? '...' : t('session.invite.issue')}
        </button>
      </div>
      {inviteCode && (
        <div className="invite-code-row">
          <span className="invite-code" style={{ color: RATING_COLORS[rating] }}>{inviteCode}</span>
          <button className="invite-copy-btn" onClick={copyCode}>
            {copied ? t('session.invite.copied') : t('session.invite.copy')}
          </button>
        </div>
      )}
    </div>
  )
}
