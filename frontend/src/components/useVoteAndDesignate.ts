import { useState } from 'react'

// SessionTab.tsx から分離: 投票ダイアログ・次発言者指名の状態。
// `SessionTab.tsx`分割の第二段階（TODO.md「SessionTab.tsxのコンポーネント分割」参照）。
// 実際の投票開始/確定処理（startDeliberation・commitVote）はmessages・counters・
// endSession等の複数ドメインにまたがるため、SessionTab本体に残す。
export function useVoteAndDesignate() {
  const [designateTarget, setDesignateTarget] = useState('')
  const [showVoteDialog, setShowVoteDialog] = useState(false)
  const [voteType, setVoteType] = useState<'topic_change' | 'expel' | 'end_session'>('topic_change')
  const [voteDetail, setVoteDetail] = useState('')
  const [voteTarget, setVoteTarget] = useState('')
  const [voteProposerText, setVoteProposerText] = useState('')
  const [voteLoading, setVoteLoading] = useState(false)

  return {
    designateTarget, setDesignateTarget,
    showVoteDialog, setShowVoteDialog,
    voteType, setVoteType,
    voteDetail, setVoteDetail,
    voteTarget, setVoteTarget,
    voteProposerText, setVoteProposerText,
    voteLoading, setVoteLoading,
  }
}
