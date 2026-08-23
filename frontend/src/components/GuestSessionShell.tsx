import type { JoinResult } from './useJoinFlow'
import SessionTab from './SessionTab'
import '../GuestOnboarding.css'

const LS_KEY_THEME = 'def_theme'
function readTheme(): 'dark' | 'light' {
  try { return (localStorage.getItem(LS_KEY_THEME) as 'dark' | 'light') || 'light' } catch { return 'light' }
}

type Props = { initialJoinResult?: JoinResult }

// join直後（initialJoinResultを渡す、GuestOnboardingFlow.tsx経由）・リロード復帰
// （initialJoinResultなし、SessionTab自身のsessionStorage復帰effectに委ねる、
// GuestGate.tsx経由）の両方から使う、サイドバー・他タブを持たないゲスト専用の
// 最小シェル（2026-08-23）。characters/backend/ttsBackend/t2iBackendは公開ポート
// 経由のゲストが従来から得ていた値（常に空）と同じで、SessionTab側は元々この
// 空props耐性を前提に設計されている。
export default function GuestSessionShell({ initialJoinResult }: Props) {
  const themeClass = readTheme() === 'light' ? ' light-mode' : ''
  return (
    <div className={`guest-session-shell${themeClass}`}>
      <SessionTab characters={[]} backend="" ttsBackend="" t2iBackend="" initialJoinResult={initialJoinResult} />
    </div>
  )
}
