import { useState } from 'react'

// SessionTab.tsx から分離: ロビーのAI割付けウィザード（キャラ選択→ゲームキャラシート選択→LLM選択）。
// `SessionTab.tsx`分割の第二段階（TODO.md「SessionTab.tsxのコンポーネント分割」参照）。
// 確定処理（confirmAssignDialog、lobbyAddAi/lobbySetKeeperChar経由でinitiative等の
// 他ドメインを書き換える）はSessionTab本体に残す。
export function useAiAssignWizard() {
  const [assignDialogTarget, setAssignDialogTarget] = useState<'slot' | 'keeper' | null>(null)
  const [assignStep, setAssignStep] = useState<'char' | 'sheet' | 'backend'>('char')
  const [assignCharId, setAssignCharId] = useState('')
  const [assignSheetOptions, setAssignSheetOptions] = useState<string[]>([])
  const [assignSheetId, setAssignSheetId] = useState('')
  const [assignBackendId, setAssignBackendId] = useState('')

  const openAssignDialog = (target: 'slot' | 'keeper') => {
    setAssignDialogTarget(target)
    setAssignStep('char')
    setAssignCharId('')
    setAssignSheetOptions([])
    setAssignSheetId('')
    setAssignBackendId('')
  }

  const selectAssignChar = async (charId: string, lobbyTrpgMode: boolean) => {
    setAssignCharId(charId)
    if (lobbyTrpgMode && assignDialogTarget === 'slot') {
      try {
        const res = await fetch(`/api/characters/${charId}/game_sheets`)
        const data = await res.json()
        setAssignSheetOptions(Object.keys(data.game_sheets ?? {}))
      } catch {
        setAssignSheetOptions([])
      }
      setAssignStep('sheet')
    } else {
      setAssignStep('backend')
    }
  }

  return {
    assignDialogTarget, setAssignDialogTarget,
    assignStep, setAssignStep,
    assignCharId, setAssignCharId,
    assignSheetOptions, setAssignSheetOptions,
    assignSheetId, setAssignSheetId,
    assignBackendId, setAssignBackendId,
    openAssignDialog, selectAssignChar,
  }
}
