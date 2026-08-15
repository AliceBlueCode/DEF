import { useRef, useState } from 'react'

export type KeeperJudgment = { character_id: string; character_name: string; stat: string; stat_value: number; damage_on?: 'failure' | 'fumble' | 'any' }

// SessionTab.tsx から分離: TRPGキャラシート・ダイスダイアログ・判定キュー。
// `SessionTab.tsx`分割の第二段階（TODO.md「SessionTab.tsxのコンポーネント分割」参照）。
export function useCharSheetAndDice() {
  const [charSheetData, setCharSheetData] = useState<Record<string, any>>({})
  const [showSheetPanel, setShowSheetPanel] = useState(false)
  const [showDiceDialog, setShowDiceDialog] = useState(false)
  const [diceDialogChars, setDiceDialogChars] = useState<string[]>([])
  const [diceDialogLocked, setDiceDialogLocked] = useState(false)
  const [diceDialogStatKey, setDiceDialogStatKey] = useState('')
  const [diceDialogSkillKey, setDiceDialogSkillKey] = useState('')
  const [autoJudgmentStat, setAutoJudgmentStat] = useState('')
  const autoJudgmentStatRef = useRef('')
  const [pendingJudgments, setPendingJudgments] = useState<KeeperJudgment[]>([])

  const openDiceDialog = (initiative: string[]) => {
    const withSheet = initiative.filter(id => charSheetData[id])
    setDiceDialogChars(withSheet)
    setDiceDialogLocked(false)
    setShowDiceDialog(true)
  }

  const openDiceDialogForHuman = (humanCharId: string) => {
    setDiceDialogChars(humanCharId ? [humanCharId] : [])
    setDiceDialogLocked(true)
    setShowDiceDialog(true)
  }

  const isCharDead = (charId: string, sheetOverride?: Record<string, any>): boolean => {
    const sheet = (sheetOverride ?? charSheetData)[charId]
    if (!sheet?.stats) return false
    return Object.values(sheet.stats as Record<string, { current: number }>).some(s => s.current <= 0)
  }

  const shouldApplyDamage = (judgment: { success?: boolean; fumble?: boolean; critical?: boolean } | null | undefined, damageOn?: string): boolean => {
    if (!judgment) return false
    if (!damageOn) return !!judgment.fumble
    if (damageOn === 'fumble') return !!judgment.fumble
    if (damageOn === 'failure') return !judgment.success
    if (damageOn === 'any') return true
    return !!judgment.fumble
  }

  const normalizeSheetStats = (sheet: any): any => {
    if (!sheet?.stats) return sheet
    const stats: Record<string, any> = {}
    for (const [k, v] of Object.entries(sheet.stats)) {
      if (typeof v === 'number') {
        stats[k] = { current: v, max: v }
      } else {
        stats[k] = v
      }
    }
    return { ...sheet, stats }
  }

  return {
    charSheetData, setCharSheetData,
    showSheetPanel, setShowSheetPanel,
    showDiceDialog, setShowDiceDialog,
    diceDialogChars, setDiceDialogChars,
    diceDialogLocked, setDiceDialogLocked,
    diceDialogStatKey, setDiceDialogStatKey,
    diceDialogSkillKey, setDiceDialogSkillKey,
    autoJudgmentStat, setAutoJudgmentStat, autoJudgmentStatRef,
    pendingJudgments, setPendingJudgments,
    openDiceDialog, openDiceDialogForHuman,
    isCharDead, shouldApplyDamage, normalizeSheetStats,
  }
}
