import { useEffect, useState } from 'react'

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

const JOIN_URL_STORAGE_KEY = 'def_join_url'

export default function InvitePanel({ defaultCode, sessionId, hostToken, onCodeChanged }: Props) {
  const [rating, setRating] = useState<Rating>('SFW')
  const [inviteCode, setInviteCode] = useState(defaultCode)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [joinUrl, setJoinUrl] = useState(() => localStorage.getItem(JOIN_URL_STORAGE_KEY) ?? '')
  const [urlCopied, setUrlCopied] = useState(false)

  const updateJoinUrl = (url: string) => {
    setJoinUrl(url)
    localStorage.setItem(JOIN_URL_STORAGE_KEY, url)
  }

  useEffect(() => {
    // dual_run.py --cloudflare-tunnel がcloudflaredを自動起動していれば、検出済みの
    // Quick Tunnel URLをここで拾える。手入力で別ドメイン（Named Tunnel等）を設定済みの
    // 場合を上書きしないよう、backendが実際にURLを検出できた時だけ反映する。
    fetch('/api/tunnel_url')
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data?.url) updateJoinUrl(data.url)
      })
      .catch(() => {})
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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

  const copyJoinUrl = () => {
    if (!joinUrl) return
    navigator.clipboard.writeText(joinUrl).then(() => {
      setUrlCopied(true)
      setTimeout(() => setUrlCopied(false), 2000)
    })
  }

  const rowStyle: React.CSSProperties = { display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }
  const fieldBoxStyle: React.CSSProperties = { flex: 1, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--border-color, #ccc)', background: 'transparent', color: 'inherit', fontSize: '0.85em' }
  const copyBtnStyle = (enabled: boolean): React.CSSProperties => ({
    padding: '6px 12px', borderRadius: 8, border: '1px solid var(--border-color, #ccc)',
    background: 'transparent', color: 'inherit', cursor: enabled ? 'pointer' : 'default',
    fontSize: '0.85em', whiteSpace: 'nowrap',
  })

  return (
    <div className="invite-panel">
      <div className="invite-url-row" style={rowStyle}>
        <input
          type="text"
          value={joinUrl}
          onChange={e => updateJoinUrl(e.target.value)}
          placeholder="参加用URL（例: https://xxxx.trycloudflare.com）"
          style={fieldBoxStyle}
        />
        <button className="invite-copy-btn" onClick={copyJoinUrl} disabled={!joinUrl} style={copyBtnStyle(!!joinUrl)}>
          {urlCopied ? '✓ コピー済み' : 'URLコピー'}
        </button>
      </div>
      <div className="invite-rating-row" style={{ ...rowStyle, gap: 6 }}>
        {RATINGS.map(r => {
          const active = rating === r
          return (
            <button
              key={r}
              className={`invite-rating-btn${active ? ' active' : ''}`}
              onClick={() => void switchRating(r)}
              disabled={loading}
              style={{
                padding: '6px 14px', borderRadius: 8,
                border: `1px solid ${active ? RATING_COLORS[r] : 'var(--border-color, #ccc)'}`,
                background: active ? `${RATING_COLORS[r]}1a` : 'transparent',
                color: active ? RATING_COLORS[r] : 'inherit',
                fontWeight: active ? 600 : 400, fontSize: '0.85em',
                cursor: loading ? 'default' : 'pointer',
              }}
            >
              {r}
            </button>
          )
        })}
      </div>
      <div className="invite-code-row" style={rowStyle}>
        <span
          className="invite-code"
          style={{ ...fieldBoxStyle, fontWeight: 700, letterSpacing: '0.05em', color: loading ? 'var(--text-muted, #888)' : RATING_COLORS[rating] }}
        >
          {loading ? '...' : inviteCode}
        </span>
        <button className="invite-copy-btn" onClick={copy} disabled={loading || !inviteCode} style={copyBtnStyle(!loading && !!inviteCode)}>
          {copied ? '✓ コピー済み' : 'コピー'}
        </button>
      </div>
    </div>
  )
}
