import { useT } from '../i18n'

export type Participant = {
  participant_id: string   // 一意ID（char_idが空のobs/gmはサーバー生成値）
  char_id: string
  display_name: string
  role: 'host' | 'player' | 'observer' | 'gm'
  connected: boolean
  claimed_char_id?: string
  disconnectTimeoutSec?: number  // 切断中のみ。設計書§3.7「○○が切断中、N秒後にスキップ」の表示用
}

type Props = {
  participants: Participant[]
}

const ROLE_BADGE: Record<Participant['role'], string> = {
  host: '👑',
  player: '🎭',
  observer: '👁',
  gm: '🎩',
}

export default function ParticipantList({ participants }: Props) {
  const t = useT()
  if (participants.length === 0) return null

  return (
    <div className="participant-list">
      <div className="participant-list-title">{t('session.participants.title')}</div>
      {participants.map(p => (
        <div key={p.participant_id || p.char_id} className={`participant-row${p.connected ? '' : ' disconnected'}`}>
          <span className="participant-role">{ROLE_BADGE[p.role]}</span>
          <span className="participant-name">{p.display_name}</span>
          {!p.connected && (
            <span className="participant-status">
              {p.disconnectTimeoutSec
                ? t('session.participants.disconnectedWithTimeout', { sec: String(p.disconnectTimeoutSec) })
                : t('session.participants.disconnected')}
            </span>
          )}
        </div>
      ))}
    </div>
  )
}
