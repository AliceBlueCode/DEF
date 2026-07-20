import { useState, useEffect, useRef } from 'react'
import { useT } from '../i18n'

type Character = { id: string; name: string; image_color?: string; player_type?: string }

type SessionMessage = {
  character_id: string
  character_name: string
  text: string
  emotion: string
  tags: string[]
  imageColor?: string
  isHuman?: boolean
  isRevealed?: boolean
  isSceneImage?: boolean
  isKeeperVote?: boolean
  audioUrl?: string
  imageStatus?: 'generating' | 'done' | 'error'
  imageUrl?: string
  imageError?: string
  _genId?: string
}

type SavedSession = {
  filename: string
  topic: string
  saved_at: string
  round: number
  character_names: string[]
  trpg_scenario_title?: string
}

type Props = {
  characters: Character[]
  backend: string
  ttsBackend: string
  t2iBackend: string
}

const SEXUAL_TAGS = ['sfw', 'nsfw', 'hentai']
const VIOLENCE_TAGS = ['violence', 'gore', 'extreme']

function isContentBlocked(tags: string[], allowedSexual: string[], allowedViolence: string[]): boolean {
  return tags.some(tag =>
    (SEXUAL_TAGS.includes(tag) && !allowedSexual.includes(tag)) ||
    (VIOLENCE_TAGS.includes(tag) && !allowedViolence.includes(tag))
  )
}

// ── ダイスローラー（投票行の右に配置）────────────────────────
function DiceRow({ onOpenDialog, onAdvanceScene }: { onOpenDialog: () => void; onAdvanceScene?: () => void }) {
  const t = useT()
  return (
    <>
      <span style={{ flex: 1 }} />
      {onAdvanceScene && <button onClick={onAdvanceScene} className="keeper-add-btn" style={{ marginRight: 4 }}>{t('trpg.scene.advance')}</button>}
      <button onClick={onOpenDialog} className="keeper-add-btn">{t('trpg.dice.roll')}</button>
    </>
  )
}

