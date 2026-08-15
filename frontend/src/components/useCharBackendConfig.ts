import { useState } from 'react'

// SessionTab.tsx から分離: キャラごとのLLMバックエンド・ゲームキャラシート・役割割り当て。
// `SessionTab.tsx`分割の第二段階（TODO.md「SessionTab.tsxのコンポーネント分割」参照）。
export function useCharBackendConfig() {
  const [charBackends, setCharBackends] = useState<Record<string, string>>({})
  const [llmBackendOptions, setLlmBackendOptions] = useState<{ id: string; label: string }[]>([])
  const [showBackendDialog, setShowBackendDialog] = useState(false)
  const [charGameSheets, setCharGameSheets] = useState<Record<string, string>>({})
  const [charGameSheetOptions, setCharGameSheetOptions] = useState<Record<string, string[]>>({})
  const [showGameSheetDialog, setShowGameSheetDialog] = useState(false)
  const [charRoles, setCharRoles] = useState<Record<string, 'investigator' | 'keeper'>>({})
  const keeperCharId = Object.entries(charRoles).find(([, r]) => r === 'keeper')?.[0] ?? ''
  const keeperCount = Object.values(charRoles).filter(r => r === 'keeper').length

  const openGameSheetDialog = async (selectedChars: string[]) => {
    const opts: Record<string, string[]> = {}
    await Promise.all(selectedChars.map(async id => {
      try {
        const res = await fetch(`/api/characters/${id}/game_sheets`)
        const data = await res.json()
        opts[id] = Object.keys(data.game_sheets ?? {})
      } catch {
        opts[id] = []
      }
    }))
    setCharGameSheetOptions(opts)
    setShowGameSheetDialog(true)
  }

  return {
    charBackends, setCharBackends,
    llmBackendOptions, setLlmBackendOptions,
    showBackendDialog, setShowBackendDialog,
    charGameSheets, setCharGameSheets,
    charGameSheetOptions, setCharGameSheetOptions,
    showGameSheetDialog, setShowGameSheetDialog,
    charRoles, setCharRoles,
    keeperCharId, keeperCount,
    openGameSheetDialog,
  }
}
