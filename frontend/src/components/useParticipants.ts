import { useRef, useState } from 'react'
import type { Participant } from './ParticipantList'

// SessionTab.tsx から分離: 参加者一覧・自分のロール・参加ダイアログ・アイコンバージョン。
// `SessionTab.tsx`分割の第二段階（TODO.md「SessionTab.tsxのコンポーネント分割」参照）。
export function useParticipants() {
  const [participants, setParticipants] = useState<Participant[]>([])
  const [showJoinDialog, setShowJoinDialog] = useState(false)
  const [myRole, setMyRole] = useState<'host' | 'player' | 'observer' | 'gm'>('host')
  const myRoleRef = useRef<'host' | 'player' | 'observer' | 'gm'>('host')
  const myCharIdRef = useRef('')  // このタブが担当するキャラID（オンライン対戦用）
  const [extraNameMap, setExtraNameMap] = useState<Record<string, string>>({})
  const [showParticipantPanel, setShowParticipantPanel] = useState(true)
  // 持ち込みキャラのアイコン/立ち絵がバックグラウンド生成完了した際、no-cacheな画像を再取得させるためのバージョン値
  const [iconVersion, setIconVersion] = useState<Record<string, number>>({})

  const iconUrl = (charId: string) => `/api/characters/${charId}/icon${iconVersion[charId] ? `?v=${iconVersion[charId]}` : ''}`
  const standingUrl = (charId: string) => `/api/characters/${charId}/standing${iconVersion[charId] ? `?v=${iconVersion[charId]}` : ''}`

  return {
    participants, setParticipants,
    showJoinDialog, setShowJoinDialog,
    myRole, setMyRole, myRoleRef,
    myCharIdRef,
    extraNameMap, setExtraNameMap,
    showParticipantPanel, setShowParticipantPanel,
    iconVersion, setIconVersion,
    iconUrl, standingUrl,
  }
}
