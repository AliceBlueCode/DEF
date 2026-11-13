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

/** サーバーが返す参加者の一覧（GET の participants、WS の PARTICIPANTS_SNAPSHOT）を、画面の一覧に変える。
 *  切断中のままの参加者は、前に受け取ったスキップまでの秒数を引き継ぐ。 */
export function participantsFromServer(prev: Participant[], list: any[]): Participant[] {
  return list.map((p: any) => {
    const pid = p.participant_id || p.character_id
    const old = prev.find(x => x.participant_id === pid)
    return {
      participant_id: pid,
      char_id: p.character_id || '',
      display_name: p.display_name || '',
      role: p.role || 'player',
      connected: !!p.connected,
      claimed_char_id: p.claimed_char_id || '',
      disconnectTimeoutSec: p.connected ? undefined : old?.disconnectTimeoutSec,
    }
  })
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
