import { useT } from '../i18n'

export type Participant = {
  char_id: string
  display_name: string
  role: 'host' | 'player' | 'observer'
  connected: boolean
}

type Props = {
  participants: Participant[]
}

const ROLE_BADGE: Record<Participant['role'], string> = {
  host: '👑',
  player: '🎭',
  observer: '👁',
}

export default function ParticipantList({ participants }: Props) {
  const t = useT()
  if (participants.length === 0) return null

  return (
    <div className="participant-list">
      <div className="participant-list-title">{t('session.participants.title')}</div>
      {participants.map(p => (
        <div key={p.char_id} className={`participant-row${p.connected ? '' : ' disconnected'}`}>
          <span className="participant-role">{ROLE_BADGE[p.role]}</span>
          <span className="participant-name">{p.display_name}</span>
          {!p.connected && (
            <span className="participant-status">{t('session.participants.disconnected')}</span>
          )}
        </div>
      ))}
    </div>
  )
}
