// ルールブック・シナリオ・プラグインの manifest の `credit`（B-023）。
// 選ぶ画面とセッションの画面に出す。文はデータのまま出し、翻訳しない（権利者の書いた表記のため）。
import { useT } from '../i18n'

export function TrpgCredits({ credits, compact = false }: { credits: string[]; compact?: boolean }) {
  const t = useT()
  const list = credits.filter(c => c)
  if (list.length === 0) return null
  return (
    <div
      className="trpg-credits"
      style={{ fontSize: compact ? '0.72em' : '0.78em', opacity: 0.6, marginTop: compact ? 2 : 6, lineHeight: 1.5 }}
    >
      <span>{t('trpg.credits.label')}: </span>
      {list.map((c, i) => (
        <span key={i} style={{ whiteSpace: 'pre-wrap' }}>{i > 0 && ' / '}{c}</span>
      ))}
    </div>
  )
}

export function mergeCredits(...lists: (string[] | undefined)[]): string[] {
  const out: string[] = []
  for (const l of lists) for (const c of l ?? []) if (c && !out.includes(c)) out.push(c)
  return out
}