// ── マルチセレクト ────────────────────────────────────────────
function CharMultiSelect({
  characters,
  selected,
  onChange,
}: {
  characters: Character[]
  selected: string[]
  onChange: (ids: string[]) => void
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const unselected = characters.filter(c => !selected.includes(c.id))
  const filtered = search
    ? unselected.filter(c => c.name.includes(search))
    : unselected

  const add = (id: string) => { onChange([...selected, id]); setSearch('') }
  const remove = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    onChange(selected.filter(s => s !== id))
  }

  return (
    <div className="char-multiselect" ref={ref}>
      <div className="char-multiselect-input" onClick={() => setOpen(true)}>
        {selected.map(id => {
          const c = characters.find(c => c.id === id)
          if (!c) return null
          return (
            <span key={id} className="char-tag" style={c.image_color ? { borderColor: c.image_color } : undefined}>
              <img src={`/api/characters/${id}/icon`} alt="" className="char-tag-icon" />
              {c.name}
              <button className="char-tag-remove" onClick={e => remove(id, e)}>×</button>
            </span>
          )
        })}
        <input
          className="char-multiselect-search"
          placeholder={selected.length === 0 ? t('session.setup.charSelect.placeholder') : ''}
          value={search}
          onChange={e => setSearch(e.target.value)}
          onFocus={() => setOpen(true)}
        />
      </div>
      {open && filtered.length > 0 && (
        <div className="char-multiselect-dropdown">
          {filtered.map(c => (
            <div key={c.id} className="char-option" onClick={() => add(c.id)}>
              <img src={`/api/characters/${c.id}/icon`} alt="" className="char-option-icon" />
              <span>{c.name}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── メインコンポーネント ──────────────────────────────────────
type RuleOption = { id: string; label: string }
type DirectiveOption = { id: string; label: string; rating: string; recommended_for: number[] }
type RulebookOption = { id: string; label: string; dice_system: string }
type ScenarioOption = { id: string; label: string; synopsis: string; rulebook_id: string }
type KeeperJudgment = { character_id: string; character_name: string; stat: string; stat_value: number; damage_on?: 'failure' | 'fumble' | 'any' }

export default function SessionTab({ characters, backend, ttsBackend, t2iBackend }: Props) {
  const t = useT()
  const [selectedChars, setSelectedChars] = useState<string[]>([])
  const [topic, setTopic] = useState('')
  const [ruleSet, setRuleSet] = useState('default')
  const [trpgMode, setTrpgMode] = useState(false)
  const trpgModeRef = useRef(false)
  const [rulebookOptions, setRulebookOptions] = useState<RulebookOption[]>([])
  const [selectedRulebook, setSelectedRulebook] = useState('')
  const [scenarioOptions, setScenarioOptions] = useState<ScenarioOption[]>([])
  const [selectedScenario, setSelectedScenario] = useState('')
  const [ruleOptions, setRuleOptions] = useState<RuleOption[]>([])
  const [directiveSet, setDirectiveSet] = useState('default')
  const [directiveOptions, setDirectiveOptions] = useState<DirectiveOption[]>([])
  const [sessionId, setSessionId] = useState('')
  const sessionIdRef = useRef('')
  const [messages, setMessages] = useState<SessionMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [sessionStarting, setSessionStarting] = useState(false)
  const [round, setRound] = useState(1)
  const [currentSceneIndex, setCurrentSceneIndex] = useState(0)
  const [activeTurnCharId, setActiveTurnCharId] = useState('')
  const [initiative, setInitiative] = useState<string[]>([])
  const initiativeRef = useRef<string[]>([])
  const [allowedSexual, setAllowedSexual] = useState<string[]>(['sfw'])
  const [allowedViolence, setAllowedViolence] = useState<string[]>(['violence'])
  const [safetyLevel, setSafetyLevel] = useState('off')
  const [autoAdvance, setAutoAdvance] = useState(false)
  const autoAdvanceRef = useRef(false)
  const [actionsPerTurn, setActionsPerTurn] = useState(0)
  const [sceneImageStatus, setSceneImageStatus] = useState<'idle' | 'generating' | 'error'>('idle')
  const actionsPerTurnRef = useRef(0)
  const [, setTtsEnabled] = useState(false)
  const ttsEnabledRef = useRef(false)
  const ttsHumanEnabledRef = useRef(false)
  const prefetchRef = useRef<any>(null)
  const [standingFallback, setStandingFallback] = useState<Set<string>>(new Set())
  const [savedSessions, setSavedSessions] = useState<SavedSession[]>([])
  const [saveStatus, setSaveStatus] = useState('')
  const [showRuleDialog, setShowRuleDialog] = useState(false)
  const [ruleDraft, setRuleDraft] = useState('')
  const [ruleEditId, setRuleEditId] = useState('')
  const [charBackends, setCharBackends] = useState<Record<string, string>>({})
  const [llmBackendOptions, setLlmBackendOptions] = useState<{ id: string; label: string }[]>([])
  const [showBackendDialog, setShowBackendDialog] = useState(false)
  const [charGameSheets, setCharGameSheets] = useState<Record<string, string>>({})
  const [charGameSheetOptions, setCharGameSheetOptions] = useState<Record<string, string[]>>({})
  const [showGameSheetDialog, setShowGameSheetDialog] = useState(false)
  const [charRoles, setCharRoles] = useState<Record<string, 'investigator' | 'keeper'>>({})
  const keeperCharId = Object.entries(charRoles).find(([, r]) => r === 'keeper')?.[0] ?? ''
  const keeperCount = Object.values(charRoles).filter(r => r === 'keeper').length
  const [humanKeeper, setHumanKeeper] = useState(false)
  const [waitingForKeeperTurn, setWaitingForKeeperTurn] = useState(false)
  const isHumanKeeperRef = useRef(false)
  const [keeperInput, setKeeperInput] = useState('')
  const [pendingActions, setPendingActions] = useState<string[]>([])
  const [counters, setCounters] = useState<Record<string, number>>({})
  const [maxCounter, setMaxCounter] = useState(5)
  const maxCounterRef = useRef(5)
  const [designateTarget, setDesignateTarget] = useState('')
  const [showVoteDialog, setShowVoteDialog] = useState(false)
  const [voteType, setVoteType] = useState<'topic_change' | 'expel' | 'end_session'>('topic_change')
  const [voteDetail, setVoteDetail] = useState('')
  const [voteTarget, setVoteTarget] = useState('')
  const [voteProposerText, setVoteProposerText] = useState('')
  const [voteLoading, setVoteLoading] = useState(false)
  const [waitingForHuman, setWaitingForHuman] = useState(false)
  const [humanCharId, setHumanCharId] = useState('')
  const [humanCharName, setHumanCharName] = useState('')
  const [humanInput, setHumanInput] = useState('')
  const [humanPending, setHumanPending] = useState<string[]>([])
  const [interruptMode, setInterruptMode] = useState(false)
  const [hasDiscarded, setHasDiscarded] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
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
  const wasAutoAdvancingRef = useRef(false)
  const keeperFiredRoundRef = useRef(0)

  const fetchSavedSessions = () => {
    fetch('/api/session/saved')
      .then(r => r.json())
      .then(d => setSavedSessions(d.sessions || []))
      .catch(() => {})
  }

  useEffect(() => {
    fetch('/api/settings')
      .then(r => r.json())
      .then(res => {
        const s = res.settings ?? res
        if (s.allowed_rating_sexual) setAllowedSexual(s.allowed_rating_sexual)
        if (s.allowed_rating_violence) setAllowedViolence(s.allowed_rating_violence)
        if (s.safety_level) setSafetyLevel(s.safety_level === 'warn' ? 'off' : s.safety_level)
        if (s.session_actions_per_turn) {
          setActionsPerTurn(s.session_actions_per_turn)
          actionsPerTurnRef.current = s.session_actions_per_turn
        }
        {
          const v = typeof s.session_max_counter === 'number' ? s.session_max_counter : 5
          setMaxCounter(v)
          maxCounterRef.current = v
        }
        {
          const v = 'tts_enabled' in s ? !!s.tts_enabled : true
          setTtsEnabled(v)
          ttsEnabledRef.current = v
        }
        if ('tts_human_enabled' in s) {
          ttsHumanEnabledRef.current = !!s.tts_human_enabled
        }
      })
      .catch(() => {})

    const onSettingsChange = (e: Event) => {
      const { key, value } = (e as CustomEvent).detail
      if (key === 'tts_enabled') {
        setTtsEnabled(!!value)
        ttsEnabledRef.current = !!value
      }
      if (key === 'tts_human_enabled') {
        ttsHumanEnabledRef.current = !!value
      }
      if (key === 'session_actions_per_turn' && value) {
        setActionsPerTurn(value)
        actionsPerTurnRef.current = value
      }
      if (key === 'session_max_counter' && value) {
        setMaxCounter(value)
        maxCounterRef.current = value
      }
      if (key === 'safety_level') setSafetyLevel(value === 'warn' ? 'off' : value)
    }
    window.addEventListener('def-settings-change', onSettingsChange)
    fetch('/api/session/rules')
      .then(r => r.json())
      .then(d => {
        if (d.rules?.length) {
          setRuleOptions(d.rules)
          setRuleSet(d.rules[0].id)
        }
      })
      .catch(() => {})
    fetch('/api/session/action-directives')
      .then(r => r.json())
      .then(d => {
        if (d.directives?.length) {
          setDirectiveOptions(d.directives)
        }
      })
      .catch(() => {})
    fetch('/api/trpg/rulebooks')
      .then(r => r.json())
      .then(d => {
        if (d.rulebooks?.length) {
          setRulebookOptions(d.rulebooks)
          setSelectedRulebook(d.rulebooks[0].id)
        }
      })
      .catch(() => {})
    fetch('/api/trpg/scenarios')
      .then(r => r.json())
      .then(d => {
        if (d.scenarios?.length) {
          setScenarioOptions(d.scenarios)
        }
      })
      .catch(() => {})
    fetch('/api/settings/backends')
      .then(r => r.json())
      .then(d => {
        const ids: string[] = d.llm?.backends ?? []
        const labels: Record<string, string> = d.llm?.labels ?? {}
        setLlmBackendOptions(ids.map(id => ({ id, label: labels[id] ?? id })))
      })
      .catch(() => {})
    fetchSavedSessions()
    return () => window.removeEventListener('def-settings-change', onSettingsChange)
  }, [])

  useEffect(() => {
    if (!directiveOptions.length || actionsPerTurn <= 1) return
    const filtered = directiveOptions.filter(d => d.recommended_for.length === 0 || d.recommended_for.includes(actionsPerTurn))
    if (!filtered.length) return
    const current = filtered.find(d => d.id === directiveSet)
    if (!current) setDirectiveSet(filtered[0].id)
  }, [actionsPerTurn, directiveOptions])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const charMap = Object.fromEntries(characters.map(c => [c.id, c]))

  const startSession = async () => {
    if (selectedChars.length < 1) return
    setSessionStarting(true)
    try {
      const res = await fetch('/api/session/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character_ids: selectedChars, topic: trpgMode ? '' : topic, backend, rule_set: trpgMode ? 'none' : ruleSet, action_directive_set: directiveSet, actions_per_turn: actionsPerTurn, char_backends: charBackends, trpg_mode: trpgMode, trpg_rulebook: trpgMode ? selectedRulebook : '', trpg_scenario: trpgMode ? selectedScenario : '', char_game_sheets: trpgMode ? charGameSheets : {}, keeper_char_id: trpgMode ? keeperCharId : '', human_keeper: trpgMode ? humanKeeper : false }),
      })
      const data = await res.json()
      sessionIdRef.current = data.session_id
      setSessionId(data.session_id)
      trpgModeRef.current = trpgMode
      initiativeRef.current = data.initiative || []
      setInitiative(data.initiative || [])
      setMessages([])
      setRound(1)
      setCurrentSceneIndex(0)
      setActiveTurnCharId('')
      setCounters({})
      keeperFiredRoundRef.current = 0
      isHumanKeeperRef.current = data.human_keeper || false
      setWaitingForKeeperTurn(false)
      setPendingJudgments([])
      setStandingFallback(new Set())
      setWaitingForHuman(false)
      const humanChar = characters.find(c => selectedChars.includes(c.id) && c.player_type === 'human')
      setHumanCharId(humanChar?.id ?? '')
      setHumanCharName(humanChar?.name ?? '')
      if (trpgMode && Object.keys(charGameSheets).length > 0) {
        const sheetData: Record<string, any> = {}
        await Promise.all(
          Object.entries(charGameSheets).map(async ([charId, sheetId]) => {
            try {
              const r = await fetch(`/api/characters/${charId}/game_sheets`)
              const d = await r.json()
              if (d.game_sheets?.[sheetId]) sheetData[charId] = normalizeSheetStats({ ...d.game_sheets[sheetId], _sheet_id: sheetId })
            } catch {}
          })
        )
        setCharSheetData(sheetData)
      }
      const firstCharId = (data.initiative || [])[0]
      if (humanChar && firstCharId === humanChar.id) {
        // 人間が先頭: nextTurn を呼ばず直接入力待ちに
        setWaitingForHuman(true)
        setHasDiscarded(false)
      } else if (autoAdvanceRef.current) {
        setTimeout(() => nextTurn(data.session_id, actionsPerTurnRef.current), 200)
      }
    } catch (e) {
      console.error(e)
    } finally {
      setSessionStarting(false)
    }
  }

  const generateTTSUrl = async (text: string, characterId: string): Promise<string | null> => {
    if (!ttsEnabledRef.current || !ttsBackend) return null
    try {
      const res = await fetch('/api/tts/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, character_id: characterId, backend: ttsBackend }),
      })
      if (!res.ok) return null
      const blob = await res.blob()
      const form = new FormData()
      form.append('file', blob, 'audio.wav')
      const saveRes = await fetch('/api/tts/save', { method: 'POST', body: form })
      const saveData = await saveRes.json()
      return saveData.url as string
    } catch (e) {
      console.error('TTS generate error:', e)
      return null
    }
  }

  const generateImage = async (prompt: string, msgIndex: number) => {
    if (!t2iBackend) return
    setMessages(prev => prev.map((m, i) => i === msgIndex ? { ...m, imageStatus: 'generating' } : m))
    try {
      const res = await fetch('/api/t2i/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, backend: t2iBackend }),
      })
      const data = await res.json()
      if (data.error) {
        setMessages(prev => prev.map((m, i) => i === msgIndex ? { ...m, imageStatus: 'error', imageError: data.error } : m))
      } else {
        setMessages(prev => prev.map((m, i) => i === msgIndex ? { ...m, imageStatus: 'done', imageUrl: data.url } : m))
      }
    } catch (e) {
      setMessages(prev => prev.map((m, i) => i === msgIndex ? { ...m, imageStatus: 'error', imageError: String(e) } : m))
    }
  }

  const playAudio = (url: string): Promise<void> =>
    new Promise(resolve => {
      const audio = new Audio(url)
      audio.onended = () => resolve()
      audio.onerror = () => resolve()
      audio.play().catch(() => resolve())
    })

  const fetchNextData = (sid: string) =>
    fetch('/api/session/next', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sid, backend }),
    }).then(r => r.json()).catch(() => null)

  const nextTurn = async (sessionIdOverride?: string, batchRemaining?: number) => {
    if (!sessionIdRef.current) return
    const sid = sessionIdOverride ?? sessionId
    if (!sid) return
    const rem = batchRemaining ?? actionsPerTurnRef.current
    setLoading(true)
    try {
      // 先読みデータがあればそれを使い、なければ API 呼び出し
      let data: any
      if (prefetchRef.current) {
        data = prefetchRef.current
        prefetchRef.current = null
      } else {
        data = await fetchNextData(sid)
      }
      if (!data || data.error) { console.error(data?.error); return }

      if (data.counters) setCounters(capCounters(data.counters))
      if (data.character_id) setActiveTurnCharId(data.character_id)

      // 人間プレイヤーのターン
      if (data.waiting_for_human) {
        if (autoAdvanceRef.current) {
          wasAutoAdvancingRef.current = true
          setAutoAdvance(false)
          autoAdvanceRef.current = false
        }
        if (typeof data.round === 'number') setRound(data.round)
        setWaitingForHuman(true)
        setHasDiscarded(false)
        setHumanCharId(data.character_id)
        setHumanCharName(data.character_name)
        return
      }

      // スキップ（自動 or 自発）
      // counter_before < 0 なら強制スキップ、>= 0 なら自発スキップ
      if (data.skipped) {
        setRound(data.round)
        const ctrB: number | null = typeof data.counter_before === 'number' ? data.counter_before : null
        const isForced = ctrB !== null && ctrB < 0
        const skipText = isForced
          ? `⏭ ${data.character_name} は発言力不足のためスキップ [${ctrB}→${(ctrB as number) + 1}]`
          : ctrB !== null
            ? `⏭ ${data.character_name} はスキップ（発言力 ${ctrB}→${ctrB + 1}）`
            : t('session.msg.humanSkip', { name: data.character_name })
        setMessages(prev => [...prev, {
          character_id: '_keeper',
          character_name: '⚙ System',
          text: skipText,
          emotion: '', tags: [],
        }])
        if (rem > 0 || autoAdvanceRef.current) {
          setTimeout(() => nextTurn(sid, rem), 200)
        }
        return
      }

      // AI による投票発議
      if (data.action === 'vote_proposal') {
        if (data.counters) setCounters(capCounters(data.counters))
        setMessages(prev => [...prev, {
          character_id: '_keeper',
          character_name: '⚙ System',
          text: `🗳 ${data.character_name} が投票を発議 [発言力-3]`,
          emotion: '', tags: [],
        }])
        try {
          const delibRes = await fetch(`/api/session/${sid}/vote/deliberate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              vote_type: data.vote_type || 'topic_change',
              detail: data.vote_detail || '',
              target_id: '',
              proposer_id: data.character_id,
              proposer_text: data.proposer_text || '',
            }),
          })
          const delibData = await delibRes.json()
          if (delibData.counters) setCounters(capCounters(delibData.counters))
          if (delibData.deliberations && Array.isArray(delibData.deliberations)) {
            for (const d of delibData.deliberations as { character_id: string; character_name: string; text: string; emotion: string }[]) {
              setMessages(prev => [...prev, {
                character_id: d.character_id,
                character_name: d.character_name,
                text: d.text,
                emotion: d.emotion,
                tags: [],
              }])
            }
          }
          setMessages(prev => [...prev, {
            character_id: '_keeper',
            character_name: 'GM',
            text: `${data.character_name} の投票提案: ${data.vote_detail || data.vote_type || ''}`,
            emotion: '', tags: [],
            isKeeperVote: true,
          }])
          // キーパーが決断するまで自動進行を一時停止
          wasAutoAdvancingRef.current = autoAdvanceRef.current
          setAutoAdvance(false)
          autoAdvanceRef.current = false
        } catch (e) {
          console.error(e)
        }
        return
      }

      // TRPGモード: ラウンド末尾キャラ判定（このキャラが喋り終えたらキーパーを発火）
      const isLastOfRound = trpgModeRef.current && initiativeRef.current.length > 0 &&
        initiativeRef.current[initiativeRef.current.length - 1] === data.character_id

      const char = charMap[data.character_id]
      let newMsgIndex = -1
      setMessages(prev => {
        newMsgIndex = prev.length
        return [...prev, {
          character_id: data.character_id,
          character_name: data.character_name,
          text: data.text,
          emotion: data.emotion,
          tags: data.tags || [],
          imageColor: char?.image_color ?? undefined,
        }]
      })
      setRound(data.round)

      if (data.penalty_message) {
        setMessages(prev => [...prev, {
          character_id: '_keeper',
          character_name: '⚙ System',
          text: data.penalty_message,
          emotion: '', tags: [],
        }])
      }

      if (data.ai_action === 'extend') {
        const ctr = data.counters?.[data.character_id]
        const ctrStr = typeof ctr === 'number' ? ` → 残${ctr}` : ''
        setMessages(prev => [...prev, {
          character_id: '_keeper',
          character_name: '⚙ System',
          text: `⚡ ${data.character_name} が力強く発言 [発言力-1${ctrStr}]`,
          emotion: '', tags: [],
        }])
      }

      if (data.ai_action === 'designate' && data.designated_name) {
        const ctr = data.counters?.[data.character_id]
        const ctrStr = typeof ctr === 'number' ? ` → 残${ctr}` : ''
        setMessages(prev => [...prev, {
          character_id: '_keeper',
          character_name: '⚙ System',
          text: `👉 ${data.character_name} が ${data.designated_name} を指名 [発言力-1${ctrStr}]`,
          emotion: '', tags: [],
        }])
      }

      // T2I 生成（非同期・ノンブロッキング）
      if (data.image_prompt_en && t2iBackend && newMsgIndex >= 0) {
        generateImage(data.image_prompt_en, newMsgIndex)
      }

      const nextRem = rem - 1
      const willContinue = nextRem > 0 || autoAdvanceRef.current

      // TTS 生成
      const ttsUrl = data.text ? await generateTTSUrl(data.text, data.character_id) : null
      if (ttsUrl) {
        setMessages(prev => {
          const last = prev.length - 1
          return last < 0 ? prev : prev.map((m, i) => i === last ? { ...m, audioUrl: ttsUrl } : m)
        })
        // TRPGラウンド末尾では先読みしない（キーパー後に次ラウンド1番目を新規取得するため）
        if (willContinue && !prefetchRef.current && !isLastOfRound) {
          fetchNextData(sid).then(d => {
            if (d && !d.error) prefetchRef.current = d
          })
        }
        await playAudio(ttsUrl)
      }

      // TRPGモード自動進行: ラウンド末尾でキーパーを発火（次ラウンド全員が文脈を持てる）
      // nextRem <= 0 でそのキャラの最後のアクション確定後にのみ発火（2アクション目がある場合は1回目をスキップ）
      // keeperFiredRoundRef で同一ラウンド内の並行呼び出しによる二重発火を防ぐ
      if (isLastOfRound && autoAdvanceRef.current && nextRem <= 0 && keeperFiredRoundRef.current !== data.round) {
        await fireKeeperTurn(sid, data.round)
        return
      }

      if (nextRem > 0) {
        setTimeout(() => nextTurn(sid, nextRem), 200)
      } else if (autoAdvanceRef.current) {
        setTimeout(() => nextTurn(sid, actionsPerTurnRef.current), 300)
      }
    } catch (e) {
      console.error(e)
      setAutoAdvance(false)
      autoAdvanceRef.current = false
    } finally {
      setLoading(false)
    }
  }

  const retakeTurn = async () => {
    if (!sessionId || loading) return
    setAutoAdvance(false)
    autoAdvanceRef.current = false
    prefetchRef.current = null
    const res = await fetch(`/api/session/${sessionId}/retake`, { method: 'POST' })
    const data = await res.json()
    if (data.error) { console.error(data.error); return }
    const removed = data.removed ?? 0
    if (removed > 0) {
      setMessages(prev => prev.slice(0, -removed))
    }
    nextTurn(sessionId, actionsPerTurnRef.current)
  }

  const toggleAutoAdvance = () => {
    const next = !autoAdvance
    setAutoAdvance(next)
    autoAdvanceRef.current = next
    if (next && !loading) {
      if (waitingForHuman) {
        submitHumanTurn('skip')
      } else {
        nextTurn(undefined, actionsPerTurnRef.current)
      }
    }
  }

  const revealMessage = (index: number) => {
    setMessages(prev => prev.map((m, i) => i === index ? { ...m, isRevealed: true } : m))
  }

  const saveCurrentSession = async () => {
    if (!sessionId) return
    setSaveStatus(t('session.save.saving'))
    try {
      const media = messages
        .map((m, i) => ({
          index: i,
          image_url: m.imageUrl && !m.imageUrl.startsWith('blob:') ? m.imageUrl : undefined,
          audio_url: m.audioUrl && !m.audioUrl.startsWith('blob:') ? m.audioUrl : undefined,
        }))
        .filter(item => item.image_url || item.audio_url)
      const res = await fetch(`/api/session/${sessionId}/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ media }),
      })
      const data = await res.json()
      if (data.status === 'ok') {
        setSaveStatus(t('session.save.done'))
        fetchSavedSessions()
        setTimeout(() => setSaveStatus(''), 2000)
      } else {
        setSaveStatus(t('session.save.failed'))
        setTimeout(() => setSaveStatus(''), 2000)
      }
    } catch {
      setSaveStatus(t('session.save.failed'))
      setTimeout(() => setSaveStatus(''), 2000)
    }
  }

  type KeeperResult = {
    text: string
    character_name?: string
    judgments: KeeperJudgment[]
    scene_advanced?: boolean
    new_scene_index?: number
    new_scene_title?: string
    new_chapter_title?: string | null
    propose_end?: boolean
  }

  const fetchAIKeeperResult = async (sid: string): Promise<KeeperResult | null> => {
    try {
      const res = await fetch(`/api/session/${sid}/ai_keeper`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend }),
      })
      const d = await res.json()
      if (d.error) { console.error(d.error); return null }
      return {
        text: d.text ?? '',
        character_name: d.character_name ?? '',
        judgments: d.judgments ?? [],
        scene_advanced: d.scene_advanced ?? false,
        new_scene_index: d.new_scene_index,
        new_scene_title: d.new_scene_title ?? '',
        new_chapter_title: d.new_chapter_title ?? null,
        propose_end: d.propose_end ?? false,
      }
    } catch (e) {
      console.error(e)
      return null
    }
  }

  const fireKeeperTurn = async (sid: string, round: number) => {
    keeperFiredRoundRef.current = round
    setActiveTurnCharId('')
    if (isHumanKeeperRef.current) {
      wasAutoAdvancingRef.current = autoAdvanceRef.current
      setAutoAdvance(false)
      autoAdvanceRef.current = false
      setWaitingForKeeperTurn(true)
      return
    }
    const keeperResult = await fetchAIKeeperResult(sid)
    if (keeperResult?.text) {
      setMessages(prev => [...prev, {
        character_id: '_keeper', character_name: keeperResult.character_name || '🎩 Keeper', text: keeperResult.text, emotion: '', tags: [],
      }])
    }
    if (keeperResult?.scene_advanced) {
      if (typeof keeperResult.new_scene_index === 'number') setCurrentSceneIndex(keeperResult.new_scene_index)
      const sceneLabel = keeperResult.new_scene_title
        ? `【シーン進行】${keeperResult.new_chapter_title ? `${keeperResult.new_chapter_title} / ` : ''}${keeperResult.new_scene_title}`
        : '【シーン進行】次のシーンへ'
      setMessages(prev => [...prev, {
        character_id: '_keeper', character_name: '📍 Scene', text: sceneLabel, emotion: '', tags: [],
      }])
      generateSceneImage()
    }
    if (keeperResult?.propose_end) {
      setMessages(prev => [...prev, {
        character_id: '_keeper', character_name: '⚙ System',
        text: '🏁 Keeper がセッション終了を提案しています',
        emotion: '', tags: [],
      }])
      try {
        const delibRes = await fetch(`/api/session/${sid}/vote/deliberate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ vote_type: 'end_session', detail: '', target_id: '', proposer_id: '_keeper', proposer_text: '' }),
        })
        const delibData = await delibRes.json()
        if (delibData.deliberations && Array.isArray(delibData.deliberations)) {
          for (const d of delibData.deliberations as { character_id: string; character_name: string; text: string; emotion: string }[]) {
            setMessages(prev => [...prev, { character_id: d.character_id, character_name: d.character_name, text: d.text, emotion: d.emotion, tags: [] }])
          }
        }
        setMessages(prev => [...prev, {
          character_id: '_keeper', character_name: 'GM',
          text: 'Keeper のセッション終了提案: 全員の意見は？',
          emotion: '', tags: [], isKeeperVote: true,
        }])
        wasAutoAdvancingRef.current = autoAdvanceRef.current
        setAutoAdvance(false)
        autoAdvanceRef.current = false
      } catch (e) { console.error(e) }
      return
    }
    if (keeperResult?.judgments && keeperResult.judgments.length > 0) {
      wasAutoAdvancingRef.current = autoAdvanceRef.current
      setAutoAdvance(false)
      autoAdvanceRef.current = false
      setPendingJudgments(keeperResult.judgments)
    }
    if (autoJudgmentStatRef.current && Object.keys(charSheetData).length > 0) {
      for (const [charId, sheet] of Object.entries(charSheetData)) {
        if (isCharDead(charId)) continue
        const statVal = (sheet as any)?.stats?.[autoJudgmentStatRef.current]?.current ?? 0
        if (statVal <= 0) continue
        const j: KeeperJudgment = {
          character_id: charId,
          character_name: charMap[charId]?.name ?? charId,
          stat: autoJudgmentStatRef.current,
          stat_value: statVal,
        }
        const roll = await rollJudgmentAuto(sid, j)
        if (roll) {
          const jv = roll.judgment?.judgment_value ?? statVal
          let outcome = ''
          if (roll.judgment?.critical) outcome = t('trpg.outcome.critical')
          else if (roll.judgment?.fumble) outcome = t('trpg.outcome.fumble')
          else if (roll.judgment?.success) outcome = t('trpg.outcome.success')
          else if (roll.judgment) outcome = t('trpg.outcome.failure')
          setMessages(prev => [...prev, {
            character_id: j.character_id,
            character_name: `🎲 ${j.character_name}`,
            text: `【${j.stat}】${roll.total} / ${jv}${outcome ? ` → ${outcome}` : ''}`,
            emotion: '', tags: [],
          }])
          if (shouldApplyDamage(roll.judgment, j.damage_on) && !isCharDead(j.character_id)) await rollDamage(j.character_id, j.character_name)
        }
      }
    }
    if (autoAdvanceRef.current) {
      setTimeout(() => nextTurn(sid, actionsPerTurnRef.current), 300)
    }
  }

  const rollJudgmentAuto = async (sid: string, j: KeeperJudgment, isSkill = false) => {
    if (j.stat_value === 0) {
      // stat_value=0 は死亡または未習得。死亡キャラはダメージを受けないよう success:true を返す
      const dead = isCharDead(j.character_id)
      return { total: 0, judgment: { success: dead, fumble: false, critical: false, judgment_value: 0 } }
    }
    try {
      const res = await fetch('/api/trpg/dice', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notation: '1d100',
          session_id: sid,
          skill_value: j.stat_value,
          rulebook_id: selectedRulebook,
          character_id: j.character_id,
          stat_name: j.stat,
          is_skill: isSkill,
        }),
      })
      const d = await res.json()
      if (d.error) { console.error(d.error); return null }
      return d
    } catch (e) {
      console.error(e)
      return null
    }
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

  const rollDamage = async (charId: string, charName: string) => {
    try {
      const res = await fetch('/api/trpg/damage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, character_id: charId, rulebook_id: selectedRulebook }),
      })
      const d = await res.json()
      if (d.error) return
      const syncStats = (updatedStats: Record<string, any>) => {
        const flat = Object.fromEntries(
          Object.entries(updatedStats).map(([k, v]: [string, any]) => [k, v.current ?? 0])
        )
        fetch(`/api/session/${sessionId}/sync_stats`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ character_id: charId, stats: flat }),
        }).catch(e => console.error('sync_stats failed:', e))
      }

      if (d.result === '即死') {
        setCharSheetData(prev => {
          const sheet = prev[charId]
          if (!sheet?.stats) return prev
          const zeroed = Object.fromEntries(
            Object.entries(sheet.stats as Record<string, any>).map(([k, v]) => [k, { ...(v as any), current: 0 }])
          )
          syncStats(zeroed)
          return { ...prev, [charId]: { ...sheet, stats: zeroed } }
        })
        setMessages(prev => [...prev, {
          character_id: charId,
          character_name: `💀 ${charName}`,
          text: `【即死】${d.flavor}`,
          emotion: '', tags: [],
        }])
      } else {
        const stat: string = d.stat
        const delta: number = d.delta
        setCharSheetData(prev => {
          const sheet = prev[charId]
          if (!sheet || !sheet.stats?.[stat]) return prev
          const newCurrent = Math.max(0, (sheet.stats[stat].current ?? 0) + delta)
          const updatedStats = { ...sheet.stats, [stat]: { ...sheet.stats[stat], current: newCurrent } }
          syncStats(updatedStats)
          return { ...prev, [charId]: { ...sheet, stats: updatedStats } }
        })
        setMessages(prev => [...prev, {
          character_id: charId,
          character_name: `💥 ${charName}`,
          text: `【ダメージ】${stat}${delta} (出目:${d.roll}) ${d.flavor}`,
          emotion: '', tags: [],
        }])
      }
    } catch (e) {
      console.error(e)
    }
  }

  const rollAllPendingJudgments = async () => {
    const list = [...pendingJudgments]
    setPendingJudgments([])
    for (const j of list) {
      if (isCharDead(j.character_id)) continue
      const roll = await rollJudgmentAuto(sessionId, j)
      if (roll) {
        const jv = roll.judgment?.judgment_value ?? j.stat_value
        let outcome = ''
        if (roll.judgment?.critical) outcome = 'クリティカル！'
        else if (roll.judgment?.fumble) outcome = 'ファンブル…'
        else if (roll.judgment?.success) outcome = '成功'
        else if (roll.judgment) outcome = '失敗'
        setMessages(prev => [...prev, {
          character_id: j.character_id,
          character_name: `🎲 ${j.character_name}`,
          text: `【${j.stat}】${roll.total} / ${jv}${outcome ? ` → ${outcome}` : ''}`,
          emotion: '', tags: [],
        }])
        if (shouldApplyDamage(roll.judgment, j.damage_on) && !isCharDead(j.character_id)) await rollDamage(j.character_id, j.character_name)
      }
    }
    if (wasAutoAdvancingRef.current) {
      setAutoAdvance(true)
      autoAdvanceRef.current = true
    }
    wasAutoAdvancingRef.current = false
    setTimeout(() => nextTurn(sessionId, actionsPerTurnRef.current), 300)
  }

  const rollPendingJudgment = async (j: KeeperJudgment, idx: number) => {
    if (isCharDead(j.character_id)) {
      setPendingJudgments(prev => prev.filter((_, i) => i !== idx))
      return
    }
    const roll = await rollJudgmentAuto(sessionId, j)
    if (roll) {
      const jv = roll.judgment?.judgment_value ?? j.stat_value
      let outcome = ''
      if (roll.judgment?.critical) outcome = 'クリティカル！'
      else if (roll.judgment?.fumble) outcome = 'ファンブル…'
      else if (roll.judgment?.success) outcome = '成功'
      else if (roll.judgment) outcome = '失敗'
      setMessages(prev => [...prev, {
        character_id: j.character_id,
        character_name: `🎲 ${j.character_name}`,
        text: `【${j.stat}】${roll.total} / ${jv}${outcome ? ` → ${outcome}` : ''}`,
        emotion: '', tags: [],
      }])
      if (shouldApplyDamage(roll.judgment, j.damage_on) && !isCharDead(j.character_id)) await rollDamage(j.character_id, j.character_name)
    }
    setPendingJudgments(prev => prev.filter((_, i) => i !== idx))
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

  const capCounters = (c: Record<string, number>) =>
    Object.fromEntries(Object.entries(c).map(([k, v]) => [k, Math.min(v, maxCounterRef.current)]))

  const openDiceDialog = () => {
    const withSheet = initiative.filter(id => charSheetData[id])
    setDiceDialogChars(withSheet)
    setDiceDialogLocked(false)
    setShowDiceDialog(true)
  }

  const openDiceDialogForHuman = () => {
    setDiceDialogChars(humanCharId ? [humanCharId] : [])
    setDiceDialogLocked(true)
    setShowDiceDialog(true)
  }

  const rollDiceDialog = async (type: 'stat' | 'skill', key: string) => {
    if (!key) return
    for (const charId of diceDialogChars) {
      const sheet = charSheetData[charId]
      if (!sheet) continue
      const raw = type === 'skill'
        ? (sheet.skills?.[key]?.current ?? sheet.skills?.[key])
        : sheet.stats?.[key]?.current
      const resolvedVal: number | undefined = typeof raw === 'number' ? raw : undefined
      const body: any = { notation: '1d100' }
      if (resolvedVal) {
        body.skill_value = resolvedVal
        body.rulebook_id = selectedRulebook
        body.is_skill = type === 'skill'
        body.is_stat = type === 'stat'
      }
      try {
        const res = await fetch('/api/trpg/dice', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        const data = await res.json()
        if (data.error) continue
        let text = `[${data.rolls?.join(', ')}] = ${data.total}`
        if (data.judgment) {
          const j = data.judgment
          text += `　/ ${key}(${j.judgment_value})`
          const label = j.critical ? t('trpg.outcome.criticalLabel') : j.fumble ? t('trpg.outcome.fumbleLabel') : j.success ? t('trpg.outcome.successLabel') : t('trpg.outcome.failureLabel')
          text += `　→ ${label}`
        } else if (resolvedVal) {
          text += `　/ ${key}(${resolvedVal})`
        }
        const charName = charMap[charId]?.name ?? charId
        setMessages(prev => [...prev, { character_id: charId, character_name: `🎲 ${charName}`, text, emotion: '', tags: [] }])
      } catch (e) {
        console.error(e)
      }
    }
  }

  const openGameSheetDialog = async () => {
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

  const openRuleDialog = async () => {
    const id = ruleSet || (ruleOptions[0]?.id ?? 'default')
    setRuleEditId(id)
    try {
      const res = await fetch(`/api/session/rules/${id}`)
      const data = await res.json()
      if (data.content) setRuleDraft(JSON.stringify(JSON.parse(data.content), null, 2))
    } catch {}
    setShowRuleDialog(true)
  }

  const saveRule = async () => {
    await fetch(`/api/session/rules/${ruleEditId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: ruleDraft }),
    })
  }

  const applyRule = async () => {
    await saveRule()
    setRuleSet(ruleEditId)
    const res = await fetch('/api/session/rules')
    const data = await res.json()
    if (data.rules) setRuleOptions(data.rules)
    setShowRuleDialog(false)
  }

  const loadSavedSession = async (filename: string) => {
    setLoading(true)
    try {
      const res = await fetch('/api/session/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      })
      const data = await res.json()
      if (data.error) { console.error(data.error); return }

      const nameMap: Record<string, string> = data.name_map || {}
      const history: any[] = data.history || []
      // _dice 旧データ用: "🎲 CharName【stat】..." からキャラ名を逆引き
      const reverseNameMap: Record<string, string> = {}
      for (const [id, n] of Object.entries(nameMap)) reverseNameMap[n] = id

      const reconstructed: SessionMessage[] = history.map(h => {
        if (h.character_id === 'human') {
          return { character_id: 'human', character_name: 'You', text: h.content, emotion: '', tags: [], isHuman: true }
        }
        if (h.character_id === '_scene_image') {
          return {
            character_id: '__scene__',
            character_name: '',
            text: '',
            emotion: '',
            tags: [],
            isSceneImage: true,
            imageStatus: h.image_url ? 'done' : 'error',
            imageUrl: (h.image_url as string) || undefined,
          } as SessionMessage
        }
        let cid: string = h.character_id || ''
        // 旧セーブデータ互換: _dice → コンテンツからキャラ名を解析して実IDに変換
        if (cid === '_dice') {
          const m = h.content.match(/^🎲\s+(.+?)(?:【|$)/)
          const parsedName = m?.[1]?.trim()
          const resolvedId = parsedName ? reverseNameMap[parsedName] : undefined
          if (resolvedId) cid = resolvedId
        }
        const name = cid === '_keeper' ? '🎩 Keeper' : (nameMap[cid] || cid)
        const prefix = name + ': '
        const text = h.content.startsWith(prefix) ? h.content.slice(prefix.length) : h.content
        return {
          character_id: cid,
          character_name: name,
          text,
          emotion: h.emotion || '',
          tags: h.tags || [],
          imageColor: charMap[cid]?.image_color,
          imageUrl: (h.image_url as string) || undefined,
          audioUrl: (h.audio_url as string) || undefined,
        }
      })

      sessionIdRef.current = data.session_id
      setSessionId(data.session_id)
      initiativeRef.current = data.initiative || []
      setInitiative(data.initiative || [])
      setRound(data.round || 1)
      setCurrentSceneIndex(data.current_scene_index || 0)
      setActiveTurnCharId('')
      setMessages(reconstructed)
      setStandingFallback(new Set())
      setWaitingForHuman(false)
      const loadedHumanChar = characters.find(c => (data.initiative || []).includes(c.id) && c.player_type === 'human')
      setHumanCharId(loadedHumanChar?.id ?? '')
      setHumanCharName(loadedHumanChar?.name ?? '')
      if (data.actions_per_turn) {
        setActionsPerTurn(data.actions_per_turn)
        actionsPerTurnRef.current = data.actions_per_turn
      }

      // TRPGフィールド復元
      const isTrpg: boolean = data.trpg_mode || false
      trpgModeRef.current = isTrpg
      setTrpgMode(isTrpg)
      if (data.trpg_rulebook) setSelectedRulebook(data.trpg_rulebook)
      isHumanKeeperRef.current = data.human_keeper || false
      setWaitingForKeeperTurn(false)
      setCharSheetData({})
      const charGameSheets: Record<string, string> = data.char_game_sheets || {}
      if (isTrpg && Object.keys(charGameSheets).length > 0) {
        const runtimeStats: Record<string, Record<string, number>> = data.runtime_stats || {}
        const sheetData: Record<string, any> = {}
        await Promise.all(
          Object.entries(charGameSheets).map(async ([charId, sheetId]) => {
            try {
              const r = await fetch(`/api/characters/${charId}/game_sheets`)
              const d = await r.json()
              if (d.game_sheets?.[sheetId]) {
                const sheet = normalizeSheetStats({ ...d.game_sheets[sheetId], _sheet_id: sheetId })
                const statOverrides = runtimeStats[charId]
                if (statOverrides && sheet.stats) {
                  const stats = { ...sheet.stats }
                  for (const [statKey, currentVal] of Object.entries(statOverrides)) {
                    if (stats[statKey]) stats[statKey] = { ...stats[statKey], current: currentVal }
                  }
                  sheetData[charId] = { ...sheet, stats }
                } else {
                  sheetData[charId] = sheet
                }
              }
            } catch {}
          })
        )
        setCharSheetData(sheetData)
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const endSession = async () => {
    if (sessionId && messages.length > 0) {
      await saveCurrentSession()
    }
    sessionIdRef.current = ''
    setSessionId('')
    setMessages([])
    initiativeRef.current = []
    setInitiative([])
    setRound(1)
    setAutoAdvance(false)
    autoAdvanceRef.current = false
    setSceneImageStatus('idle')
    setWaitingForHuman(false)
    setWaitingForKeeperTurn(false)
    isHumanKeeperRef.current = false
    setHumanCharId('')
    setHumanCharName('')
    fetchSavedSessions()
  }

  const addKeeperAction = () => {
    if (!keeperInput.trim()) return
    if (pendingActions.length >= actionsPerTurnRef.current) return
    setPendingActions(prev => [...prev, keeperInput.trim()])
    setKeeperInput('')
  }

  const commitKeeperActions = async () => {
    if (!sessionId || pendingActions.length === 0) return
    const text = pendingActions.length === 1
      ? pendingActions[0]
      : pendingActions.map((a, i) => `${i + 1}. ${a}`).join('\n')
    await fetch(`/api/session/${sessionId}/keeper`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })
    setMessages(prev => [...prev, {
      character_id: '_keeper',
      character_name: '🎩 Keeper',
      text,
      emotion: '',
      tags: [],
    }])
    setPendingActions([])
    if (waitingForKeeperTurn) {
      setWaitingForKeeperTurn(false)
      setAutoAdvance(true)
      autoAdvanceRef.current = true
      setTimeout(() => nextTurn(sessionId, actionsPerTurnRef.current), 300)
    } else if (autoAdvanceRef.current) {
      setAutoAdvance(false)
      autoAdvanceRef.current = false
    }
  }

  const skipCurrentTurn = async () => {
    if (!sessionId) return
    const res = await fetch(`/api/session/${sessionId}/skip`, { method: 'POST' })
    const data = await res.json()
    if (data.error) return
    if (data.counters) setCounters(capCounters(data.counters))
    setRound(data.round)
    setMessages(prev => [...prev, {
      character_id: '_keeper',
      character_name: '🎩 Keeper',
      text: t('session.msg.skipTurn', { name: data.character_name }),
      emotion: '', tags: [],
    }])
  }

  const designateNext = async () => {
    if (!sessionId || !designateTarget) return
    await fetch(`/api/session/${sessionId}/designate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_id: designateTarget }),
    })
    const nameMap = Object.fromEntries(characters.map(c => [c.id, c.name]))
    setMessages(prev => [...prev, {
      character_id: '_keeper',
      character_name: '🎩 Keeper',
      text: t('session.msg.designate', { name: nameMap[designateTarget] ?? designateTarget }),
      emotion: '', tags: [],
    }])
    setDesignateTarget('')
  }

  const handleHumanGenerateImage = async () => {
    if (!sessionId || !t2iBackend) return
    const res = await fetch(`/api/session/${sessionId}/human_turn`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'generate_image', text: '', character_id: humanCharId }),
    })
    const data = await res.json()
    if (data.error) return
    if (data.counters) setCounters(capCounters(data.counters))
    generateSceneImage()
  }

  const addHumanAction = () => {
    if (!humanInput.trim()) return
    if (actionsPerTurnRef.current > 0 && humanPending.length >= actionsPerTurnRef.current) return
    setHumanPending(prev => [...prev, humanInput.trim()])
    setHumanInput('')
  }

  const submitHumanTurn = async (action: 'send' | 'extend' | 'skip' | 'interrupt') => {
    if (!sessionId) return
    const lines = [...humanPending, ...(humanInput.trim() ? [humanInput.trim()] : [])]
    const text = lines.join('\n')
    const res = await fetch(`/api/session/${sessionId}/human_turn`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, text, character_id: humanCharId }),
    })
    const data = await res.json()
    if (data.error) return

    if (action === 'skip') {
      setMessages(prev => [...prev, {
        character_id: '_keeper',
        character_name: '⚙ System',
        text: t('session.msg.humanSkip', { name: humanCharName }),
        emotion: '', tags: [],
      }])
    }
    if (action !== 'skip' && text) {
      setMessages(prev => [...prev, {
        character_id: humanCharId,
        character_name: humanCharName,
        text,
        emotion: 'neutral',
        tags: [],
        imageColor: charMap[humanCharId]?.image_color,
      }])
      if (ttsHumanEnabledRef.current && ttsBackend) {
        const ttsUrl = await (async () => {
          try {
            const r = await fetch('/api/tts/', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ text, character_id: humanCharId, backend: ttsBackend }),
            })
            if (!r.ok) return null
            const blob = await r.blob()
            const form = new FormData()
            form.append('file', blob, 'audio.wav')
            const sr = await fetch('/api/tts/save', { method: 'POST', body: form })
            const sd = await sr.json()
            return sd.url as string
          } catch { return null }
        })()
        if (ttsUrl) {
          setMessages(prev => {
            const last = prev.length - 1
            return last < 0 ? prev : prev.map((m, i) => i === last ? { ...m, audioUrl: ttsUrl } : m)
          })
          await playAudio(ttsUrl)
        }
      }
    }

    if (data.counters) setCounters(capCounters(data.counters))
    if (typeof data.round === 'number') setRound(data.round)
    setHumanInput('')
    setHumanPending([])

    if (action === 'interrupt') { setInterruptMode(false); return }
    if (action === 'extend') return
    if (action === 'send' && !data.turn_advanced) return

    setWaitingForHuman(false)
    if (wasAutoAdvancingRef.current) {
      wasAutoAdvancingRef.current = false
      setAutoAdvance(true)
      autoAdvanceRef.current = true
    }
    // 人間がラウンド末尾だった場合、nextTurn を呼ぶ前にキーパーを発火
    const humanIsLastOfRound = trpgModeRef.current &&
      initiativeRef.current.length > 0 &&
      initiativeRef.current[initiativeRef.current.length - 1] === humanCharId &&
      keeperFiredRoundRef.current !== data.round
    if (humanIsLastOfRound && autoAdvanceRef.current) {
      await fireKeeperTurn(sessionId!, data.round)
    } else if (autoAdvanceRef.current) {
      setTimeout(() => nextTurn(sessionId, actionsPerTurnRef.current), 300)
    }
  }

  const startDeliberation = async () => {
    if (!sessionId) return
    setVoteLoading(true)
    setShowVoteDialog(false)
    try {
      const res = await fetch(`/api/session/${sessionId}/vote/deliberate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vote_type: voteType, detail: voteDetail, target_id: voteTarget, proposer_id: humanCharId, proposer_text: voteProposerText }),
      })
      const data = await res.json()
      if (data.error) return
      if (data.counters) setCounters(capCounters(data.counters))
      if (data.deliberations && Array.isArray(data.deliberations)) {
        for (const d of data.deliberations as { character_id: string; character_name: string; text: string; emotion: string }[]) {
          setMessages(prev => [...prev, {
            character_id: d.character_id,
            character_name: d.character_name,
            text: d.text,
            emotion: d.emotion || '',
            tags: [],
            imageColor: charMap[d.character_id]?.image_color,
          }])
          if (d.character_id !== '_keeper' && d.text && d.text !== '(弁明なし)') {
            let ttsUrl: string | null = null
            if (d.character_id === humanCharId) {
              if (ttsHumanEnabledRef.current && ttsBackend) {
                try {
                  const r = await fetch('/api/tts/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: d.text, character_id: d.character_id, backend: ttsBackend }) })
                  if (r.ok) {
                    const blob = await r.blob()
                    const form = new FormData()
                    form.append('file', blob, 'audio.wav')
                    const sr = await fetch('/api/tts/save', { method: 'POST', body: form })
                    const sd = await sr.json()
                    ttsUrl = sd.url as string
                  }
                } catch {}
              }
            } else {
              ttsUrl = await generateTTSUrl(d.text, d.character_id)
            }
            if (ttsUrl) {
              setMessages(prev => { const last = prev.length - 1; return last < 0 ? prev : prev.map((m, i) => i === last ? { ...m, audioUrl: ttsUrl } : m) })
              await playAudio(ttsUrl)
            }
          }
        }
      }
      setMessages(prev => [...prev, {
        character_id: '_keeper',
        character_name: 'GM',
        text: humanCharId
          ? t('session.vote.castHuman', { name: humanCharName })
          : t('session.vote.castKeeper'),
        emotion: '',
        tags: [],
        isKeeperVote: true,
      }])
    } finally {
      setVoteLoading(false)
    }
  }

  const commitVote = async (keeperVote: boolean) => {
    if (!sessionId) return
    setVoteLoading(true)
    try {
      const res = await fetch(`/api/session/${sessionId}/vote/commit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keeper_vote: keeperVote }),
      })
      const data = await res.json()
      if (data.error) return
      setMessages(prev => [
        ...prev.filter(m => !m.isKeeperVote),
        {
          character_id: '_keeper',
          character_name: 'GM',
          text: data.result_text,
          emotion: '', tags: [],
        },
      ])
      if (data.initiative) { initiativeRef.current = data.initiative; setInitiative(data.initiative) }
      if (data.ended) endSession()
      setVoteDetail('')
      setVoteTarget('')
      setVoteProposerText('')
    } finally {
      setVoteLoading(false)
    }
  }

  const advanceScene = async () => {
    if (!sessionId) return
    try {
      const res = await fetch(`/api/session/${sessionId}/scene/advance`, { method: 'POST' })
      const data = await res.json()
      if (data.error) { console.error('scene/advance:', data.error); return }
      if (typeof data.current_scene_index === 'number') setCurrentSceneIndex(data.current_scene_index)
      const sceneLabel = data.scene_title
        ? `【シーン進行】${data.chapter_title ? `${data.chapter_title} / ` : ''}${data.scene_title}`
        : '【シーン進行】次のシーンへ'
      setMessages(prev => [...prev, {
        character_id: '_keeper', character_name: '📍 Scene', text: sceneLabel, emotion: '', tags: [],
      }])
      generateSceneImage()
    } catch (e) {
      console.error('advanceScene error:', e)
    }
  }

  const generateSceneImage = async () => {
    if (!sessionId || !t2iBackend) return
    setSceneImageStatus('generating')
    const genId = Math.random().toString(36).slice(2)
    setMessages(prev => [...prev, {
      character_id: '__scene__',
      character_name: '',
      text: '',
      emotion: '',
      tags: [],
      isSceneImage: true,
      imageStatus: 'generating',
      _genId: genId,
    }])
    try {
      const res = await fetch(`/api/session/${sessionId}/generate-image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend, t2i_backend: t2iBackend }),
      })
      const data = await res.json()
      if (data.error) {
        setMessages(prev => prev.map(m => m._genId === genId ? { ...m, imageStatus: 'error', imageError: data.error } : m))
        setSceneImageStatus('error')
      } else {
        setMessages(prev => prev.map(m => m._genId === genId ? { ...m, imageStatus: 'done', imageUrl: data.url } : m))
        setSceneImageStatus('idle')
      }
    } catch {
      setMessages(prev => prev.map(m => m._genId === genId ? { ...m, imageStatus: 'error', imageError: t('session.msg.imageFailed') } : m))
      setSceneImageStatus('error')
    }
  }

  // ── セットアップ画面 ──────────────────────────────────────
  if (!sessionId) {
    return (
      <div className="tab-content session-tab">
        <div className="session-setup-scroll">
        <div className="session-setup">
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
            <h2 style={{ margin: 0 }}>{t('session.setup.heading')}</h2>
            <button
              className={`toggle-btn${trpgMode ? ' active' : ''}`}
              onClick={() => { const next = !trpgMode; trpgModeRef.current = next; setTrpgMode(next) }}
              style={{ padding: '4px 16px', borderRadius: 20, border: '1px solid var(--border-color, #aaa)', background: trpgMode ? '#4a6cf7' : 'transparent', color: trpgMode ? '#fff' : 'inherit', cursor: 'pointer', fontSize: '0.9em' }}
            >
              {trpgMode ? t('trpg.mode.on') : t('trpg.mode.off')}
            </button>
          </div>

          <div className="session-field">
            <label className="session-label">{t('session.setup.charSelect.label')}</label>
            <CharMultiSelect
              characters={characters}
              selected={selectedChars}
              onChange={next => {
                setSelectedChars(next)
                setCharRoles(prev => Object.fromEntries(Object.entries(prev).filter(([id]) => next.includes(id))) as Record<string, 'investigator' | 'keeper'>)
              }}
            />
          </div>

          {selectedChars.length > 0 && (
            <div className="session-participants">
              <div className="session-participants-header">
                <span>{t('session.setup.participants.label', { n: selectedChars.length })}</span>
                {llmBackendOptions.length > 0 && (
                  <button className="novel-hdr-btn" onClick={() => setShowBackendDialog(true)} title={t('session.setup.aiSettingsBtn.title')}>{t('session.setup.aiSettingsBtn')}</button>
                )}
                {trpgMode && (
                  <button className="novel-hdr-btn" onClick={openGameSheetDialog} title={t('trpg.gameChar.setupBtn.title')}>{t('trpg.gameChar.setupBtn')}</button>
                )}
              </div>
              <ul className="session-participants-list">
                {selectedChars.map(id => (
                  <li key={id}>
                    <span>{charMap[id]?.name ?? id}</span>
                    {charBackends[id] && (
                      <span style={{ fontSize: '0.75em', opacity: 0.6, marginLeft: '6px' }}>
                        [{llmBackendOptions.find(b => b.id === charBackends[id])?.label ?? charBackends[id]}]
                      </span>
                    )}
                    {trpgMode && charRoles[id] === 'keeper' && (
                      <span style={{ fontSize: '0.75em', marginLeft: '6px', color: '#4a6cf7' }}>{t('trpg.role.keeper')}</span>
                    )}
                    {trpgMode && charGameSheets[id] && charRoles[id] !== 'keeper' && (
                      <span style={{ fontSize: '0.75em', opacity: 0.6, marginLeft: '6px', color: '#4a6cf7' }}>
                        [{charGameSheets[id]}]
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {selectedChars.length === 0 && (
            <p className="session-hint">{t('session.setup.noCharHint')}</p>
          )}

          {!trpgMode && ruleOptions.length > 0 && (
            <div className="session-field">
              <label className="session-label">{t('session.setup.ruleLabel')}</label>
              <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                <select
                  className="session-select"
                  style={{ flex: 1 }}
                  value={ruleSet}
                  onChange={e => setRuleSet(e.target.value)}
                >
                  {ruleOptions.map(r => (
                    <option key={r.id} value={r.id}>{r.label}</option>
                  ))}
                </select>
                <button className="novel-hdr-btn" onClick={openRuleDialog} title={t('session.setup.ruleEditBtn.title')}>✏️</button>
              </div>
            </div>
          )}

          {trpgMode && rulebookOptions.length > 0 && (
            <div className="session-field">
              <label className="session-label">{t('trpg.rulebook.label')}</label>
              <select
                className="session-select"
                value={selectedRulebook}
                onChange={e => setSelectedRulebook(e.target.value)}
              >
                {rulebookOptions.map(r => (
                  <option key={r.id} value={r.id}>{r.label}（{r.dice_system}）</option>
                ))}
              </select>
            </div>
          )}

          {trpgMode && scenarioOptions.length > 0 && (
            <div className="session-field">
              <label className="session-label">{t('trpg.scenario.label')}</label>
              <select
                className="session-select"
                value={selectedScenario}
                onChange={e => setSelectedScenario(e.target.value)}
              >
                <option value="">{t('trpg.scenario.none')}</option>
                {scenarioOptions.map(s => (
                  <option key={s.id} value={s.id}>{s.label}</option>
                ))}
              </select>
              {selectedScenario && scenarioOptions.find(s => s.id === selectedScenario)?.synopsis && (
                <p style={{ fontSize: '0.82em', opacity: 0.7, marginTop: 4, marginBottom: 0 }}>
                  {scenarioOptions.find(s => s.id === selectedScenario)?.synopsis}
                </p>
              )}
            </div>
          )}

          {trpgMode && (
            <div className="session-field">
              <label className="session-label">{t('trpg.keeper.label')}</label>
              {keeperCharId ? (
                <span style={{ fontSize: '0.85em', color: '#4a6cf7', padding: '4px 2px' }}>{t('trpg.keeper.aiAssigned')}</span>
              ) : (
                <div style={{ display: 'flex', gap: 6 }}>
                  <button
                    className={`toggle-btn${!humanKeeper ? ' active' : ''}`}
                    onClick={() => setHumanKeeper(false)}
                    style={{ padding: '4px 14px', borderRadius: 16, border: '1px solid var(--border-color, #aaa)', background: !humanKeeper ? '#4a6cf7' : 'transparent', color: !humanKeeper ? '#fff' : 'inherit', cursor: 'pointer', fontSize: '0.85em' }}
                  >{t('trpg.keeper.ai')}</button>
                  <button
                    className={`toggle-btn${humanKeeper ? ' active' : ''}`}
                    onClick={() => setHumanKeeper(true)}
                    style={{ padding: '4px 14px', borderRadius: 16, border: '1px solid var(--border-color, #aaa)', background: humanKeeper ? '#4a6cf7' : 'transparent', color: humanKeeper ? '#fff' : 'inherit', cursor: 'pointer', fontSize: '0.85em' }}
                  >{t('trpg.keeper.human')}</button>
                </div>
              )}
            </div>
          )}

          {!trpgMode && actionsPerTurn > 1 && (() => {
            const filtered = directiveOptions.filter(d => d.recommended_for.length === 0 || d.recommended_for.includes(actionsPerTurn))
            return filtered.length > 0 && (
              <div className="session-field">
                <label className="session-label">{t('session.setup.directiveLabel')}</label>
                <select
                  className="session-select"
                  value={directiveSet}
                  onChange={e => setDirectiveSet(e.target.value)}
                >
                  {filtered.map(d => (
                    <option key={d.id} value={d.id}>{d.label}</option>
                  ))}
                </select>
              </div>
            )
          })()}

          {!trpgMode && (
            <div className="session-field">
              <label className="session-label">{t('session.setup.topicLabel')}</label>
              <input
                className="session-topic-input"
                type="text"
                value={topic}
                onChange={e => setTopic(e.target.value)}
                placeholder={t('session.setup.topicPlaceholder')}
              />
            </div>
          )}

          <button
            className="start-btn"
            onClick={startSession}
            disabled={selectedChars.length < 1 || sessionStarting}
          >
            {t('session.setup.startBtn')}
          </button>

          {savedSessions.length > 0 && (
            <div className="session-field">
              <label className="session-label">{t('session.setup.savedLabel')}</label>
              <div className="session-saved-list">
                {savedSessions.map(s => (
                  <div key={s.filename} className="session-saved-item" onClick={() => loadSavedSession(s.filename)}>
                    <span className="saved-topic">{s.trpg_scenario_title || s.topic || t('session.setup.savedUntitled')}</span>
                    <span className="saved-meta">{s.character_names.join(' · ')} | Round {s.round}</span>
                    <span className="saved-date">{s.saved_at.replace('_', ' ')}</span>
                    <button
                      className="saved-delete-btn"
                      title={t('session.setup.deleteBtn.title')}
                      onClick={async e => {
                        e.stopPropagation()
                        if (!confirm(t('session.setup.deleteConfirm', { topic: s.topic || t('session.setup.savedUntitled') }))) return
                        await fetch(`/api/session/saved/${s.filename}`, { method: 'DELETE' })
                        fetchSavedSessions()
                      }}
                    >🗑</button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        </div>

        {showRuleDialog && (
          <div className="plot-dialog-overlay" onClick={e => { if (e.target === e.currentTarget) setShowRuleDialog(false) }}>
            <div className="plot-dialog">
              <div className="plot-dialog-header">
                <span>{t('session.ruleDialog.header')}{ruleEditId ? ` — ${ruleOptions.find(r => r.id === ruleEditId)?.label ?? ruleEditId}` : ''}</span>
                <button className="plot-dialog-close" onClick={() => setShowRuleDialog(false)}>×</button>
              </div>
              <div className="plot-dialog-body">
                <textarea
                  className="plot-dialog-textarea"
                  value={ruleDraft}
                  onChange={e => setRuleDraft(e.target.value)}
                  placeholder={t('session.ruleDialog.placeholder')}
                  rows={14}
                />
              </div>
              <div className="plot-dialog-footer">
                <button className="novel-hdr-btn" onClick={saveRule}>{t('session.ruleDialog.saveBtn')}</button>
                <button className="novel-hdr-btn apply-btn" onClick={applyRule}>{t('session.ruleDialog.applyBtn')}</button>
              </div>
            </div>
          </div>
        )}
      {showBackendDialog && (
        <div className="plot-dialog-overlay" onClick={e => { if (e.target === e.currentTarget) setShowBackendDialog(false) }}>
          <div className="plot-dialog" style={{ maxWidth: 420 }}>
            <div className="plot-dialog-header">
              <span>{t('session.backendDialog.header')}</span>
              <button className="plot-dialog-close" onClick={() => setShowBackendDialog(false)}>×</button>
            </div>
            <div className="plot-dialog-body" style={{ padding: '16px' }}>
              {selectedChars.map(id => (
                <div key={id} style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
                  <span style={{ flex: 1, fontWeight: 500 }}>{charMap[id]?.name ?? id}</span>
                  <select
                    className="session-select"
                    style={{ flex: 2 }}
                    value={charBackends[id] ?? ''}
                    onChange={e => setCharBackends(prev => {
                      const next = { ...prev }
                      if (e.target.value) next[id] = e.target.value
                      else delete next[id]
                      return next
                    })}
                  >
                    <option value="">{t('session.backendDialog.globalOption')}</option>
                    {llmBackendOptions.map(b => (
                      <option key={b.id} value={b.id}>{b.label}</option>
                    ))}
                  </select>
                </div>
              ))}
            </div>
            <div className="plot-dialog-footer">
              <button className="novel-hdr-btn apply-btn" onClick={() => setShowBackendDialog(false)}>{t('session.backendDialog.confirmBtn')}</button>
            </div>
          </div>
        </div>
      )}
      {showGameSheetDialog && (
        <div className="plot-dialog-overlay" onClick={e => { if (e.target === e.currentTarget) setShowGameSheetDialog(false) }}>
          <div className="plot-dialog" style={{ maxWidth: 440 }}>
            <div className="plot-dialog-header">
              <span>{t('trpg.gameChar.dialogHeader')}</span>
              <button className="plot-dialog-close" onClick={() => setShowGameSheetDialog(false)}>×</button>
            </div>
            <div className="plot-dialog-body" style={{ padding: '16px' }}>
              {keeperCount >= 2 && (
                <div style={{ color: '#e05', fontSize: '0.82em', marginBottom: '10px' }}>
                  {t('trpg.keeper.maxOneWarn')}
                </div>
              )}
              {selectedChars.map(id => {
                const role = charRoles[id] ?? 'investigator'
                const isKeeper = role === 'keeper'
                const options = charGameSheetOptions[id] ?? []
                return (
                  <div key={id} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                    <img src={`/api/characters/${id}/icon`} alt="" style={{ width: 28, height: 28, borderRadius: '50%', objectFit: 'cover' }} />
                    <span style={{ width: 80, fontWeight: 500, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{charMap[id]?.name ?? id}</span>
                    <button
                      className="novel-hdr-btn"
                      style={{ flexShrink: 0, fontSize: '0.78em', padding: '2px 8px', background: isKeeper ? '#4a6cf7' : undefined, color: isKeeper ? '#fff' : undefined }}
                      onClick={() => setCharRoles(prev => ({ ...prev, [id]: isKeeper ? 'investigator' : 'keeper' }))}
                    >
                      {isKeeper ? t('trpg.role.keeper') : t('trpg.role.investigator')}
                    </button>
                    {!isKeeper && (
                      <select
                        className="session-select"
                        style={{ flex: 1 }}
                        value={charGameSheets[id] ?? ''}
                        onChange={e => setCharGameSheets(prev => {
                          const next = { ...prev }
                          if (e.target.value) next[id] = e.target.value
                          else delete next[id]
                          return next
                        })}
                      >
                        <option value="">{t('trpg.gameChar.noSheet')}</option>
                        {options.map(sid => (
                          <option key={sid} value={sid}>{sid}</option>
                        ))}
                      </select>
                    )}
                    {isKeeper && (
                      <span style={{ flex: 1, fontSize: '0.78em', opacity: 0.5 }}>{t('trpg.gameChar.sheetNotRequired')}</span>
                    )}
                  </div>
                )
              })}
            </div>
            <div className="plot-dialog-footer">
              <button
                className="novel-hdr-btn apply-btn"
                onClick={() => setShowGameSheetDialog(false)}
                disabled={keeperCount >= 2}
              >{t('trpg.gameChar.confirmBtn')}</button>
            </div>
          </div>
        </div>
      )}
      </div>
    )
  }

  // ── セッション中 ──────────────────────────────────────────
  const nameMap = Object.fromEntries(characters.map(c => [c.id, c.name]))

  return (
    <div className="tab-content session-tab">
      <div className="session-header">
        <span className="session-info">
          {trpgMode && <span style={{ marginRight: 8 }}>Scene {currentSceneIndex + 1} |</span>}
          Round {round} | {initiative.map((id, idx) => {
            const name = nameMap[id] || id
            const c = counters[id] ?? 0
            const cStr = c > 0 ? `[+${c}]` : `[${c}]`
            const isActive = id === activeTurnCharId
            const atMax = c >= maxCounter
            return (
              <span key={id} style={atMax ? { color: '#e05' } : undefined}>
                {idx > 0 && ' → '}
                {isActive ? <strong>{name}{cStr}</strong> : `${name}${cStr}`}
              </span>
            )
          })}
        </span>
        <div className="session-header-actions">
          {saveStatus && <span className="save-status">{saveStatus}</span>}
          {trpgMode && Object.keys(charSheetData).length > 0 && (
            <button
              className="novel-hdr-btn"
              onClick={() => setShowSheetPanel(v => !v)}
              title="キャラクターシート"
              style={{ opacity: showSheetPanel ? 1 : 0.55 }}
            >📋</button>
          )}
          <button className="save-btn" onClick={saveCurrentSession} title={t('session.header.saveTitle')}>💾</button>
          <button className="end-btn" onClick={endSession}>{t('session.header.endBtn')}</button>
        </div>
      </div>

      <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
      <div className="session-stage" style={{ flex: 1, minWidth: 0 }}>
        {/* 立ち絵オーバーレイ */}
        <div className="session-standing">
          {initiative.map((cid, idx) => {
            const n = initiative.length
            const leftPct = n === 1 ? 50 : 10 + (idx / (n - 1)) * 80
            return (
              <img
                key={cid}
                src={standingFallback.has(cid) ? `/api/characters/${cid}/icon` : `/api/characters/${cid}/standing`}
                alt=""
                className={standingFallback.has(cid) ? 'standing-icon-fallback' : ''}
                style={{ left: `${leftPct}%` }}
                onError={e => {
                  if (!standingFallback.has(cid)) {
                    setStandingFallback(prev => new Set([...prev, cid]))
                  } else {
                    e.currentTarget.style.display = 'none'
                  }
                }}
              />
            )
          })}
        </div>

        {/* メッセージ履歴 */}
        <div className="session-messages">
          {messages.map((m, i) => {
            if (m.character_id === '_keeper') {
              if (m.isKeeperVote) {
                return (
                  <div key={i} className="session-msg keeper-msg">
                    <div className="session-msg-body keeper-body">
                      <div className="session-msg-header">
                        <span className="session-msg-name keeper-name">🎩 Keeper</span>
                      </div>
                      <div className="session-msg-text keeper-text" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <span>{m.text}</span>
                        <button className="novel-hdr-btn apply-btn" onClick={() => commitVote(true)} disabled={voteLoading} style={{ padding: '4px 12px', height: 'auto' }}>{t('session.vote.agree')}</button>
                        <button className="novel-hdr-btn" onClick={() => commitVote(false)} disabled={voteLoading} style={{ padding: '4px 12px', height: 'auto', background: '#c0392b' }}>{t('session.vote.disagree')}</button>
                      </div>
                    </div>
                  </div>
                )
              }
              return (
                <div key={i} className="session-msg keeper-msg">
                  <div className="session-msg-body keeper-body">
                    <div className="session-msg-header">
                      <span className="session-msg-name keeper-name">{m.character_name || '🎩 Keeper'}</span>
                    </div>
                    <div className="session-msg-text keeper-text">{m.text}</div>
                  </div>
                </div>
              )
            }
            if (m.isSceneImage) {
              return (
                <div key={i} className="session-msg-scene-image">
                  {m.imageStatus === 'generating' && <div className="t2i-status">{t('session.msg.sceneGenerating')}</div>}
                  {m.imageStatus === 'error' && <div className="t2i-status t2i-error">⚠ {m.imageError}</div>}
                  {m.imageUrl && (
                    <img
                      src={m.imageUrl}
                      alt="scene"
                      className="scene-image"
                      onDoubleClick={() => window.open(m.imageUrl, '_blank')}
                      style={{ cursor: 'zoom-in' }}
                    />
                  )}
                </div>
              )
            }
            const blocked = safetyLevel !== 'off' && !m.isHuman && !m.isRevealed && isContentBlocked(m.tags, allowedSexual, allowedViolence)
            const revealed = safetyLevel !== 'off' && m.isRevealed && isContentBlocked(m.tags, allowedSexual, allowedViolence)
            return (
              <div key={i} className={`session-msg ${m.isHuman ? 'human' : ''}`}>
                {!m.isHuman && (
                  m.character_id.startsWith('_')
                    ? <span className="avatar avatar-system">{m.character_id === '_dice' ? '🎲' : m.character_id === '_keeper' ? '🎩' : '⚙️'}</span>
                    : <img src={`/api/characters/${m.character_id}/icon`} alt="" className="avatar" />
                )}
                <div
                  className="session-msg-body"
                  style={m.imageColor && !m.isHuman ? { background: m.imageColor + '33', borderLeft: `3px solid ${m.imageColor}` } : undefined}
                >
                  <div className="session-msg-header">
                    <span
                      className="session-msg-name"
                      style={m.imageColor && !m.isHuman ? { color: m.imageColor } : undefined}
                    >
                      {m.character_name}
                      {m.emotion && m.emotion !== 'neutral' && (
                        <span className="emotion"> ({m.emotion})</span>
                      )}
                    </span>
                    {m.audioUrl && (
                      <audio key={m.audioUrl} controls src={m.audioUrl} className="session-msg-audio" />
                    )}
                  </div>
                  {blocked ? (
                    <div className="content-filter-overlay" onClick={() => revealMessage(i)}>
                      <span>{t('session.msg.filterBlocked', { tags: m.tags.join(', ') })}</span>
                      <span className="filter-hint">{t('session.msg.filterHint')}</span>
                    </div>
                  ) : (
                    <>
                      {revealed && (
                        <div className="filter-warning">{t('session.msg.filterReleased', { tags: m.tags.join(', ') })}</div>
                      )}
                      <div className="session-msg-text">{m.text}</div>
                      {m.imageStatus === 'generating' && (
                        <div className="t2i-status">{t('session.msg.imageGenerating')}</div>
                      )}
                      {m.imageStatus === 'error' && (
                        <div className="t2i-status t2i-error">⚠ {m.imageError}</div>
                      )}
                      {m.imageUrl && (
                        <img src={m.imageUrl} alt="" className="session-msg-image" />
                      )}
                    </>
                  )}
                </div>
              </div>
            )
          })}
          {loading && (
            <div className="session-msg">
              <div className="session-msg-body">
                <div className="typing">...</div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>
      {trpgMode && showSheetPanel && Object.keys(charSheetData).length > 0 && (
        <div style={{ width: 220, overflowY: 'auto', borderLeft: '1px solid var(--border-color, #444)', padding: '10px 8px', flexShrink: 0, fontSize: '0.8em' }}>
          {Object.entries(charSheetData).map(([charId, sheet]) => {
            const stats: Record<string, { current: number; max?: number }> = sheet.stats ?? {}
            const isDead = Object.values(stats).some(v => v.current <= 0)
            return (
              <div key={charId} style={{ marginBottom: 16, opacity: isDead ? 0.5 : 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 6 }}>
                  <img src={`/api/characters/${charId}/icon`} alt="" style={{ width: 20, height: 20, borderRadius: '50%', objectFit: 'cover', filter: isDead ? 'grayscale(1)' : 'none' }} />
                  <span style={{ fontWeight: 600 }}>{isDead ? '💀 ' : ''}{charMap[charId]?.name ?? charId}</span>
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ opacity: 0.5 }}>
                      <th style={{ textAlign: 'left', padding: '1px 3px', fontWeight: 'normal' }}>能力</th>
                      <th style={{ textAlign: 'right', padding: '1px 3px', fontWeight: 'normal' }}>現在値</th>
                      <th style={{ textAlign: 'right', padding: '1px 3px', fontWeight: 'normal' }}>最大値</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(stats).map(([key, val]) => (
                      <tr key={key}>
                        <td style={{ padding: '2px 3px' }}>【{key}】</td>
                        <td style={{ textAlign: 'right', padding: '2px 3px', fontVariantNumeric: 'tabular-nums', color: val.current <= 0 ? 'var(--danger-color, #e55)' : undefined }}>{val.current}</td>
                        <td style={{ textAlign: 'right', padding: '2px 3px', fontVariantNumeric: 'tabular-nums', opacity: 0.7 }}>{val.max}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {isDead && <div style={{ marginTop: 4, fontSize: '0.85em', opacity: 0.7 }}>死亡 — 死者視点で継続</div>}
              </div>
            )
          })}
        </div>
      )}
      </div>

      <div className="session-controls">
        {humanCharId && (
          <>
            <div className="session-controls-row">
              <button
                className={`auto-advance-btn ${autoAdvance ? 'active' : ''}`}
                onClick={toggleAutoAdvance}
                disabled={waitingForHuman}
                title={autoAdvance ? t('session.ctrl.autoAdvance.stopTitle') : t('session.ctrl.autoAdvance.startTitle')}
              >
                {autoAdvance ? t('session.ctrl.autoBtn.stop') : t('session.ctrl.autoBtn.auto')}
              </button>
              <input
                className="keeper-input"
                style={{ flex: 1 }}
                value={humanInput}
                onChange={e => setHumanInput(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addHumanAction() } }}
                placeholder={interruptMode ? t('session.ctrl.interruptInput.placeholder') : waitingForHuman ? t('session.ctrl.humanInput.placeholder') : ''}
                disabled={!waitingForHuman && !interruptMode}
              />
              <button onClick={addHumanAction} disabled={(!waitingForHuman && !interruptMode) || !humanInput.trim() || (actionsPerTurn > 0 && humanPending.length >= actionsPerTurn)} className="keeper-add-btn">{t('session.ctrl.queueBtn')}</button>
              <button onClick={() => submitHumanTurn(interruptMode ? 'interrupt' : 'send')} disabled={(!waitingForHuman && !interruptMode) || (humanPending.length === 0 && !humanInput.trim())} className="keeper-send-btn">{interruptMode ? t('session.ctrl.interruptDoneBtn') : t('session.ctrl.speakDoneBtn')}</button>
              <button onClick={() => { setHumanInput(''); setHumanPending([]); setHasDiscarded(true) }} disabled={humanPending.length === 0 || hasDiscarded} className="keeper-redo-btn">{t('session.ctrl.discardBtn')}</button>
              <button onClick={() => nextTurn(undefined, actionsPerTurn)} disabled={waitingForHuman || interruptMode || loading || autoAdvance} className="next-btn">{t('session.ctrl.nextBtn')}</button>
              <button onClick={() => submitHumanTurn('skip')} disabled={!waitingForHuman} className="keeper-add-btn" title={t('session.ctrl.skipBtn.title')}>{t('session.ctrl.skipBtn')}</button>
            </div>
            <div className="session-controls-row">
              <button onClick={() => submitHumanTurn('extend')} disabled={!waitingForHuman || (humanPending.length === 0 && !humanInput.trim()) || (counters[humanCharId] ?? 0) < 1} className="keeper-add-btn" title={t('session.ctrl.extendBtn.title')}>{t('session.ctrl.extendBtn')}</button>
              <button onClick={() => { setInterruptMode(true); setHasDiscarded(false) }} disabled={interruptMode || waitingForHuman || (counters[humanCharId] ?? 0) < 2} className="keeper-add-btn" title={t('session.ctrl.interruptBtn.title')}>{t('session.ctrl.interruptBtn')}</button>
              {initiative.length > 1 && (
                <>
                  <select
                    className="keeper-input"
                    style={{ flex: 'none', width: 'auto', maxWidth: 120 }}
                    value={designateTarget}
                    onChange={e => setDesignateTarget(e.target.value)}
                  >
                    <option value="">{t('session.ctrl.designateSelect.empty')}</option>
                    {initiative.filter(id => id !== humanCharId).map(id => (
                      <option key={id} value={id}>{nameMap[id] || id}</option>
                    ))}
                  </select>
                  <button onClick={designateNext} disabled={!designateTarget} className="keeper-add-btn">{t('session.ctrl.designateBtn')}</button>
                </>
              )}
              {t2iBackend && (
                <button
                  onClick={handleHumanGenerateImage}
                  disabled={sceneImageStatus === 'generating' || messages.length === 0 || (counters[humanCharId] ?? 0) < 1}
                  className="scene-image-btn"
                  title={t('session.ctrl.sceneImageBtn.title')}
                >
                  {sceneImageStatus === 'generating' ? '🎨...' : '🎨 [-1]'}
                </button>
              )}
              <button onClick={() => setShowVoteDialog(true)} disabled={autoAdvance || (counters[humanCharId] ?? 0) < 3} className="keeper-add-btn" title={t('session.ctrl.voteBtn.title')}>{t('session.ctrl.voteBtn')}</button>
              {false && trpgMode && Object.keys(charSheetData).length > 0 && (
                <select className="session-select" style={{ flex: 'none', maxWidth: 80 }} value={autoJudgmentStat} onChange={e => { setAutoJudgmentStat(e.target.value); autoJudgmentStatRef.current = e.target.value }} title={t('trpg.autoJudgment.title')}>
                  <option value="">{t('trpg.autoJudgment')}</option>
                  {[...new Set(Object.values(charSheetData).flatMap((s: any) => Object.keys(s?.stats ?? {})))].map(stat => (
                    <option key={stat} value={stat}>{stat}</option>
                  ))}
                </select>
              )}
              {trpgMode && charSheetData[humanCharId] && <DiceRow onOpenDialog={openDiceDialogForHuman} />}
            </div>
            {humanPending.length > 0 && (
              <div className="keeper-pending">
                <span className="keeper-pending-count">{t('session.ctrl.humanQueue.count', { n: humanPending.length })}</span>
                {humanPending.map((a, i) => (
                  <span key={i} className="keeper-pending-item">{i + 1}. {a}</span>
                ))}
              </div>
            )}
          </>
        )}
        {!humanCharId && waitingForKeeperTurn && (
          <div className="session-controls-row" style={{ background: 'rgba(74,108,247,0.12)', border: '1px solid #4a6cf7', borderRadius: 8, padding: '6px 10px' }}>
            <span style={{ fontWeight: 600, color: '#4a6cf7' }}>{t('trpg.keeper.turnBanner')}</span>
          </div>
        )}
        {!humanCharId && <div className="session-controls-row">
          <button
            className={`auto-advance-btn ${autoAdvance ? 'active' : ''}`}
            onClick={toggleAutoAdvance}
            title={autoAdvance ? t('session.ctrl.autoAdvance.stopTitle') : t('session.ctrl.autoAdvance.startTitle')}
          >
            {autoAdvance ? t('session.ctrl.autoBtn.stop') : t('session.ctrl.autoBtn.auto')}
          </button>
          <input
            className="keeper-input"
            type="text"
            value={keeperInput}
            onChange={e => setKeeperInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addKeeperAction() } }}
            placeholder={t('session.ctrl.keeperInput.placeholder')}
          />
          <button onClick={addKeeperAction} disabled={!keeperInput.trim() || pendingActions.length >= actionsPerTurn} className="keeper-add-btn">{t('session.ctrl.queueBtn')}</button>
          <button onClick={commitKeeperActions} disabled={pendingActions.length === 0} className="keeper-send-btn">{t('session.ctrl.keeperSendBtn')}</button>
          <button onClick={() => setPendingActions([])} disabled={pendingActions.length === 0} className="keeper-redo-btn">{t('session.ctrl.discardBtn')}</button>
          <button onClick={() => nextTurn(undefined, actionsPerTurn)} disabled={loading || autoAdvance} className="next-btn">{t('session.ctrl.nextBtn')}</button>
          {t2iBackend && (
            <button
              onClick={generateSceneImage}
              disabled={sceneImageStatus === 'generating' || messages.length === 0}
              className="scene-image-btn"
              title={t('session.ctrl.sceneImageBtn.titleKeeper')}
            >
              {sceneImageStatus === 'generating' ? '🎨...' : '🎨'}
            </button>
          )}
        </div>}
        {!humanCharId && <div className="session-controls-row">
          <button onClick={retakeTurn} disabled={loading || autoAdvance} className="retake-btn" title={t('session.ctrl.retakeBtn.title')}>{t('session.ctrl.retakeBtn')}</button>
          <button onClick={skipCurrentTurn} disabled={loading} className="keeper-add-btn" title={t('session.ctrl.skipBtnKeeper.title')}>{t('session.ctrl.skipBtnKeeper')}</button>
          {initiative.length > 1 && (
            <>
              <select
                className="keeper-input"
                style={{ flex: 'none', width: 'auto', maxWidth: 120 }}
                value={designateTarget}
                onChange={e => setDesignateTarget(e.target.value)}
              >
                <option value="">{t('session.ctrl.designateSelect.empty')}</option>
                {initiative.map(id => (
                  <option key={id} value={id}>{nameMap[id] || id}</option>
                ))}
              </select>
              <button onClick={designateNext} disabled={!designateTarget} className="keeper-add-btn">{t('session.ctrl.designateBtnKeeper')}</button>
            </>
          )}
          <button onClick={() => setShowVoteDialog(true)} disabled={autoAdvance} className="keeper-add-btn" title={t('session.ctrl.voteBtnKeeper.title')}>{t('session.ctrl.voteBtnKeeper')}</button>
          {false && trpgMode && Object.keys(charSheetData).length > 0 && (
            <select className="session-select" style={{ flex: 'none', maxWidth: 80 }} value={autoJudgmentStat} onChange={e => { setAutoJudgmentStat(e.target.value); autoJudgmentStatRef.current = e.target.value }} title={t('trpg.autoJudgment.title')}>
              <option value="">{t('trpg.autoJudgment')}</option>
              {[...new Set(Object.values(charSheetData).flatMap((s: any) => Object.keys(s?.stats ?? {})))].map(stat => (
                <option key={stat} value={stat}>{stat}</option>
              ))}
            </select>
          )}
          {trpgMode && Object.keys(charSheetData).length > 0 && <DiceRow onOpenDialog={openDiceDialog} onAdvanceScene={advanceScene} />}
        </div>}
      </div>

      {pendingActions.length > 0 && (
        <div className="keeper-pending">
          <span className="keeper-pending-count">{t('session.ctrl.keeperQueue.count', { n: pendingActions.length })}</span>
          {pendingActions.map((a, i) => (
            <span key={i} className="keeper-pending-item">{i + 1}. {a}</span>
          ))}
        </div>
      )}

      {showVoteDialog && (
        <div className="plot-dialog-overlay" onClick={e => { if (e.target === e.currentTarget) setShowVoteDialog(false) }}>
          <div className="plot-dialog" style={{ maxWidth: 400 }}>
            <div className="plot-dialog-header">
              <span>{t('session.voteDialog.header')}</span>
              <button className="plot-dialog-close" onClick={() => setShowVoteDialog(false)}>×</button>
            </div>
            <div className="plot-dialog-body" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ fontSize: '0.85em', color: '#aaa', display: 'block', marginBottom: 4 }}>{t('session.voteDialog.typeLabel')}</label>
                <select className="session-select" value={voteType} onChange={e => setVoteType(e.target.value as any)}>
                  <option value="topic_change">{t('session.voteDialog.type.topicChange')}</option>
                  <option value="expel">{t('session.voteDialog.type.expel')}</option>
                  <option value="end_session">{t('session.voteDialog.type.endSession')}</option>
                </select>
              </div>
              {voteType === 'topic_change' && (
                <div>
                  <label style={{ fontSize: '0.85em', color: '#aaa', display: 'block', marginBottom: 4 }}>{t('session.voteDialog.newTopicLabel')}</label>
                  <input className="session-topic-input" value={voteDetail} onChange={e => setVoteDetail(e.target.value)} placeholder={t('session.voteDialog.newTopicPlaceholder')} />
                </div>
              )}
              {voteType === 'expel' && (
                <div>
                  <label style={{ fontSize: '0.85em', color: '#aaa', display: 'block', marginBottom: 4 }}>{t('session.voteDialog.expelTargetLabel')}</label>
                  <select className="session-select" value={voteTarget} onChange={e => setVoteTarget(e.target.value)}>
                    <option value="">{t('session.voteDialog.expelSelect.empty')}</option>
                    {initiative.map(id => (
                      <option key={id} value={id}>{nameMap[id] || id}</option>
                    ))}
                  </select>
                </div>
              )}
              {humanCharId && (
                <div>
                  <label style={{ fontSize: '0.85em', color: '#aaa', display: 'block', marginBottom: 4 }}>{t('session.voteDialog.proposerLabel', { name: humanCharName })}</label>
                  <textarea
                    className="plot-dialog-textarea"
                    value={voteProposerText}
                    onChange={e => setVoteProposerText(e.target.value)}
                    placeholder={t('session.voteDialog.proposerPlaceholder')}
                    rows={3}
                  />
                </div>
              )}
            </div>
            <div className="plot-dialog-footer">
              <button className="novel-hdr-btn apply-btn" onClick={startDeliberation} disabled={voteLoading || (voteType === 'expel' && !voteTarget)}>
                {voteLoading ? t('session.voteDialog.startBtn.loading') : t('session.voteDialog.startBtn')}
              </button>
            </div>
          </div>
        </div>
      )}
      {pendingJudgments.length > 0 && (
        <div className="dialog-backdrop">
          <div className="dialog" style={{ minWidth: 280, maxWidth: 400 }}>
            <div className="dialog-header">
              <span>{t('trpg.judgment.header')}</span>
            </div>
            <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 8 }}>
              {pendingJudgments.map((j, idx) => (
                <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.9em' }}>
                  <span style={{ flex: 1, opacity: 0.85 }}>
                    {j.stat_value > 0
                      ? t('trpg.judgment.item', { name: j.character_name, stat: j.stat, value: j.stat_value })
                      : t('trpg.judgment.itemNoValue', { name: j.character_name, stat: j.stat })}
                  </span>
                  <button
                    className="keeper-redo-btn"
                    style={{ fontSize: '0.8em', padding: '2px 8px' }}
                    onClick={() => rollDamage(j.character_id, j.character_name)}
                  >{t('trpg.judgment.damage')}</button>
                </div>
              ))}
            </div>
            <div style={{ padding: '8px 16px 16px', display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="keeper-redo-btn" onClick={() => {
                setPendingJudgments([])
                if (wasAutoAdvancingRef.current) {
                  setAutoAdvance(true)
                  autoAdvanceRef.current = true
                }
                wasAutoAdvancingRef.current = false
                setTimeout(() => nextTurn(sessionId, actionsPerTurnRef.current), 300)
              }}>{t('trpg.judgment.skip')}</button>
              <button className="novel-hdr-btn apply-btn" onClick={rollAllPendingJudgments}>{t('trpg.judgment.rollAll')}</button>
            </div>
          </div>
        </div>
      )}
      {showDiceDialog && (() => {
        const sheetChars = initiative.filter(id => charSheetData[id])
        const allStatKeys = [...new Set(sheetChars.flatMap(id => Object.keys(charSheetData[id]?.stats ?? {})))]
        const allSkillKeys = [...new Set(sheetChars.flatMap(id => Object.keys(charSheetData[id]?.skills ?? {})))]
        const allSelected = sheetChars.length > 0 && sheetChars.every(id => diceDialogChars.includes(id))
        const noChars = diceDialogChars.length === 0
        return (
          <div className="plot-dialog-overlay" onClick={e => { if (e.target === e.currentTarget) setShowDiceDialog(false) }}>
            <div className="plot-dialog" style={{ maxWidth: 440 }}>
              <div className="plot-dialog-header">
                <span>{t('trpg.diceDialog.header')}</span>
                <button className="plot-dialog-close" onClick={() => setShowDiceDialog(false)}>×</button>
              </div>
              <div className="plot-dialog-body" style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: 16 }}>
                {diceDialogLocked ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 600 }}>{t('trpg.diceDialog.targets')}</span>
                    {diceDialogChars[0] && (
                      <>
                        <img src={`/api/characters/${diceDialogChars[0]}/icon`} alt="" style={{ width: 22, height: 22, borderRadius: '50%', objectFit: 'cover' }} />
                        <span>{charMap[diceDialogChars[0]]?.name ?? diceDialogChars[0]}</span>
                      </>
                    )}
                  </div>
                ) : (
                  <div>
                    <div style={{ fontWeight: 600, marginBottom: 8 }}>{t('trpg.diceDialog.targets')}</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 6 }}>
                      {sheetChars.map(id => {
                        const checked = diceDialogChars.includes(id)
                        return (
                          <label key={id} style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', padding: '3px 8px', borderRadius: 12, border: `1px solid ${checked ? '#4a6cf7' : 'var(--border-color, #aaa)'}`, background: checked ? 'rgba(74,108,247,0.1)' : 'transparent' }}>
                            <input type="checkbox" checked={checked} style={{ margin: 0 }} onChange={() =>
                              setDiceDialogChars(prev => checked ? prev.filter(x => x !== id) : [...prev, id])
                            } />
                            <img src={`/api/characters/${id}/icon`} alt="" style={{ width: 18, height: 18, borderRadius: '50%', objectFit: 'cover' }} />
                            <span style={{ fontSize: '0.88em' }}>{charMap[id]?.name ?? id}</span>
                          </label>
                        )
                      })}
                    </div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button className="novel-hdr-btn" style={{ fontSize: '0.78em', padding: '2px 10px' }} onClick={() => setDiceDialogChars(sheetChars)}>{allSelected ? t('trpg.diceDialog.allSelected') : t('trpg.diceDialog.selectAll')}</button>
                      <button className="novel-hdr-btn" style={{ fontSize: '0.78em', padding: '2px 10px' }} onClick={() => setDiceDialogChars([])}>{t('trpg.diceDialog.deselect')}</button>
                    </div>
                  </div>
                )}
                {allStatKeys.length > 0 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 600, minWidth: 72, flexShrink: 0 }}>{t('trpg.diceDialog.stat')}</span>
                    <select className="session-select" style={{ flex: 1 }} value={diceDialogStatKey} onChange={e => setDiceDialogStatKey(e.target.value)}>
                      <option value="">選択…</option>
                      {allStatKeys.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <button className="keeper-send-btn" disabled={noChars || !diceDialogStatKey} onClick={() => rollDiceDialog('stat', diceDialogStatKey)}>{t('trpg.diceDialog.rollBtn')}</button>
                  </div>
                )}
                {allSkillKeys.length > 0 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 600, minWidth: 72, flexShrink: 0 }}>{t('trpg.diceDialog.skill')}</span>
                    <select className="session-select" style={{ flex: 1 }} value={diceDialogSkillKey} onChange={e => setDiceDialogSkillKey(e.target.value)}>
                      <option value="">選択…</option>
                      {allSkillKeys.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <button className="keeper-send-btn" disabled={noChars || !diceDialogSkillKey} onClick={() => rollDiceDialog('skill', diceDialogSkillKey)}>{t('trpg.diceDialog.rollBtn')}</button>
                  </div>
                )}
              </div>
              <div className="plot-dialog-footer">
                <button className="novel-hdr-btn" onClick={() => setShowDiceDialog(false)}>{t('dialog.closeBtn')}</button>
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
