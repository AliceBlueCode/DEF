import { useEffect, useState, type ReactNode } from 'react'
import { isGuestMode } from './sessionUtils'
import GuestOnboardingFlow from './GuestOnboardingFlow'
import GuestSessionShell from './GuestSessionShell'

type Props = { children: ReactNode }

type Mode = 'checking' | 'host' | 'guestOnboarding' | 'guestActiveSession'

// 公開ポート（Cloudflare Tunnel経由の実ゲスト）とローカルポート（ホスト）を判定し、
// ゲストにはApp.tsx本来のサイドバー・7タブ構造（ゲストには無意味・公開ポートでは
// 404するAPIに依存する）を一切マウントせず、専用のオンボーディング画面/最小
// セッションシェルへ振り分ける（2026-08-23、TODO.md「参加者向けのTERMS同意導線」）。
//
// 判定順序:
//   1. def_guest_mode（GuestOnboardingFlowがjoin成功時にのみセットする）があれば、
//      probeせず即座にゲスト最小シェルへ（リロード復帰を高速化）。
//   2. 無ければ GET /api/settings/backends をprobe。ローカルポートのみ200になる
//      （公開ポートはsettings.routerを意図的にマウントしていないため404）。
//      ホストがローカルポートで自セッションにJoinDialog経由で追加参加する場合も
//      def_active_sessionはセットされるがdef_guest_modeはセットされないため、
//      このprobeにより正しく「ホスト」側と判定される。
export default function GuestGate({ children }: Props) {
  const [mode, setMode] = useState<Mode>(() => (isGuestMode() ? 'guestActiveSession' : 'checking'))

  useEffect(() => {
    if (mode !== 'checking') return
    let cancelled = false
    fetch('/api/settings/backends')
      .then(res => { if (!cancelled) setMode(res.ok ? 'host' : 'guestOnboarding') })
      .catch(() => { if (!cancelled) setMode('host') })  // 判定不能時は既存挙動（フルApp）を維持
    return () => { cancelled = true }
  }, [mode])

  if (mode === 'checking') return <div style={{ minHeight: '100vh', background: '#0e1117' }} />
  if (mode === 'guestActiveSession') return <GuestSessionShell />
  if (mode === 'guestOnboarding') return <GuestOnboardingFlow />
  return <>{children}</>
}
