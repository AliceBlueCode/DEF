import { useRef, useState } from 'react'

// SessionTab.tsx から分離: 人間プレイヤー/人間キーパーのターン入力状態。
// `SessionTab.tsx`分割の第二段階（TODO.md「SessionTab.tsxのコンポーネント分割」参照）。
export function useHumanTurn() {
  const [humanKeeper, setHumanKeeper] = useState(false)
  const [waitingForKeeperTurn, setWaitingForKeeperTurn] = useState(false)
  const isHumanKeeperRef = useRef(false)
  const [keeperInput, setKeeperInput] = useState('')
  const [pendingActions, setPendingActions] = useState<string[]>([])
  const [waitingForHuman, setWaitingForHuman] = useState(false)
  const [humanCharId, setHumanCharId] = useState('')
  const [humanCharName, setHumanCharName] = useState('')
  const [humanInput, setHumanInput] = useState('')
  const [humanPending, setHumanPending] = useState<string[]>([])
  const [interruptMode, setInterruptMode] = useState(false)
  const [hasDiscarded, setHasDiscarded] = useState(false)

  // actionsPerTurnRef は useTurnState 側が正本（呼び出し元から渡す）。
  const addKeeperAction = (actionsPerTurnRef: React.RefObject<number>) => {
    if (!keeperInput.trim()) return
    if (actionsPerTurnRef.current > 0 && pendingActions.length >= actionsPerTurnRef.current) return
    setPendingActions(prev => [...prev, keeperInput.trim()])
    setKeeperInput('')
  }

  const addHumanAction = (actionsPerTurnRef: React.RefObject<number>) => {
    if (!humanInput.trim()) return
    if (actionsPerTurnRef.current > 0 && humanPending.length >= actionsPerTurnRef.current) return
    setHumanPending(prev => [...prev, humanInput.trim()])
    setHumanInput('')
  }

  return {
    humanKeeper, setHumanKeeper,
    waitingForKeeperTurn, setWaitingForKeeperTurn, isHumanKeeperRef,
    keeperInput, setKeeperInput,
    pendingActions, setPendingActions,
    waitingForHuman, setWaitingForHuman,
    humanCharId, setHumanCharId,
    humanCharName, setHumanCharName,
    humanInput, setHumanInput,
    humanPending, setHumanPending,
    interruptMode, setInterruptMode,
    hasDiscarded, setHasDiscarded,
    addKeeperAction, addHumanAction,
  }
}
