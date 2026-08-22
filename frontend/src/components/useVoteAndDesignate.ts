import { useState } from 'react'

// SessionTab.tsx から分離: 投票ダイアログ・次発言者指名の状態。
// `SessionTab.tsx`分割の第二段階（TODO.md「SessionTab.tsxのコンポーネント分割」参照）。
// 実際の投票開始/確定処理（startDeliberation・commitVote・castMyVote・
// resolveExpelFollowup）はmessages・counters・endSession等の複数ドメインにまたがるため、
// SessionTab本体に残す。
export function useVoteAndDesignate() {
  const [designateTarget, setDesignateTarget] = useState('')
  const [showVoteDialog, setShowVoteDialog] = useState(false)
  const [voteType, setVoteType] = useState<'topic_change' | 'expel' | 'end_session'>('topic_change')
  const [voteDetail, setVoteDetail] = useState('')
  const [voteTarget, setVoteTarget] = useState('')
  const [voteProposerText, setVoteProposerText] = useState('')
  const [voteLoading, setVoteLoading] = useState(false)
  // 非キーパー人間（弁明ラウンド対象者含む）が自分の意見を投じる際の自由記述入力
  const [castVoteText, setCastVoteText] = useState('')
  // expel可決後、キーパーの追加選択（続行/AI引き継ぎ）待ちの対象キャラ
  const [expelFollowupTarget, setExpelFollowupTarget] =
    useState<{ target_id: string; target_name: string } | null>(null)

  return {
    designateTarget, setDesignateTarget,
    showVoteDialog, setShowVoteDialog,
    voteType, setVoteType,
    voteDetail, setVoteDetail,
    voteTarget, setVoteTarget,
    voteProposerText, setVoteProposerText,
    voteLoading, setVoteLoading,
    castVoteText, setCastVoteText,
    expelFollowupTarget, setExpelFollowupTarget,
  }
}
