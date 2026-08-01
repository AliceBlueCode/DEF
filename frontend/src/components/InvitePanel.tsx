import { useState } from 'react'

type Props = {
  defaultCode: string
  sessionId: string
  hostToken: string
  onCodeChanged: (code: string) => void
}

const RATINGS = ['SFW', 'R15', 'R18', 'UNL'] as const
type Rating = typeof RATINGS[number]

const RATING_COLORS: Record<Rating, string> = {
  SFW: '#4caf50', R15: '#ff9800', R18: '#f44336', UNL: '#9c27b0',
}

export default function InvitePanel({ defaultCode, sessionId, hostToken, onCodeChanged }: Props) {
  const [rating, setRating] = useState<Rating>('SFW')
  const [inviteCode, setInviteCode] = useState(defaultCode)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  const switchRating = async (r: Rating) => {
    if (r === rating) return
    setRating(r)
    if (r === 'SFW' && defaultCode) {
      setInviteCode(defaultCode)
      onCodeChanged(defaultCode)
      return
    }
    setLoading(true)
    try {
      const res = await fetch(`/api/session/${sessionId}/invite`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${hostToken}` },
        body: JSON.stringify({ rating: r }),
      })
      if (res.ok) {
        const d = await res.json()
        if (d.invite_code) {
          setInviteCode(d.invite_code)
          onCodeChanged(d.invite_code)
        }
      }
    } catch {}
    finally { setLoading(false) }
  }

  const copy = () => {
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
            onClick={() => void switchRating(r)}
            disabled={loading}
          >
            {r}
          </button>
        ))}
      </div>
      <div className="invite-code-row">
        <span className="invite-code" style={{ color: loading ? 'var(--text-muted, #888)' : RATING_COLORS[rating], fontWeight: 700, letterSpacing: '0.05em' }}>
          {loading ? '...' : inviteCode}
        </span>
        <button className="invite-copy-btn" onClick={copy} disabled={loading || !inviteCode}>
          {copied ? '✓ コピー済み' : 'コピー'}
        </button>
      </div>
    </div>
  )
}
