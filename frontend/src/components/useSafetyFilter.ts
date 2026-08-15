import { useRef, useState } from 'react'

// SessionTab.tsx から分離: コンテンツフィルタ（レーティング許容範囲）・監査警告・TTS有効設定。
// `SessionTab.tsx`分割の第二段階（TODO.md「SessionTab.tsxのコンポーネント分割」参照）。
export function useSafetyFilter() {
  const [allowedSexual, setAllowedSexual] = useState<string[]>(['sfw'])
  const [allowedViolence, setAllowedViolence] = useState<string[]>(['violence'])
  const [safetyLevel, setSafetyLevel] = useState('off')
  // WSイベントハンドラ(handleSessionEvent)はsessionId確定時に一度だけ張られるクロージャの
  // ため、その中で最新の安全設定を読むにはstateではなくrefが要る(ttsEnabledRefと同じ理由)。
  // 音声の自動再生をtags/レーティングでブロックする判定に使う。
  const allowedSexualRef = useRef<string[]>(['sfw'])
  const allowedViolenceRef = useRef<string[]>(['violence'])
  const safetyLevelRef = useRef('off')
  // 持ち込みキャラのLLM審査がfail-open（未実行のまま通過）になった場合の
  // ホスト/GM向け警告。CHARACTER_AUDIT_SKIPPED（WS）で追加、×で個別に消せる。
  const [auditWarnings, setAuditWarnings] = useState<{ id: string; characterId: string; reason: string }[]>([])
  const [, setTtsEnabled] = useState(false)
  const ttsEnabledRef = useRef(false)
  const ttsHumanEnabledRef = useRef(false)

  return {
    allowedSexual, setAllowedSexual, allowedSexualRef,
    allowedViolence, setAllowedViolence, allowedViolenceRef,
    safetyLevel, setSafetyLevel, safetyLevelRef,
    auditWarnings, setAuditWarnings,
    setTtsEnabled, ttsEnabledRef, ttsHumanEnabledRef,
  }
}
