import { useRef, useState } from 'react'

// SessionTab.tsx から分離: ターン進行状態（ラウンド・イニシアティブ・自動進行・カウンター）。
// `SessionTab.tsx`分割の第二段階（TODO.md「SessionTab.tsxのコンポーネント分割」参照）。
export function useTurnState() {
  const [round, setRound] = useState(1)
  const [currentSceneIndex, setCurrentSceneIndex] = useState(0)
  const [activeTurnCharId, setActiveTurnCharId] = useState('')
  const [initiative, setInitiative] = useState<string[]>([])
  const initiativeRef = useRef<string[]>([])
  const [autoAdvance, setAutoAdvance] = useState(false)
  const autoAdvanceRef = useRef(false)
  const [autoStopMsg, setAutoStopMsg] = useState<string | null>(null)
  const [actionsPerTurn, setActionsPerTurn] = useState(0)
  const actionsPerTurnRef = useRef(0)
  const [counters, setCounters] = useState<Record<string, number>>({})
  const [maxCounter, setMaxCounter] = useState(5)
  const maxCounterRef = useRef(5)
  const [loading, setLoading] = useState(false)
  const [sceneImageStatus, setSceneImageStatus] = useState<'idle' | 'generating' | 'error'>('idle')
  const [standingFallback, setStandingFallback] = useState<Set<string>>(new Set())
  const wasAutoAdvancingRef = useRef(false)
  const keeperFiredRoundRef = useRef(0)

  const capCounters = (c: Record<string, number>) =>
    Object.fromEntries(Object.entries(c).map(([k, v]) => [k, Math.min(v, maxCounterRef.current)]))

  return {
    round, setRound,
    currentSceneIndex, setCurrentSceneIndex,
    activeTurnCharId, setActiveTurnCharId,
    initiative, setInitiative, initiativeRef,
    autoAdvance, setAutoAdvance, autoAdvanceRef,
    autoStopMsg, setAutoStopMsg,
    actionsPerTurn, setActionsPerTurn, actionsPerTurnRef,
    counters, setCounters,
    maxCounter, setMaxCounter, maxCounterRef,
    loading, setLoading,
    sceneImageStatus, setSceneImageStatus,
    standingFallback, setStandingFallback,
    wasAutoAdvancingRef, keeperFiredRoundRef,
    capCounters,
  }
}
