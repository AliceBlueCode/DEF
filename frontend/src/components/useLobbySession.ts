import { useRef, useState } from 'react'

export type RuleOption = { id: string; label: string }
export type DirectiveOption = { id: string; label: string; rating: string; recommended_for: number[] }
export type RulebookOption = { id: string; label: string; dice_system: string }
export type ScenarioOption = { id: string; label: string; synopsis: string; rulebook_id: string }

type SavedSession = {
  filename: string
  topic: string
  saved_at: string
  round: number
  character_names: string[]
  trpg_scenario_title?: string
  rule_set?: string
  rule_set_label?: string
  online_mode?: boolean
}

// SessionTab.tsx から分離: セッション作成/ロビー設定・セッションルール編集ダイアログ。
// `SessionTab.tsx`分割の第二段階（TODO.md「SessionTab.tsxのコンポーネント分割」参照）。
export function useLobbySession() {
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
  const [inviteCode, setInviteCode] = useState('')
  const [sessionStarting, setSessionStarting] = useState(false)
  const [lobbyMode, setLobbyMode] = useState(false)
  const [lobbyActive, setLobbyActive] = useState(false)  // 参加者側: ホスト開始待ち
  const [lobbyMaxPlayers, setLobbyMaxPlayers] = useState(4)
  const [lobbyTrpgMode, setLobbyTrpgMode] = useState(true)
  const [keeperSource, setKeeperSource] = useState<'ai' | 'participant'>('ai')
  const [hostRole, setHostRole] = useState<'keeper' | 'player' | 'observer'>('keeper')
  const [hostCharForLobby, setHostCharForLobby] = useState('')
  const [lobbyKeeperCharId, setLobbyKeeperCharId] = useState('')
  const [lobbyKeeperCharName, setLobbyKeeperCharName] = useState('')
  const [savedSessions, setSavedSessions] = useState<SavedSession[]>([])
  const [showRuleDialog, setShowRuleDialog] = useState(false)
  const [ruleDraft, setRuleDraft] = useState('')
  const [ruleEditId, setRuleEditId] = useState('')

  const fetchSavedSessions = () => {
    fetch('/api/session/saved')
      .then(r => r.json())
      .then(d => setSavedSessions(d.sessions || []))
      .catch(() => {})
  }

  // ロビー中のセッション設定変更（お題・ルール・ルールブック・シナリオ・参加人数）。ホスト専用
  const patchLobbySettings = (body: Record<string, string | number>, sessionIdRef: React.RefObject<string>, hostTokenRef: React.RefObject<string>) => {
    if (!sessionIdRef.current) return
    void fetch(`/api/session/${sessionIdRef.current}/lobby/settings`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${hostTokenRef.current}` },
      body: JSON.stringify(body),
    })
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

  return {
    selectedChars, setSelectedChars,
    topic, setTopic,
    ruleSet, setRuleSet,
    trpgMode, setTrpgMode, trpgModeRef,
    rulebookOptions, setRulebookOptions,
    selectedRulebook, setSelectedRulebook,
    scenarioOptions, setScenarioOptions,
    selectedScenario, setSelectedScenario,
    ruleOptions, setRuleOptions,
    directiveSet, setDirectiveSet,
    directiveOptions, setDirectiveOptions,
    inviteCode, setInviteCode,
    sessionStarting, setSessionStarting,
    lobbyMode, setLobbyMode,
    lobbyActive, setLobbyActive,
    lobbyMaxPlayers, setLobbyMaxPlayers,
    lobbyTrpgMode, setLobbyTrpgMode,
    keeperSource, setKeeperSource,
    hostRole, setHostRole,
    hostCharForLobby, setHostCharForLobby,
    lobbyKeeperCharId, setLobbyKeeperCharId,
    lobbyKeeperCharName, setLobbyKeeperCharName,
    savedSessions, setSavedSessions,
    showRuleDialog, setShowRuleDialog,
    ruleDraft, setRuleDraft,
    ruleEditId, setRuleEditId,
    fetchSavedSessions, patchLobbySettings,
    openRuleDialog, saveRule, applyRule,
  }
}
