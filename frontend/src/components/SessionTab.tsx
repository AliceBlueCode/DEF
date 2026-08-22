import { useState, useEffect, useRef } from 'react'
import { useT } from '../i18n'
import InvitePanel from './InvitePanel'
import InviteCodeDisplay from './InviteCodeDisplay'
import JoinDialog from './JoinDialog'
import ParticipantList from './ParticipantList'
import {
  type Character,
  type SessionMessage,
  reconstructMessages,
  saveSessionRestoreState,
  loadSessionRestoreState,
  clearSessionRestoreState,
  isContentBlocked,
} from './sessionUtils'
import { useSafetyFilter } from './useSafetyFilter'
import { useTurnState } from './useTurnState'
import { useHumanTurn } from './useHumanTurn'
import { useVoteAndDesignate } from './useVoteAndDesignate'
import { useCharSheetAndDice, type KeeperJudgment } from './useCharSheetAndDice'
import { useCharBackendConfig } from './useCharBackendConfig'
import { useAiAssignWizard } from './useAiAssignWizard'
import { useLobbySession } from './useLobbySession'
import { useParticipants } from './useParticipants'

type Props = {
  characters: Character[]
  backend: string
  ttsBackend: string
  t2iBackend: string
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

export default function SessionTab({ characters, backend, t2iBackend }: Props) {
  const t = useT()

  // ── 分割済みカスタムフック（TODO.md「SessionTab.tsxのコンポーネント分割」参照）──
  // 状態宣言とそれ単体で完結するハンドラのみをフックへ移し、handleSessionEvent等の
  // 複数ドメインにまたがる横断関数はこのコンポーネント本体に残す（session.py分割の
  // 「機能グループ別ファイル分割」と同じ発想）。
  const {
    allowedSexual, setAllowedSexual, allowedSexualRef,
    allowedViolence, setAllowedViolence, allowedViolenceRef,
    safetyLevel, setSafetyLevel, safetyLevelRef,
    auditWarnings, setAuditWarnings,
    setTtsEnabled, ttsEnabledRef, ttsHumanEnabledRef,
  } = useSafetyFilter()
  const {
    round, setRound,
    currentSceneIndex, setCurrentSceneIndex,
    activeTurnCharId, setActiveTurnCharId,
    initiative, setInitiative, initiativeRef,
    autoAdvance, setAutoAdvance, autoAdvanceRef,
    autoStopMsg, setAutoStopMsg,
    actionsPerTurn, setActionsPerTurn, actionsPerTurnRef,
    counters, setCounters,
    maxCounter, setMaxCounter, maxCounterRef,
    loading, setLoading,
    sceneImageStatus, setSceneImageStatus,
    standingFallback, setStandingFallback,
    wasAutoAdvancingRef, keeperFiredRoundRef,
    capCounters,
  } = useTurnState()
  const {
    humanKeeper, setHumanKeeper,
    waitingForKeeperTurn, setWaitingForKeeperTurn, isHumanKeeperRef,
    keeperInput, setKeeperInput,
    pendingActions, setPendingActions,
    waitingForHuman, setWaitingForHuman,
    humanCharId, setHumanCharId,
    humanCharName, setHumanCharName,
    humanInput, setHumanInput,
    humanPending, setHumanPending,
    interruptMode, setInterruptMode,
    hasDiscarded, setHasDiscarded,
    addKeeperAction: _addKeeperAction, addHumanAction: _addHumanAction,
  } = useHumanTurn()
  const {
    designateTarget, setDesignateTarget,
    showVoteDialog, setShowVoteDialog,
    voteType, setVoteType,
    voteDetail, setVoteDetail,
    voteTarget, setVoteTarget,
    voteProposerText, setVoteProposerText,
    voteLoading, setVoteLoading,
  } = useVoteAndDesignate()
  const {
    charSheetData, setCharSheetData,
    showSheetPanel, setShowSheetPanel,
    showDiceDialog, setShowDiceDialog,
    diceDialogChars, setDiceDialogChars,
    diceDialogLocked,
    diceDialogStatKey, setDiceDialogStatKey,
    diceDialogSkillKey, setDiceDialogSkillKey,
    autoJudgmentStat, setAutoJudgmentStat, autoJudgmentStatRef,
    pendingJudgments, setPendingJudgments,
    openDiceDialog: _openDiceDialog, openDiceDialogForHuman: _openDiceDialogForHuman,
    isCharDead, shouldApplyDamage, normalizeSheetStats,
  } = useCharSheetAndDice()
  const {
    charBackends, setCharBackends,
    llmBackendOptions, setLlmBackendOptions,
    showBackendDialog, setShowBackendDialog,
    charGameSheets, setCharGameSheets,
    charGameSheetOptions,
    showGameSheetDialog, setShowGameSheetDialog,
    charRoles, setCharRoles,
    keeperCharId, keeperCount,
    openGameSheetDialog: _openGameSheetDialog,
  } = useCharBackendConfig()
  const {
    assignDialogTarget, setAssignDialogTarget,
    assignStep, setAssignStep,
    assignCharId,
    assignSheetOptions,
    assignSheetId, setAssignSheetId,
    assignBackendId, setAssignBackendId,
    openAssignDialog, selectAssignChar: _selectAssignChar,
  } = useAiAssignWizard()
  const {
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
    savedSessions,
    showRuleDialog, setShowRuleDialog,
    ruleDraft, setRuleDraft,
    ruleEditId,
    fetchSavedSessions, patchLobbySettings: _patchLobbySettings,
    openRuleDialog, saveRule, applyRule,
  } = useLobbySession()
  const {
    participants, setParticipants,
    showJoinDialog, setShowJoinDialog,
    myRole, setMyRole, myRoleRef,
    myCharIdRef,
    extraNameMap, setExtraNameMap,
    showParticipantPanel, setShowParticipantPanel,
    setIconVersion,
    iconUrl, standingUrl,
    aiTakenOverChars, setAiTakenOverChars,
  } = useParticipants()

  // ── セッション識別・接続まわりはメッセージ履歴と同様、ほぼ全域から参照されるため
  // 独立させずこのコンポーネント本体に残す（TODO.md参照）。
  const [sessionId, setSessionId] = useState('')
  const sessionIdRef = useRef('')
  const [messages, setMessages] = useState<SessionMessage[]>([])
  // 接続時に取得した既存履歴のうち、直近分以外を隠しておく置き場(ChatTab.tsxの
  // hiddenHistory/hasMoreと同じ考え方)。リロード・途中参加時に会話が全部消える
  // 問題(2026-08-08発覚)への対応。
  const [hiddenSessionHistory, setHiddenSessionHistory] = useState<SessionMessage[]>([])
  // GET /{session_id}のname_map（サーバー正本）。ヘッダーの発言順表示は従来
  // characters（App.tsxからのprop、ローカル専用ポートの/api/characters/でしか
  // 取得できない）とparticipantsだけから名前を合成していたため、公開ポート経由の
  // ゲストではAIキャラの名前が解決できずraw character_id（日付サフィックス付き）が
  // そのまま表示されていた（2026-08-16、リロード動確中にユーザーが実機で発見）。
  // 公開ポートでも読めるGET /{session_id}のname_mapを正本として持たせる。
  const [sessionNameMap, setSessionNameMap] = useState<Record<string, string>>({})
  // GET /{session_id}のchar_colors（サーバー正本）。imageColorも上と全く同じ理由
  // （charactersがローカル専用ポートのAPIでしか取れず、公開ポート経由のゲストは
  // 常に空のまま）で欠落していた（2026-08-16）。characters一覧が読めないゲストの
  // ためのimage_color配信経路。
  const [sessionCharColors, setSessionCharColors] = useState<Record<string, string>>({})
  const initialHistoryFetchedForRef = useRef('')
  // AUDIO_READY（human_turn_action・vote/deliberateの人間/AI発言読み上げ）の
  // request_id → messages配列インデックス対応表。AUDIO_READY受信時にここを引いて
  // 該当メッセージへaudioUrlを反映する（2026-08-10、リスナー未実装で自動再生が
  // 常に死んでいたのを発見・修正）。
  const audioRequestIndexRef = useRef<Record<string, number>>({})
  const hostTokenRef = useRef('')
  const endingRef = useRef(false)  // endSession 再入ガード（SESSION_ENDED 受信での再実行防止）
  const wsRef = useRef<WebSocket | null>(null)
  const wsReconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // sessionStorageからの自動復帰試行中フラグ。復帰時の最初の接続が4001(認証切れ)/
  // 4004(セッション消滅)で閉じた場合は、無限に再接続を試み続けず諦めて通常の
  // 作成/参加画面に戻す(トークン失効・ホストのセッション終了後にリロードした場合等)。
  const isRestoringRef = useRef(false)
  const [saveStatus, setSaveStatus] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // フック側は他ドメインのstate/refを知らないため、必要な引数を橋渡しするラッパー。
  const addKeeperAction = () => _addKeeperAction(actionsPerTurnRef)
  const addHumanAction = () => _addHumanAction(actionsPerTurnRef)
  const openDiceDialog = () => _openDiceDialog(initiative)
  const openDiceDialogForHuman = () => _openDiceDialogForHuman(humanCharId)
  const openGameSheetDialog = () => _openGameSheetDialog(selectedChars)
  const selectAssignChar = (charId: string) => _selectAssignChar(charId, lobbyTrpgMode)
  const patchLobbySettings = (body: Record<string, string | number>) => _patchLobbySettings(body, sessionIdRef, hostTokenRef)

  // JWT を自動付与する fetch ラッパー（hostTokenRef = 自タブのトークン）
  const authFetch = (path: string, init: RequestInit = {}) =>
    fetch(path, {
      ...init,
      headers: {
        ...(init.headers as Record<string, string> | undefined ?? {}),
        ...(hostTokenRef.current ? { 'Authorization': `Bearer ${hostTokenRef.current}` } : {}),
      },
    })

  // レスポンスをJSONパースし、data.errorの形にそろえて返す。
  // バックエンドは業務エラーを200+{error}、認証/権限/レート制限エラーをHTTPException(401/403/404/429等)+{detail}で
  // 返すため、res.okを見ずにdata.errorだけをチェックするとHTTPException側を素通りしてしまう
  // （例: 追放されJWTが失効したプレイヤーの操作が、実際は401で拒否されているのに成功したかのように見えるバグ）。
  const parseJsonResponse = async (res: Response): Promise<any> => {
    const data = await res.json().catch(() => ({}))
    if (!res.ok && !data.error) return { ...data, error: data.detail || `HTTP ${res.status}` }
    return data
  }

  // characters（App.tsxのprop、ローカル専用ポートの/api/characters/でしか取得できず
  // 公開ポート経由のゲストでは常に空）を主としつつ、そこに無い/image_colorが
  // 欠けているキャラをsessionCharColors（GET /{session_id}経由、公開ポートでも
  // 読める）で補うCharacterマップを組み立てる（2026-08-16）。3箇所
  // （履歴再構築・imageColor補完useEffect・WSイベントハンドラ群）で同じ形の
  // マップが必要なため共通化した。
  const buildCharMap = (): Record<string, Character> => {
    const map: Record<string, Character> = Object.fromEntries(characters.map(c => [c.id, c]))
    for (const [id, color] of Object.entries(sessionCharColors)) {
      if (!map[id]) {
        map[id] = { id, name: sessionNameMap[id] || id, image_color: color }
      } else if (!map[id].image_color) {
        map[id] = { ...map[id], image_color: color }
      }
    }
    return map
  }

  // ── マウント時のセッション復帰（リロード対策） ──────────────────
  // sessionStorageに以前のセッション情報が残っていれば、作成/参加画面を経由せず
  // 直接そのセッションへの接続を試みる。sessionIdがセットされると下のWS接続用
  // useEffectが起動する。復帰後に何ターンか進んでいた場合の状態(round/counters等)
  // はWS接続時に届くイベントで徐々に追いつく想定であり、ここでは接続の再開自体
  // のみを担う(完全な状態スナップショット取得はしていない — 既知の制約)。
  useEffect(() => {
    if (sessionId) return
    const restore = loadSessionRestoreState()
    if (!restore) return
    isRestoringRef.current = true
    sessionIdRef.current = restore.sessionId
    hostTokenRef.current = restore.token
    myRoleRef.current = restore.role
    setMyRole(restore.role)
    if (restore.charId) {
      myCharIdRef.current = restore.charId
      setHumanCharId(restore.charId)
      setHumanCharName(restore.displayName || restore.charId)
    }
    setLobbyActive(false)
    setSessionId(restore.sessionId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── WebSocket 接続（sessionId 確定後に接続・exponential backoff 再接続）──
  // 初回接続前に既存の会話履歴を1回だけ取得する。リロード・途中参加・再接続時に
  // 会話が全部消える問題(2026-08-08発覚)への対応。WS再接続(ws.onclose→connect再実行)
  // 側では取得しない — 取得済みのmessagesをそのまま保持し続ければ十分なため。
  useEffect(() => {
    if (!sessionId) return
    let retries = 0
    let cancelled = false
    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${proto}//${window.location.host}/api/session/${sessionId}/ws`)
      wsRef.current = ws
      ws.onopen = () => {
        retries = 0
        ws.send(JSON.stringify({ type: 'auth', token: hostTokenRef.current }))
      }
      ws.onmessage = (e) => {
        // サーバーは認証成功後にしかメッセージを送らないため、何か1件でも
        // 受信できた時点で復帰試行は成功とみなしてよい。
        isRestoringRef.current = false
        try { void handleSessionEvent(JSON.parse(e.data as string)) } catch {}
      }
      ws.onclose = (event) => {
        wsRef.current = null
        if (!sessionIdRef.current) return
        // sessionStorageからの復帰試行における最初の接続が認証切れ(4001)/
        // セッション消滅(4004)で閉じた場合は、無限リトライせず諦めて通常の
        // 作成/参加画面に戻す。
        if (isRestoringRef.current && retries === 0 && (event.code === 4001 || event.code === 4004)) {
          isRestoringRef.current = false
          clearSessionRestoreState()
          sessionIdRef.current = ''
          setSessionId('')
          setMyRole('host')
          myCharIdRef.current = ''
          setHumanCharId('')
          setHumanCharName('')
          return
        }
        const delay = Math.min(1000 * Math.pow(2, retries), 16000)
        retries++
        wsReconnectTimerRef.current = setTimeout(connect, delay)
      }
    }

    const RECENT_COUNT = 20
    const connectAfterInitialHistory = async () => {
      if (initialHistoryFetchedForRef.current !== sessionId) {
        initialHistoryFetchedForRef.current = sessionId
        try {
          const res = await fetch(`/api/session/${sessionId}`, {
            headers: hostTokenRef.current ? { 'Authorization': `Bearer ${hostTokenRef.current}` } : {},
          })
          const data = await res.json()
          if (!res.ok) console.error('initial history fetch failed:', data.detail || res.status)
          if (res.ok && !cancelled && data.session?.initiative) {
            initiativeRef.current = data.session.initiative
            setInitiative(data.session.initiative)
          }
          // trpgModeRefは自分でセッション作成したタブ(_initSession)以外では
          // 初期値falseのまま取り残されており、参加者/リロード後のタブでは
          // キーパー発火(isLastOfRound判定)が永久に起きない不具合があった
          // (2026-08-22発覚)。GET /{session_id}が返すtrpg_modeで復元する。
          if (res.ok && !cancelled && typeof data.session?.trpg_mode === 'boolean') {
            trpgModeRef.current = data.session.trpg_mode
            setTrpgMode(data.session.trpg_mode)
          }
          const nameMap: Record<string, string> = data.session?.name_map || {}
          if (res.ok && !cancelled && data.session?.name_map) {
            setSessionNameMap(nameMap)
          }
          const charColors: Record<string, string> = data.session?.char_colors || {}
          if (res.ok && !cancelled && data.session?.char_colors) {
            setSessionCharColors(charColors)
          }
          const history: any[] = res.ok ? (data.session?.history || []) : []
          if (history.length > 0 && !cancelled) {
            // setSessionCharColors直後はまだstateに反映されない（Reactの非同期更新）ため、
            // ここではstate（sessionCharColors）ではなく取得直後のcharColorsローカル変数を
            // 直接使ってマージする（buildCharMap()のクロージャ経由だと古い値のまま）。
            const charMapForHistory: Record<string, Character> = Object.fromEntries(characters.map(c => [c.id, c]))
            for (const [id, color] of Object.entries(charColors)) {
              if (!charMapForHistory[id]) charMapForHistory[id] = { id, name: nameMap[id] || id, image_color: color }
              else if (!charMapForHistory[id].image_color) charMapForHistory[id] = { ...charMapForHistory[id], image_color: color }
            }
            const reconstructed = reconstructMessages(history, nameMap, charMapForHistory)
            if (reconstructed.length > RECENT_COUNT) {
              setHiddenSessionHistory(reconstructed.slice(0, -RECENT_COUNT))
              setMessages(reconstructed.slice(-RECENT_COUNT))
            } else {
              setMessages(reconstructed)
            }
          }
        } catch { /* 取得失敗時は履歴なしで通常接続に進む(fail-open) */ }
      }
      if (!cancelled) connect()
    }
    void connectAfterInitialHistory()

    return () => {
      cancelled = true
      if (wsReconnectTimerRef.current !== null) {
        clearTimeout(wsReconnectTimerRef.current)
        wsReconnectTimerRef.current = null
      }
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [sessionId])

  // ── リロード復帰時、charactersが遅れて届いた場合のimageColor補完 ──────
  // connectAfterInitialHistory（上のuseEffect内）はマウント直後の1回だけ
  // reconstructMessagesを実行するが、その時点でApp.tsx側のキャラ一覧取得
  // （/api/characters/、非同期）がまだ完了していないと、charMapForHistoryが
  // 空のままimageColorが全メッセージでundefinedになり、二度と補完されない
  // 問題があった（2026-08-15発覚、2026-08-16修正）。charactersが後から
  // 届いた時点で、既存messages/hiddenSessionHistoryのimageColorを再計算する。
  // 公開ポート経由のゲストはcharactersが恒久的に空のままのため、
  // sessionCharColors（GET /{session_id}経由）の到着でも同様に再計算する。
  useEffect(() => {
    if (characters.length === 0 && Object.keys(sessionCharColors).length === 0) return
    const charMap = buildCharMap()
    const backfillImageColor = (msgs: SessionMessage[]) =>
      msgs.map(m => {
        const color = charMap[m.character_id]?.image_color
        return color && m.imageColor !== color ? { ...m, imageColor: color } : m
      })
    setMessages(prev => backfillImageColor(prev))
    setHiddenSessionHistory(prev => backfillImageColor(prev))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [characters, sessionCharColors])

  // ── WS イベントハンドラ ────────────────────────────────────────
  const handleSessionEvent = async (event: { type: string; payload: any }) => {
    if (event.type === 'ping') {
      wsRef.current?.send(JSON.stringify({ type: 'pong' }))
      return
    }
    if (event.type === 'AI_TURN_COMPLETED') {
      await processAITurnData(event.payload, sessionIdRef.current)
    }
    if (event.type === 'WAITING_FOR_HUMAN') {
      const p = event.payload
      if (typeof p.round === 'number') setRound(p.round)
      setActiveTurnCharId(p.character_id ?? '')
      if (p.counters) setCounters(capCounters(p.counters))
      setLoading(false)
      // オンライン: 自分のキャラターンのときだけプレイヤーコントロールに切り替える
      // myCharIdRef が空 = キーパー/オブザーバー → 変更しない
      if (myCharIdRef.current && myCharIdRef.current === p.character_id) {
        // 自分のターン中だけローカルの自動進行を一時停止する（送信後 wasAutoAdvancingRef で復帰）。
        // 他人のターンでは止めない: セッションの自動進行モードは人間ターンを跨いで継続し、
        // キーパータブの連鎖が止まると次のAIターンが再開できなくなる
        if (autoAdvanceRef.current) {
          wasAutoAdvancingRef.current = true
          setAutoAdvance(false)
          autoAdvanceRef.current = false
        }
        setWaitingForHuman(true)
        setHasDiscarded(false)
        setHumanCharId(p.character_id ?? '')
        setHumanCharName(p.character_name ?? '')
      }
    }
    if (event.type === 'AUTO_ADVANCE_CHANGED') {
      // 自動進行はセッション状態。キーパー権限のタブが切り替え、全タブがここで同期する
      const enabled = !!event.payload?.enabled
      setAutoAdvance(enabled)
      autoAdvanceRef.current = enabled
      if (enabled) setAutoStopMsg(null)
      else wasAutoAdvancingRef.current = false
    }
    if (event.type === 'HUMAN_ACTION') {
      const p = event.payload
      if (p.counters) setCounters(capCounters(p.counters))
      // 自分が送信したメッセージはローカルで既に追加済みなのでスキップ
      // keeper メッセージ: sender_role が自分のロールと一致する場合のみスキップ
      const isMine = (p.action === 'keeper' || p.action === 'keeper_skip')
        ? (p.sender_role === myRoleRef.current)
        : p.character_id === myCharIdRef.current
      // カウンター更新のみで表示不要なアクション
      const _counterOnlyActions = new Set(['generate_image', 'counter_adjust'])
      if (p.character_id && !isMine && !_counterOnlyActions.has(p.action)) {
        if (p.action === 'skip') {
          setMessages(prev => [...prev, {
            character_id: '_keeper',
            character_name: '⚙ System',
            text: t('session.msg.humanSkip', { name: p.character_name ?? p.character_id }),
            emotion: '', tags: [],
          }])
        } else if (p.action === 'keeper_skip') {
          setMessages(prev => [...prev, {
            character_id: '_keeper',
            character_name: '🎩 Keeper',
            text: t('session.msg.skipTurn', { name: p.character_name ?? p.character_id }),
            emotion: '', tags: [],
          }])
        } else if (p.action === 'designate') {
          setMessages(prev => [...prev, {
            character_id: '_keeper',
            character_name: '🎩 Keeper',
            text: t('session.msg.designate', { name: p.designated_name ?? p.designated_id ?? '' }),
            emotion: '', tags: [],
          }])
        } else if (p.action === 'vote_result') {
          setMessages(prev => [...prev, {
            character_id: '_keeper',
            character_name: '🗳 Vote',
            text: p.text ?? '',
            emotion: '', tags: [],
          }])
        } else {
          setMessages(prev => [...prev, {
            character_id: p.character_id,
            character_name: p.character_name ?? p.character_id,
            text: p.text ?? '',
            emotion: 'neutral',
            tags: [],
          }])
        }
      }
    }
    if (event.type === 'SESSION_IMAGE') {
      const p = event.payload
      if (p.url) {
        setMessages(prev => {
          // 生成中プレースホルダーがある or 既にこのURLが存在する = 自分が送ったタブ → スキップ
          const hasPlaceholder = prev.some((m: SessionMessage) => m.isSceneImage && m.imageStatus === 'generating')
          const hasUrl = prev.some((m: SessionMessage) => m.imageUrl === p.url)
          if (hasPlaceholder || hasUrl) return prev
          return [...prev, {
            character_id: '__scene__',
            character_name: '',
            text: '',
            emotion: '',
            tags: [],
            isSceneImage: true,
            imageStatus: 'done' as const,
            imageUrl: p.url as string,
          }]
        })
      }
    }
    if (event.type === 'AI_ERROR') {
      setLoading(false)
      if (autoAdvanceRef.current) {
        setAutoStopMsg(t('session.msg.autoStopError'))
        setAutoAdvance(false)
        autoAdvanceRef.current = false
      }
    }
    if (event.type === 'SESSION_ENDED') {
      // ホストは自分で endSession() を呼んでいるのでスキップ。
      // オブザーバー/プレイヤーはここで受け取ってリセットする。
      void endSession()
    }
    if (event.type === 'SESSION_STARTED') {
      setLobbyActive(false)
      if (event.payload?.initiative) {
        initiativeRef.current = event.payload.initiative
        setInitiative(event.payload.initiative)
      }
      if (event.payload?.name_map) {
        setExtraNameMap(prev => ({ ...prev, ...event.payload.name_map }))
      }
      if (event.payload?.participants) {
        setParticipants(prev => {
          const merged = [...prev]
          for (const p of event.payload.participants) {
            const pid = p.participant_id ?? p.character_id
            if (!merged.some(x => x.participant_id === pid)) {
              merged.push({ participant_id: pid, char_id: p.character_id, display_name: p.display_name, role: p.role ?? 'player', connected: true })
            }
          }
          return merged
        })
      }
    }
    if (event.type === 'PLAYER_JOINED') {
      const p = event.payload
      const pid = p.participant_id ?? p.character_id
      setParticipants(prev =>
        prev.some(x => x.participant_id === pid)
          ? prev
          : [...prev, { participant_id: pid, char_id: p.character_id, display_name: p.display_name, role: p.role ?? 'player', connected: true, claimed_char_id: p.claimed_char_id ?? '' }]
      )
      // オンラインセッション: キャラJSON持ち込み参加者をイニシアティブに追加
      if (p.role === 'player' && p.character_id) {
        setInitiative(prev =>
          prev.includes(p.character_id) ? prev : [...prev, p.character_id]
        )
        initiativeRef.current = [...new Set([...initiativeRef.current, p.character_id])]
      }
    }
    if (event.type === 'CHARACTER_AUDIT_SKIPPED') {
      // 持ち込みキャラのLLM審査を実行できず通過扱いになったケース（S-4）。
      // ホスト/GMだけに見せる（参加者全員への表示は不要な内部情報のため）。
      if (myRoleRef.current === 'host' || myRoleRef.current === 'gm') {
        const { character_id, reason } = event.payload ?? {}
        setAuditWarnings(prev => [
          ...prev,
          { id: `${character_id}-${Date.now()}`, characterId: character_id ?? '', reason: reason ?? '' },
        ])
      }
    }
    if (event.type === 'VISITOR_ICON_READY') {
      const cid = event.payload?.character_id
      if (cid) setIconVersion(prev => ({ ...prev, [cid]: Date.now() }))
    }
    if (event.type === 'TURN_IMAGE_READY') {
      const { character_id, round: r, turn: t, url } = event.payload ?? {}
      setMessages(prev => prev.map(m =>
        m.character_id === character_id && m.turnRound === r && m.turnTurn === t
          ? { ...m, imageStatus: 'done', imageUrl: url }
          : m
      ))
    }
    if (event.type === 'TURN_AUDIO_READY') {
      const { character_id, round: r, turn: t, url } = event.payload ?? {}
      let matchedTags: string[] | undefined
      setMessages(prev => prev.map(m => {
        if (m.character_id !== character_id || m.turnRound !== r || m.turnTurn !== t) return m
        matchedTags = m.tags
        return { ...m, audioUrl: url }
      }))
      // safetyLevel/許容タグ範囲外なら、表示側のhide+revealと同様に自動再生も止める
      // (テキスト・画像はhide+revealで既に対応済みだったが、音声だけ抜けていた・2026-08-09対応)。
      const audioBlocked = safetyLevelRef.current !== 'off' && !!matchedTags &&
        isContentBlocked(matchedTags, allowedSexualRef.current, allowedViolenceRef.current)
      if (url && ttsEnabledRef.current && !audioBlocked) void playAudio(url)
    }
    if (event.type === 'AUDIO_READY') {
      // human_turn_action / vote_deliberate 経由の人間・AI発言読み上げ。
      // request_idでaudioRequestIndexRefを引いて対象メッセージを特定する
      // （送信直後は同期レスポンスにURLが無く、生成完了後にこのイベントで届く）。
      const { character_id, request_id, url } = event.payload ?? {}
      const idx = request_id != null ? audioRequestIndexRef.current[request_id] : undefined
      if (url && idx != null) {
        delete audioRequestIndexRef.current[request_id]
        let matchedTags: string[] | undefined
        setMessages(prev => prev.map((m, i) => {
          if (i !== idx) return m
          matchedTags = m.tags
          return { ...m, audioUrl: url }
        }))
        const shouldPlay = character_id === myCharIdRef.current ? ttsHumanEnabledRef.current : ttsEnabledRef.current
        const audioBlocked = character_id !== myCharIdRef.current && safetyLevelRef.current !== 'off' &&
          !!matchedTags && isContentBlocked(matchedTags, allowedSexualRef.current, allowedViolenceRef.current)
        if (shouldPlay && !audioBlocked) void playAudio(url)
      }
    }
    if (event.type === 'PLAYER_LEFT') {
      // participant_id で判定（char_id="" の observer/keeper が複数いても巻き添えにしない）
      const pid = event.payload.participant_id ?? event.payload.character_id
      setParticipants(prev => prev.filter(x => x.participant_id !== pid))
    }
    if (event.type === 'PLAYER_DISCONNECTED') {
      const pid = event.payload.participant_id ?? event.payload.character_id
      const timeoutSec = event.payload.timeout_sec as number | undefined
      setParticipants(prev =>
        prev.map(x => x.participant_id === pid ? { ...x, connected: false, disconnectTimeoutSec: timeoutSec } : x)
      )
    }
    if (event.type === 'PLAYER_RECONNECTED') {
      const pid = event.payload.participant_id ?? event.payload.character_id
      setParticipants(prev =>
        prev.map(x => x.participant_id === pid ? { ...x, connected: true, disconnectTimeoutSec: undefined } : x)
      )
    }
    if (event.type === 'LOBBY_UPDATE') {
      if (event.payload?.initiative) {
        initiativeRef.current = event.payload.initiative
        setInitiative(event.payload.initiative)
      }
      if (event.payload?.name_map) {
        setExtraNameMap(prev => ({ ...prev, ...event.payload.name_map }))
      }
      if ('keeper_char_id' in (event.payload ?? {})) {
        setLobbyKeeperCharId(event.payload.keeper_char_id ?? '')
        setLobbyKeeperCharName(event.payload.keeper_char_name ?? '')
      }
    }
  }

  // ── WS 受信 AI ターンデータ処理（旧 nextTurn の本体）────────────
  const processAITurnData = async (data: any, sid: string) => {
    if (!data || data.error) {
      if (autoAdvanceRef.current) setAutoStopMsg(t('session.msg.autoStopError'))
      setAutoAdvance(false)
      autoAdvanceRef.current = false
      setLoading(false)
      return
    }

    if (data.counters) setCounters(capCounters(data.counters))
    if (data.character_id) setActiveTurnCharId(data.character_id)
    setLoading(false)

    if (data.skipped) {
      setRound(data.round)
      const ctrB: number | null = typeof data.counter_before === 'number' ? data.counter_before : null
      const isForced = ctrB !== null && ctrB < 0
      const skipText = isForced
        ? t('session.msg.forcedSkip', { name: data.character_name, prev: String(ctrB), next: String((ctrB as number) + 1) })
        : ctrB !== null
          ? t('session.msg.counterSkip', { name: data.character_name, prev: String(ctrB), next: String(ctrB + 1) })
          : t('session.msg.humanSkip', { name: data.character_name })
      setMessages(prev => [...prev, { character_id: '_keeper', character_name: '⚙ System', text: skipText, emotion: '', tags: [] }])
      return
    }

    if (data.action === 'vote_proposal') {
      if (data.counters) setCounters(capCounters(data.counters))
      setMessages(prev => [...prev, { character_id: '_keeper', character_name: '⚙ System', text: t('session.msg.voteProposalSystem', { name: data.character_name }), emotion: '', tags: [] }])
      try {
        const delibRes = await authFetch(`/api/session/${sid}/vote/deliberate`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ vote_type: data.vote_type || 'topic_change', detail: data.vote_detail || '', target_id: '', proposer_id: data.character_id, proposer_text: data.proposer_text || '' }),
        })
        const delibData = await parseJsonResponse(delibRes)
        if (delibData.error) { console.error(delibData.error); return }
        if (delibData.counters) setCounters(capCounters(delibData.counters))
        if (delibData.deliberations && Array.isArray(delibData.deliberations)) {
          for (const d of delibData.deliberations as { character_id: string; character_name: string; text: string; emotion: string; tags?: string[] }[]) {
            setMessages(prev => [...prev, { character_id: d.character_id, character_name: d.character_name, text: d.text, emotion: d.emotion, tags: d.tags || [] }])
          }
        }
        setMessages(prev => [...prev, { character_id: '_keeper', character_name: t('trpg.keeper.label'), text: t('session.msg.voteProposalDetail', { name: data.character_name, detail: data.vote_detail || data.vote_type || '' }), emotion: '', tags: [], isKeeperVote: true }])
        // 投票中の自動停止・復帰はキーパー権限タブのローカル駆動状態のみ操作する
        // （player タブの表示はセッション状態 AUTO_ADVANCE_CHANGED にのみ従う）
        if (myRoleRef.current === 'host' || myRoleRef.current === 'gm') {
          wasAutoAdvancingRef.current = autoAdvanceRef.current
          setAutoAdvance(false)
          autoAdvanceRef.current = false
        }
      } catch (e) { console.error(e) }
      return
    }

    const isLastOfRound = trpgModeRef.current && initiativeRef.current.length > 0 &&
      initiativeRef.current[initiativeRef.current.length - 1] === data.character_id

    const char = charMap[data.character_id]
    setMessages(prev => [...prev, { character_id: data.character_id, character_name: data.character_name, text: data.text, emotion: data.emotion, tags: data.tags || [], imageColor: char?.image_color ?? undefined, turnRound: data.round, turnTurn: data.turn }])
    setRound(data.round)

    if (data.penalty_message) {
      setMessages(prev => [...prev, { character_id: '_keeper', character_name: '⚙ System', text: data.penalty_message, emotion: '', tags: [] }])
    }
    if (data.ai_action === 'extend') {
      const ctr = data.counters?.[data.character_id]
      const remain = typeof ctr === 'number' ? t('session.msg.remainCounter', { ctr }) : ''
      setMessages(prev => [...prev, { character_id: '_keeper', character_name: '⚙ System', text: t('session.msg.aiExtend', { name: data.character_name, remain }), emotion: '', tags: [] }])
    }
    if (data.ai_action === 'designate' && data.designated_name) {
      const ctr = data.counters?.[data.character_id]
      const remain = typeof ctr === 'number' ? t('session.msg.remainCounter', { ctr }) : ''
      setMessages(prev => [...prev, { character_id: '_keeper', character_name: '⚙ System', text: t('session.msg.aiDesignate', { name: data.character_name, target: data.designated_name, remain }), emotion: '', tags: [] }])
    }

    // 挿絵・TTSはサーバー側でバックグラウンド生成され、TURN_IMAGE_READY / TURN_AUDIO_READY で
    // 非同期に届く（WSハンドラ側でturnRound/turnTurnが一致するメッセージを探して更新する）。

    if (isLastOfRound && keeperFiredRoundRef.current !== data.round) {
      await fireKeeperTurn(sid, data.round)
    }

    // _run_ai_turns は1ターン1実行で停止する。自動モードなら次のターンを ai_resume で継続する。
    // ai_resume は require_keeper（host/gm）のため、player タブから呼んでも403になる。
    // 人間ターン到達はサーバーが AI_TURN_COMPLETED 直後に WAITING_FOR_HUMAN を emit して通知する。
    if (autoAdvanceRef.current && (myRoleRef.current === 'host' || myRoleRef.current === 'gm')) {
      void authFetch(`/api/session/${sid}/ai_resume`, { method: 'POST' })
    }
  }

  useEffect(() => {
    fetch('/api/settings')
      .then(r => r.json())
      .then(res => {
        const s = res.settings ?? res
        if (s.allowed_rating_sexual) { setAllowedSexual(s.allowed_rating_sexual); allowedSexualRef.current = s.allowed_rating_sexual }
        if (s.allowed_rating_violence) { setAllowedViolence(s.allowed_rating_violence); allowedViolenceRef.current = s.allowed_rating_violence }
        if (s.safety_level) { const v = s.safety_level === 'warn' ? 'off' : s.safety_level; setSafetyLevel(v); safetyLevelRef.current = v }
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
      if (key === 'safety_level') { const v = value === 'warn' ? 'off' : value; setSafetyLevel(v); safetyLevelRef.current = v }
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

  const charMap = buildCharMap()

  const _initSession = async (data: any, chars: string[]) => {
    setParticipants([])
    setLobbyActive(false)
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
    const humanChar = characters.find(c => chars.includes(c.id) && c.player_type === 'human')
    myCharIdRef.current = humanChar?.id ?? ''
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
    hostTokenRef.current = data.host_token ?? ''
    myRoleRef.current = 'host'
    setMyRole('host')
    if (data.invite_code) {
      setInviteCode(data.invite_code)
      // オンライン(招待コード発行あり)セッションのみ復帰対象とする。ローカル
      // セッションはそもそも他参加者がいないため、リロード後の自動復帰は不要。
      saveSessionRestoreState({
        sessionId: data.session_id,
        token: data.host_token ?? '',
        role: 'host',
        charId: humanChar?.id ?? '',
        displayName: humanChar?.name ?? '',
      })
    }
    const firstCharId = (data.initiative || [])[0]
    if (humanChar && firstCharId === humanChar.id) {
      setWaitingForHuman(true)
      setHasDiscarded(false)
    }
  }

  // ローカルで開始: キャラ選択必須、ロビーなし
  const startLocalSession = async () => {
    if (selectedChars.length < 1) return
    setSessionStarting(true)
    try {
      const res = await fetch('/api/session/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character_ids: selectedChars, topic: trpgMode ? '' : topic, backend, rule_set: trpgMode ? 'none' : ruleSet, action_directive_set: directiveSet, actions_per_turn: actionsPerTurn, char_backends: charBackends, trpg_mode: trpgMode, trpg_rulebook: trpgMode ? selectedRulebook : '', trpg_scenario: trpgMode ? selectedScenario : '', char_game_sheets: trpgMode ? charGameSheets : {}, keeper_char_id: trpgMode ? keeperCharId : '', human_keeper: trpgMode ? humanKeeper : false }),
      })
      const data = await res.json()
      if (!res.ok) { console.error('session start failed:', data.detail || res.status); return }
      await _initSession(data, selectedChars)
      // オンライン側（ロビー終了処理）と同様、ここではai_resumeを呼ばない。
      // 開始後は「自動」トグルか「次の発言」ボタンでユーザーが能動的に始める。
    } catch (e) {
      console.error(e)
    } finally {
      setSessionStarting(false)
    }
  }

  // オンラインセッション作成: キャラ不要、ロビーで参加者を待つ
  const startOnlineSession = async () => {
    setSessionStarting(true)
    try {
      const res = await fetch('/api/session/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ character_ids: [], topic: trpgMode ? '' : topic, backend, rule_set: trpgMode ? 'none' : ruleSet, action_directive_set: directiveSet, actions_per_turn: actionsPerTurn, char_backends: charBackends, trpg_mode: trpgMode, trpg_rulebook: trpgMode ? selectedRulebook : '', trpg_scenario: trpgMode ? selectedScenario : '', char_game_sheets: {}, keeper_char_id: '', human_keeper: false, online_mode: true }),
      })
      const data = await res.json()
      if (!res.ok) { console.error('session start failed:', data.detail || res.status); return }
      await _initSession(data, [])
      setLobbyTrpgMode(trpgMode)
      setKeeperSource('ai')
      setLobbyMode(true)
    } catch (e) {
      console.error(e)
    } finally {
      setSessionStarting(false)
    }
  }

  const playAudio = (url: string): Promise<void> =>
    new Promise(resolve => {
      const audio = new Audio(url)
      audio.onended = () => resolve()
      audio.onerror = () => resolve()
      audio.play().catch(() => resolve())
    })

  const retakeTurn = async () => {
    if (!sessionId || loading) return
    setAutoAdvance(false)
    autoAdvanceRef.current = false
    const res = await authFetch(`/api/session/${sessionId}/retake`, { method: 'POST' })
    const data = await parseJsonResponse(res)
    if (data.error) { console.error(data.error); return }
    const removed = data.removed ?? 0
    if (removed > 0) setMessages(prev => prev.slice(0, -removed))
    // サーバー側でai_task再起動済み（WS経由でAIターンが来る）
  }

  const toggleAutoAdvance = () => {
    const next = !autoAdvance
    setAutoAdvance(next)
    autoAdvanceRef.current = next
    if (next) setAutoStopMsg(null)
    if (!sessionId) return
    // 自動進行はセッション状態。キーパー権限（host/gm、人間キーパー参加中はgmのみ）が
    // PATCH で切り替え、AUTO_ADVANCE_CHANGED として全タブに配信される。
    // resume/pause 相当の副作用はサーバー側で処理する
    void authFetch(`/api/session/${sessionId}/auto_advance`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled: next }),
    })
    if (next && !loading && waitingForHuman) {
      // 自分の人間ターン中にONへ切り替えた場合は自ターンをスキップして進行再開
      void submitHumanTurn('skip')
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
      const res = await authFetch(`/api/session/${sessionId}/save`, {
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
      const res = await authFetch(`/api/session/${sid}/ai_keeper`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend }),
      })
      const d = await parseJsonResponse(res)
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
        ? t('session.msg.sceneAdvanced', { label: `${keeperResult.new_chapter_title ? `${keeperResult.new_chapter_title} / ` : ''}${keeperResult.new_scene_title}` })
        : t('session.msg.sceneAdvancedNext')
      setMessages(prev => [...prev, {
        character_id: '_keeper', character_name: '📍 Scene', text: sceneLabel, emotion: '', tags: [],
      }])
      generateSceneImage()
    }
    if (keeperResult?.propose_end) {
      setMessages(prev => [...prev, {
        character_id: '_keeper', character_name: '⚙ System',
        text: t('session.msg.keeperEndProposal'),
        emotion: '', tags: [],
      }])
      try {
        const delibRes = await authFetch(`/api/session/${sid}/vote/deliberate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ vote_type: 'end_session', detail: '', target_id: '', proposer_id: '_keeper', proposer_text: '' }),
        })
        const delibData = await parseJsonResponse(delibRes)
        if (delibData.error) { console.error(delibData.error); return }
        if (delibData.deliberations && Array.isArray(delibData.deliberations)) {
          for (const d of delibData.deliberations as { character_id: string; character_name: string; text: string; emotion: string; tags?: string[] }[]) {
            setMessages(prev => [...prev, { character_id: d.character_id, character_name: d.character_name, text: d.text, emotion: d.emotion, tags: d.tags || [] }])
          }
        }
        setMessages(prev => [...prev, {
          character_id: '_keeper', character_name: t('trpg.keeper.label'),
          text: t('session.msg.keeperEndVoteText'),
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
    // WS経由でAI_TURN_COMPLETEDが届く。ai_resumeでai_taskを再起動
    void authFetch(`/api/session/${sid}/ai_resume`, { method: 'POST' })
  }

  const rollJudgmentAuto = async (sid: string, j: KeeperJudgment, isSkill = false) => {
    if (j.stat_value === 0) {
      // stat_value=0 は死亡または未習得。死亡キャラはダメージを受けないよう success:true を返す
      const dead = isCharDead(j.character_id)
      return { total: 0, judgment: { success: dead, fumble: false, critical: false, judgment_value: 0 } }
    }
    try {
      const res = await authFetch(`/api/session/${sid}/dice`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          notation: '1d100',
          skill_value: j.stat_value,
          rulebook_id: selectedRulebook,
          character_id: j.character_id,
          stat_name: j.stat,
          is_skill: isSkill,
        }),
      })
      const d = await parseJsonResponse(res)
      if (d.error) { console.error(d.error); return null }
      return d
    } catch (e) {
      console.error(e)
      return null
    }
  }

  const rollDamage = async (charId: string, charName: string) => {
    try {
      const res = await fetch('/api/trpg/damage', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, character_id: charId, rulebook_id: selectedRulebook }),
      })
      const d = await parseJsonResponse(res)
      if (d.error) { console.error(d.error); return }
      const syncStats = (updatedStats: Record<string, any>) => {
        const flat = Object.fromEntries(
          Object.entries(updatedStats).map(([k, v]: [string, any]) => [k, v.current ?? 0])
        )
        authFetch(`/api/session/${sessionId}/sync_stats`, {
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
          text: t('session.msg.instantDeathLabel', { flavor: d.flavor }),
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
          text: t('session.msg.damageLabel', { stat, delta, roll: d.roll, flavor: d.flavor }),
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
    if (wasAutoAdvancingRef.current) {
      setAutoAdvance(true)
      autoAdvanceRef.current = true
    }
    wasAutoAdvancingRef.current = false
    void authFetch(`/api/session/${sessionId}/ai_resume`, { method: 'POST' })
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
    setPendingJudgments(prev => prev.filter((_, i) => i !== idx))
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
        const res = await authFetch(`/api/session/${sessionId}/dice`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
        const data = await parseJsonResponse(res)
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

  const loadSavedSession = async (filename: string) => {
    setLoading(true)
    try {
      const res = await fetch('/api/session/load', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
      })
      const data = await res.json()
      if (!res.ok || data.error) { console.error(data.detail || data.error || res.status); return }

      const nameMap: Record<string, string> = data.name_map || {}
      const history: any[] = data.history || []
      const reconstructed: SessionMessage[] = reconstructMessages(history, nameMap, charMap)

      sessionIdRef.current = data.session_id
      setSessionId(data.session_id)
      // ロード復元セッションにもホストトークンが発行されるようになった
      // （GET /{session_id} の認証必須化に伴うバックエンド変更）。
      hostTokenRef.current = data.host_token ?? ''
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

  // explicitLeave: ユーザーが「退出」ボタンを押した場合のみ true。
  // SESSION_ENDED 受信時（ホストがセッションを終えた場合）はこの関数が引数なしで
  // 呼ばれるため false のまま → /leave を叩かない（セッション自体が消滅済みのため無意味）
  const endSession = async (explicitLeave = false) => {
    // 再入ガード: ホスト自身の /end が発火させる SESSION_ENDED ブロードキャストを
    // 自タブが受信して endSession() を再実行するループを防ぐ
    if (endingRef.current) return
    endingRef.current = true
    clearSessionRestoreState()
    if (sessionId && messages.length > 0) {
      await saveCurrentSession()
    }
    // ホストはバックエンドにセッション終了を通知（参加者全員に SESSION_ENDED が届く）
    if (myRole === 'host' && sessionId) {
      try {
        await fetch(`/api/session/${sessionId}/end`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${hostTokenRef.current}` },
        })
      } catch {}
    } else if (explicitLeave && myRole !== 'host' && sessionId) {
      // 非ホストの明示的退室: サーバーの参加者データを除去し PLAYER_LEFT を他タブへ配信
      try {
        await fetch(`/api/session/${sessionId}/leave`, {
          method: 'POST',
          headers: { 'Authorization': `Bearer ${hostTokenRef.current}` },
        })
      } catch {}
    }
    // WS切断
    if (wsReconnectTimerRef.current !== null) {
      clearTimeout(wsReconnectTimerRef.current)
      wsReconnectTimerRef.current = null
    }
    wsRef.current?.close()
    wsRef.current = null
    sessionIdRef.current = ''
    setSessionId('')
    setInviteCode('')
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
    myCharIdRef.current = ''
    setHumanCharId('')
    setHumanCharName('')
    setLobbyMode(false)
    setParticipants([])
    setLobbyActive(false)
    setLobbyKeeperCharId('')
    setLobbyKeeperCharName('')
    myRoleRef.current = 'host'
    setMyRole('host')
    setShowJoinDialog(false)
    fetchSavedSessions()
    endingRef.current = false
  }

  const beginSession = async () => {
    if (!sessionId) return
    // ロビー設定をバックエンドに送信（最大プレイヤー数・ホストキャラ）
    const configRes = await fetch(`/api/session/${sessionId}/lobby_config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${hostTokenRef.current}` },
      body: JSON.stringify({
        max_players: lobbyMaxPlayers,
        host_char_id: hostRole === 'player' ? hostCharForLobby : '',
      }),
    })
    if (configRes.ok) {
      const cfg = await configRes.json()
      initiativeRef.current = cfg.initiative || []
      setInitiative(cfg.initiative || [])
    }
    // ホストがプレイヤー参加の場合、humanCharIdをセットしてプレイヤーコントロールを表示
    if (hostRole === 'player' && hostCharForLobby) {
      const hc = characters.find(c => c.id === hostCharForLobby)
      myCharIdRef.current = hostCharForLobby
      setHumanCharId(hostCharForLobby)
      setHumanCharName(hc?.name ?? hostCharForLobby)
      isHumanKeeperRef.current = false
    }
    // 観戦者モードでも myRole は 'host' のまま維持する。JWTロールが host であり
    // 進行制御（自動切替・次の発言）の権限を持つため、observer に切り替えると
    // AIキーパー構成で誰も自動進行を操作できなくなる。
    // キャラを持たない（humanCharId 空）ことで参加系コントロールは自然に非表示になる
    setLobbyMode(false)
    // ai_resume はここでは呼ばない。オフライン同様、キーパーが自動/次の発言で開始する。
  }

  const aiTakeover = async (charId: string) => {
    if (!sessionId) return
    const res = await authFetch(`/api/session/${sessionId}/ai_takeover`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character_id: charId }),
    })
    if (res.ok) {
      setAiTakenOverChars(prev => new Set([...prev, charId]))
    }
  }

  const lobbyAddAi = async (charId: string, gameSheetId = '', backendId = '') => {
    if (!sessionId) return
    const res = await authFetch(`/api/session/${sessionId}/lobby/add_ai`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character_id: charId, game_sheet_id: gameSheetId, backend_id: backendId }),
    })
    if (res.ok) {
      const d = await res.json()
      initiativeRef.current = d.initiative
      setInitiative(d.initiative)
      setExtraNameMap(prev => ({ ...prev, ...d.name_map }))
      if (gameSheetId) setCharGameSheets(prev => ({ ...prev, [charId]: gameSheetId }))
      if (backendId) setCharBackends(prev => ({ ...prev, [charId]: backendId }))
    }
    setAssignDialogTarget(null)
  }

  const lobbyRemoveAi = async (charId: string) => {
    if (!sessionId) return
    const res = await authFetch(`/api/session/${sessionId}/lobby/remove_ai`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character_id: charId }),
    })
    if (res.ok) {
      const d = await res.json()
      initiativeRef.current = d.initiative
      setInitiative(d.initiative)
    }
  }

  // charId="" で解除（無名AIキーパーに戻る。割り付けなくてもAI自動進行自体は維持される）
  const lobbySetKeeperChar = async (charId: string, backendId = '') => {
    if (!sessionId) return
    const res = await authFetch(`/api/session/${sessionId}/lobby/set_keeper_char`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ character_id: charId, backend_id: backendId }),
    })
    if (res.ok) {
      const d = await res.json()
      setLobbyKeeperCharId(d.keeper_char_id ?? '')
      setLobbyKeeperCharName(d.keeper_char_name ?? '')
      if (charId && backendId) setCharBackends(prev => ({ ...prev, [charId]: backendId }))
    }
    setAssignDialogTarget(null)
  }

  const confirmAssignDialog = () => {
    if (assignDialogTarget === 'slot') {
      void lobbyAddAi(assignCharId, assignSheetId, assignBackendId)
    } else if (assignDialogTarget === 'keeper') {
      void lobbySetKeeperChar(assignCharId, assignBackendId)
    }
  }

  const commitKeeperActions = async () => {
    if (!sessionId || pendingActions.length === 0) return
    const text = pendingActions.length === 1
      ? pendingActions[0]
      : pendingActions.map((a, i) => `${i + 1}. ${a}`).join('\n')
    const res = await fetch(`/api/session/${sessionId}/keeper`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${hostTokenRef.current}` },
      body: JSON.stringify({ text }),
    })
    if (!res.ok) { console.error('keeper action failed:', res.status); return }
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
      void authFetch(`/api/session/${sessionId}/ai_resume`, { method: 'POST' })
    } else if (autoAdvanceRef.current) {
      setAutoAdvance(false)
      autoAdvanceRef.current = false
    }
  }

  const skipCurrentTurn = async () => {
    if (!sessionId) return
    const res = await authFetch(`/api/session/${sessionId}/skip`, { method: 'POST' })
    const data = await parseJsonResponse(res)
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
    const res = await fetch(`/api/session/${sessionId}/designate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${hostTokenRef.current}` },
      body: JSON.stringify({ target_id: designateTarget }),
    })
    if (!res.ok) { console.error('designate failed:', res.status); return }
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
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${hostTokenRef.current}` },
      body: JSON.stringify({ action: 'generate_image', text: '', character_id: humanCharId }),
    })
    const data = await parseJsonResponse(res)
    if (data.error) return
    if (data.counters) setCounters(capCounters(data.counters))
    generateSceneImage()
  }

  const submitHumanTurn = async (action: 'send' | 'extend' | 'skip' | 'interrupt') => {
    if (!sessionId) return
    const lines = [...humanPending, ...(humanInput.trim() ? [humanInput.trim()] : [])]
    const text = lines.join('\n')
    // send/skip は fetch 前に waitingForHuman を false にしておく（競合防止）
    // オンライン時: WAITING_FOR_HUMAN が即座に届くとHTTPレスポンスで上書きされるため
    if (action === 'send' || action === 'skip') setWaitingForHuman(false)
    const res = await fetch(`/api/session/${sessionId}/human_turn`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${hostTokenRef.current}` },
      // expected_round: 直近のWAITING_FOR_HUMANで受け取ったroundをそのまま送り返す
      // (send/skipの多重送信対策。session.pyのhuman_turn_action参照)。
      body: JSON.stringify({ action, text, character_id: humanCharId, expected_round: round }),
    })
    const data = await parseJsonResponse(res)
    if (data.error) {
      if (action === 'send' || action === 'skip') setWaitingForHuman(true)  // 失敗時は戻す
      return
    }

    if (action === 'skip') {
      setMessages(prev => [...prev, {
        character_id: '_keeper',
        character_name: '⚙ System',
        text: t('session.msg.humanSkip', { name: humanCharName }),
        emotion: '', tags: [],
      }])
    }
    if (action !== 'skip' && text) {
      // TTSはバックグラウンド生成のためこの時点ではURL未確定。audio_request_idを
      // 記録しておき、生成完了後に届くAUDIO_READYイベントで該当メッセージへ反映する。
      setMessages(prev => {
        const idx = prev.length
        if (data.audio_request_id) audioRequestIndexRef.current[data.audio_request_id] = idx
        return [...prev, {
          character_id: humanCharId,
          character_name: humanCharName,
          text,
          emotion: 'neutral',
          tags: [],
          imageColor: charMap[humanCharId]?.image_color,
        }]
      })
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
    }
    // TRPGラウンド末尾でない場合はサーバーが自律でai_taskを再起動（WS経由でAI_TURN_COMPLETEDが届く）
  }

  const startDeliberation = async () => {
    if (!sessionId) return
    setVoteLoading(true)
    setShowVoteDialog(false)
    try {
      const res = await authFetch(`/api/session/${sessionId}/vote/deliberate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vote_type: voteType, detail: voteDetail, target_id: voteTarget, proposer_id: humanCharId, proposer_text: voteProposerText }),
      })
      const data = await parseJsonResponse(res)
      if (data.error) return
      if (data.counters) setCounters(capCounters(data.counters))
      if (data.deliberations && Array.isArray(data.deliberations)) {
        for (const d of data.deliberations as { character_id: string; character_name: string; text: string; emotion: string; tags?: string[]; audio_request_id?: string }[]) {
          // TTSはバックグラウンド生成のためこの時点ではURL未確定。audio_request_idを
          // 記録しておき、生成完了後に届くAUDIO_READYイベントで該当メッセージへ反映する
          // （人間プレイヤー発言はttsHumanEnabled、それ以外はttsEnabledに従う判定もそちらで行う）。
          setMessages(prev => {
            const idx = prev.length
            if (d.audio_request_id) audioRequestIndexRef.current[d.audio_request_id] = idx
            return [...prev, {
              character_id: d.character_id,
              character_name: d.character_name,
              text: d.text,
              emotion: d.emotion || '',
              tags: d.tags || [],
              imageColor: charMap[d.character_id]?.image_color,
            }]
          })
        }
      }
      setMessages(prev => [...prev, {
        character_id: '_keeper',
        character_name: t('trpg.keeper.label'),
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
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${hostTokenRef.current}` },
        body: JSON.stringify({ keeper_vote: keeperVote }),
      })
      const data = await parseJsonResponse(res)
      if (data.error) return
      setMessages(prev => [
        ...prev.filter(m => !m.isKeeperVote),
        {
          character_id: '_keeper',
          character_name: t('trpg.keeper.label'),
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
      const res = await authFetch(`/api/session/${sessionId}/scene/advance`, { method: 'POST' })
      const data = await parseJsonResponse(res)
      if (data.error) { console.error('scene/advance:', data.error); return }
      if (typeof data.current_scene_index === 'number') setCurrentSceneIndex(data.current_scene_index)
      const sceneLabel = data.scene_title
        ? t('session.msg.sceneAdvanced', { label: `${data.chapter_title ? `${data.chapter_title} / ` : ''}${data.scene_title}` })
        : t('session.msg.sceneAdvancedNext')
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
      const res = await authFetch(`/api/session/${sessionId}/generate-image`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend, t2i_backend: t2iBackend }),
      })
      const data = await parseJsonResponse(res)
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

  // ── ロビー画面（参加者待機）──────────────────────────────
  if (sessionId && lobbyMode) {
    // ローカルキャラ + 参加者のゲストキャラの名前マップを合成
    const nameMap: Record<string, string> = {
      ...extraNameMap,
      ...Object.fromEntries(characters.map(c => [c.id, c.name])),
      ...Object.fromEntries(participants.filter(p => p.char_id).map(p => [p.char_id, p.display_name])),
    }
    const observerCount = participants.filter(p => p.role === 'observer').length

    return (
      <div className="tab-content session-tab">
        <div className="session-setup-scroll">
          <div className="session-setup" style={{ maxWidth: 540 }}>

            {/* ヘッダー */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: '#4a6cf7', boxShadow: '0 0 6px #4a6cf7', display: 'inline-block', animation: 'pulse 1.5s ease-in-out infinite' }} />
              <h2 style={{ margin: 0 }}>{t('session.lobby.title')}</h2>
            </div>
            <p style={{ margin: '0 0 20px', opacity: 0.55, fontSize: '0.88em' }}>{t('session.lobby.desc')}</p>

            {/* ロビー設定（ホスト専用・招待コード発行前に決める） */}
            {myRole === 'host' && (
              <div style={{ marginBottom: 20, padding: '14px 16px', borderRadius: 10, border: '1px solid var(--border-color, #ddd)', background: 'var(--input-bg, rgba(128,128,128,0.06))', display: 'flex', flexDirection: 'column', gap: 14 }}>

                {/* セッションモード */}
                <div>
                  <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 8 }}>{t('session.lobby.modeLabel')}</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {([false, true] as const).map(isTrpg => (
                      <button
                        key={String(isTrpg)}
                        onClick={() => {
                          setLobbyTrpgMode(isTrpg)
                          // キーパー専任 → 通常モードでも同じ役割なのでラベルのみ変更
                          void fetch(`/api/session/${sessionId}/lobby/mode`, {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${hostTokenRef.current}` },
                            body: JSON.stringify({ trpg_mode: isTrpg }),
                          })
                          // /start と同じ条件付けで設定を同期する（TRPG: ルールブック/シナリオ、通常: ルール/お題）
                          if (isTrpg) {
                            patchLobbySettings({ rule_set: 'none', topic: '', trpg_rulebook: selectedRulebook, trpg_scenario: selectedScenario })
                          } else {
                            patchLobbySettings({ rule_set: ruleSet, topic, trpg_rulebook: '', trpg_scenario: '' })
                          }
                        }}
                        style={{ padding: '6px 18px', borderRadius: 8, border: `1px solid ${lobbyTrpgMode === isTrpg ? '#4a6cf7' : 'var(--border-color, #ccc)'}`, background: lobbyTrpgMode === isTrpg ? '#4a6cf7' : 'transparent', color: lobbyTrpgMode === isTrpg ? '#fff' : 'inherit', cursor: 'pointer', fontSize: '0.88em', fontWeight: lobbyTrpgMode === isTrpg ? 600 : 400 }}
                      >
                        {isTrpg ? t('session.lobby.modeTrpg') : t('session.lobby.modeNormal')}
                      </button>
                    ))}
                  </div>
                </div>

                {/* セッション設定（オフライン開始時と同じ項目をロビーでも変更可能にする） */}
                {!lobbyTrpgMode ? (
                  <>
                    {ruleOptions.length > 0 && (
                      <div>
                        <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 8 }}>{t('session.setup.ruleLabel')}</div>
                        <select
                          value={ruleSet}
                          onChange={e => { setRuleSet(e.target.value); patchLobbySettings({ rule_set: e.target.value }) }}
                          style={{ width: '100%', padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'var(--input-bg, #f5f5f5)', color: 'inherit', fontSize: '0.9em' }}
                        >
                          {ruleOptions.map(r => (
                            <option key={r.id} value={r.id}>{r.label}</option>
                          ))}
                        </select>
                      </div>
                    )}
                    <div>
                      <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 8 }}>{t('session.setup.topicLabel')}</div>
                      <input
                        value={topic}
                        onChange={e => setTopic(e.target.value)}
                        onBlur={() => patchLobbySettings({ topic })}
                        onKeyDown={e => { if (e.key === 'Enter') patchLobbySettings({ topic }) }}
                        placeholder={t('session.setup.topicPlaceholder')}
                        style={{ width: '100%', boxSizing: 'border-box', padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'var(--input-bg, #f5f5f5)', color: 'inherit', fontSize: '0.9em' }}
                      />
                    </div>
                  </>
                ) : (
                  <>
                    {rulebookOptions.length > 0 && (
                      <div>
                        <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 8 }}>{t('trpg.rulebook.label')}</div>
                        <select
                          value={selectedRulebook}
                          onChange={e => { setSelectedRulebook(e.target.value); patchLobbySettings({ trpg_rulebook: e.target.value }) }}
                          style={{ width: '100%', padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'var(--input-bg, #f5f5f5)', color: 'inherit', fontSize: '0.9em' }}
                        >
                          {rulebookOptions.map(r => (
                            <option key={r.id} value={r.id}>{r.label}（{r.dice_system}）</option>
                          ))}
                        </select>
                      </div>
                    )}
                    {scenarioOptions.length > 0 && (
                      <div>
                        <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 8 }}>{t('trpg.scenario.label')}</div>
                        <select
                          value={selectedScenario}
                          onChange={e => { setSelectedScenario(e.target.value); patchLobbySettings({ trpg_scenario: e.target.value }) }}
                          style={{ width: '100%', padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'var(--input-bg, #f5f5f5)', color: 'inherit', fontSize: '0.9em' }}
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
                  </>
                )}

                {/* プレイヤー人数 */}
                <div>
                  <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 8 }}>{t('session.lobby.maxPlayersLabel')}</div>
                  <div style={{ display: 'flex', gap: 4 }}>
                    {[1, 2, 3, 4, 5, 6, 7, 8].map(n => (
                      <button
                        key={n}
                        onClick={() => { setLobbyMaxPlayers(n); patchLobbySettings({ max_players: n }) }}
                        style={{ width: 34, height: 34, borderRadius: 6, border: `1px solid ${lobbyMaxPlayers === n ? '#4a6cf7' : 'var(--border-color, #ccc)'}`, background: lobbyMaxPlayers === n ? '#4a6cf7' : 'transparent', color: lobbyMaxPlayers === n ? '#fff' : 'inherit', cursor: 'pointer', fontWeight: lobbyMaxPlayers === n ? 700 : 400, fontSize: '0.9em' }}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>

                {/* ホストの役割 */}
                <div>
                  <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 8 }}>{t('session.lobby.hostRoleLabel')}</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    {(['keeper', 'player', 'observer'] as const).map(role => (
                      <button
                        key={role}
                        onClick={() => {
                          setHostRole(role)
                          void fetch(`/api/session/${sessionId}/host_role?is_keeper=${role === 'keeper'}`, {
                            method: 'PATCH',
                            headers: { 'Authorization': `Bearer ${hostTokenRef.current}` },
                          })
                        }}
                        style={{ padding: '6px 16px', borderRadius: 8, border: `1px solid ${hostRole === role ? '#4a6cf7' : 'var(--border-color, #ccc)'}`, background: hostRole === role ? '#4a6cf7' : 'transparent', color: hostRole === role ? '#fff' : 'inherit', cursor: 'pointer', fontSize: '0.88em', fontWeight: hostRole === role ? 600 : 400 }}
                      >
                        {role === 'keeper' ? (lobbyTrpgMode ? t('session.lobby.hostRoleKeeperExclusive') : t('session.lobby.progressManagerLabel')) : role === 'player' ? t('session.lobby.hostRolePlayer') : t('session.observer.label')}
                      </button>
                    ))}
                  </div>
                  {hostRole === 'player' && (
                    <div style={{ marginTop: 10 }}>
                      <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 6 }}>{t('session.lobby.charSelectHostLabel')}</div>
                      <select
                        value={hostCharForLobby}
                        onChange={e => setHostCharForLobby(e.target.value)}
                        style={{ width: '100%', padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'var(--input-bg, #f5f5f5)', color: 'inherit', fontSize: '0.9em' }}
                      >
                        <option value="">{t('session.setup.charSelect.placeholder')}</option>
                        {characters.filter(c => c.player_type === 'human' || !c.player_type).map(c => (
                          <option key={c.id} value={c.id}>{c.name}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>

                {/* キーパー/進行管理担当（ホストがキーパーでない場合のみ） */}
                {hostRole !== 'keeper' && (
                  <div>
                    <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 8 }}>
                      {lobbyTrpgMode ? t('session.lobby.keeperInChargeLabel') : t('session.lobby.progressManagerInChargeLabel')}
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                      {(['ai', 'participant'] as const).map(src => (
                        <button
                          key={src}
                          onClick={() => {
                            setKeeperSource(src)
                            void fetch(`/api/session/${sessionId}/lobby/keeper_source`, {
                              method: 'PATCH',
                              headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${hostTokenRef.current}` },
                              body: JSON.stringify({ waiting_for_gm: src === 'participant' }),
                            })
                          }}
                          style={{ padding: '6px 16px', borderRadius: 8, border: `1px solid ${keeperSource === src ? '#4a6cf7' : 'var(--border-color, #ccc)'}`, background: keeperSource === src ? '#4a6cf7' : 'transparent', color: keeperSource === src ? '#fff' : 'inherit', cursor: 'pointer', fontSize: '0.88em', fontWeight: keeperSource === src ? 600 : 400 }}
                        >
                          {src === 'ai' ? t('session.lobby.aiAutoAdvanceOption') : t('session.lobby.waitForParticipantOption')}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* 招待コード表示 */}
                <div>
                  <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 8 }}>{t('session.lobby.shareInviteCodeLabel')}</div>
                  <InvitePanel defaultCode={inviteCode} sessionId={sessionId} hostToken={hostTokenRef.current} onCodeChanged={setInviteCode} />
                </div>

              </div>
            )}

            {/* 参加スロット（オンラインロビー） */}
            {(() => {
              const aiSlots = initiative.filter(cid =>
                !participants.some(p => p.char_id === cid) && !cid.startsWith('guest_')
              )
              const gmParticipant = participants.find(p => p.role === 'gm')
              const playerSlots = participants.filter(p => p.role === 'player')
              const hostChar = hostRole === 'player' && hostCharForLobby
                ? characters.find(c => c.id === hostCharForLobby) ?? null
                : null
              const hostSlotCount = hostChar ? 1 : 0
              const emptyCount = Math.max(0, lobbyMaxPlayers - aiSlots.length - playerSlots.length - hostSlotCount)
              const assignableChars = characters.filter(c =>
                c.player_type !== 'human' && !initiative.includes(c.id) && c.id !== lobbyKeeperCharId
              )
              const keeperLabel = lobbyTrpgMode ? t('trpg.keeper.label') : t('session.lobby.progressManagerLabel')
              return (
                <div style={{ marginBottom: 20 }}>

                  {/* キーパー枠（スロット外） */}
                  <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 6 }}>{keeperLabel}</div>
                  <div style={{ marginBottom: 12 }}>
                    {hostRole === 'keeper' ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 8, background: 'var(--input-bg, rgba(128,128,128,0.08))' }}>
                        <div style={{ width: 30, height: 30, borderRadius: '50%', background: 'var(--accent-color, #4a6cf7)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.9em', flexShrink: 0 }}>🎩</div>
                        <span style={{ flex: 1, fontSize: '0.95em', fontWeight: 600 }}>{keeperLabel}</span>
                        <span style={{ fontSize: '0.82em', color: 'var(--accent-color, #4a6cf7)' }}>{t('session.lobby.hostBadge')}</span>
                      </div>
                    ) : gmParticipant ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 8, background: 'var(--input-bg, rgba(128,128,128,0.08))' }}>
                        <div style={{ width: 30, height: 30, borderRadius: '50%', background: 'var(--border-color, rgba(128,128,128,0.2))', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.9em', flexShrink: 0 }}>🧙</div>
                        <span style={{ flex: 1, fontSize: '0.95em', fontWeight: 600 }}>{gmParticipant.display_name}</span>
                        <span style={{ fontSize: '0.82em', color: 'var(--accent-color, #4a6cf7)' }}>{t('session.lobby.participantBadge')}</span>
                      </div>
                    ) : keeperSource === 'participant' ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 8, border: '1px dashed var(--border-color, rgba(128,128,128,0.4))' }}>
                        <div style={{ width: 30, height: 30, borderRadius: '50%', background: 'var(--border-color, rgba(128,128,128,0.15))', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.9em', flexShrink: 0 }}>🧙</div>
                        <span style={{ flex: 1, fontSize: '0.88em', opacity: 0.5 }}>{t('session.lobby.waitingForParticipant')}</span>
                      </div>
                    ) : lobbyKeeperCharId ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 8, background: 'var(--input-bg, rgba(128,128,128,0.08))' }}>
                        <img src={iconUrl(lobbyKeeperCharId)} alt="" style={{ width: 30, height: 30, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
                        <span style={{ flex: 1, fontSize: '0.95em', fontWeight: 600 }}>{lobbyKeeperCharName || lobbyKeeperCharId}</span>
                        {charBackends[lobbyKeeperCharId] && (
                          <span style={{ fontSize: '0.72em', opacity: 0.6 }}>
                            [{llmBackendOptions.find(b => b.id === charBackends[lobbyKeeperCharId])?.label ?? charBackends[lobbyKeeperCharId]}]
                          </span>
                        )}
                        <span style={{ fontSize: '0.75em', opacity: 0.45, padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border-color, #ccc)' }}>AI</span>
                        <button
                          onClick={() => void lobbySetKeeperChar('')}
                          style={{ fontSize: '0.75em', padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border-color, #888)', background: 'transparent', color: 'var(--danger-color, #d32)', cursor: 'pointer' }}
                        >{t('session.lobby.releaseBtn')}</button>
                      </div>
                    ) : (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 8, background: 'var(--input-bg, rgba(128,128,128,0.05))', border: '1px solid var(--border-color, rgba(128,128,128,0.2))' }}>
                        <div style={{ width: 30, height: 30, borderRadius: '50%', background: 'rgba(100,180,100,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.9em', flexShrink: 0 }}>🤖</div>
                        <span style={{ flex: 1, fontSize: '0.88em', opacity: 0.7 }}>{t('session.lobby.aiAutoLabel')}</span>
                        {lobbyTrpgMode && assignableChars.length > 0 && (
                          <button
                            onClick={() => openAssignDialog('keeper')}
                            style={{ fontSize: '0.75em', padding: '2px 10px', borderRadius: 4, border: '1px solid var(--accent-color, #4a6cf7)', color: 'var(--accent-color, #4a6cf7)', background: 'transparent', cursor: 'pointer' }}
                          >{t('session.lobby.aiAssignBtn')}</button>
                        )}
                      </div>
                    )}
                  </div>

                  {/* 参加スロット */}
                  <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 8 }}>
                    {t('session.lobby.slotCountLabel', { current: aiSlots.length + playerSlots.length + hostSlotCount, max: lobbyMaxPlayers })}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {/* AI割付け済みスロット */}
                    {aiSlots.map(cid => (
                      <div key={cid} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 8, background: 'var(--input-bg, rgba(128,128,128,0.08))' }}>
                        <img src={iconUrl(cid)} alt="" style={{ width: 30, height: 30, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
                        <span style={{ flex: 1, fontSize: '0.95em' }}>{nameMap[cid] ?? cid}</span>
                        {charGameSheets[cid] && (
                          <span style={{ fontSize: '0.72em', opacity: 0.6, color: 'var(--accent-color, #4a6cf7)' }}>
                            [{charGameSheets[cid]}]
                          </span>
                        )}
                        {charBackends[cid] && (
                          <span style={{ fontSize: '0.72em', opacity: 0.6 }}>
                            [{llmBackendOptions.find(b => b.id === charBackends[cid])?.label ?? charBackends[cid]}]
                          </span>
                        )}
                        <span style={{ fontSize: '0.75em', opacity: 0.45, padding: '2px 6px', borderRadius: 4, border: '1px solid var(--border-color, #ccc)' }}>AI</span>
                        <button
                          onClick={() => void lobbyRemoveAi(cid)}
                          style={{ fontSize: '0.75em', padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border-color, #888)', background: 'transparent', color: 'var(--danger-color, #d32)', cursor: 'pointer' }}
                        >{t('session.lobby.releaseBtn')}</button>
                      </div>
                    ))}
                    {/* ホストスロット（プレイヤー参加時） */}
                    {hostRole === 'observer' ? (
                      <div key="host-observer" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', borderRadius: 8, border: '1px dashed var(--border-color, rgba(128,128,128,0.3))', opacity: 0.7 }}>
                        <div style={{ width: 30, height: 30, borderRadius: '50%', background: 'var(--border-color, rgba(128,128,128,0.15))', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.9em', flexShrink: 0 }}>👁</div>
                        <span style={{ flex: 1, fontSize: '0.88em' }}>{t('session.observer.label')}</span>
                        <span style={{ fontSize: '0.75em', opacity: 0.6 }}>{t('session.lobby.hostOutOfSlot')}</span>
                      </div>
                    ) : hostChar ? (
                      <div key="host-char" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 8, background: 'var(--input-bg, rgba(128,128,128,0.08))' }}>
                        <img src={iconUrl(hostChar.id)} alt="" style={{ width: 30, height: 30, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
                        <span style={{ flex: 1, fontSize: '0.95em', fontWeight: 600 }}>{hostChar.name}</span>
                        <span style={{ fontSize: '0.82em', color: 'var(--accent-color, #4a6cf7)' }}>{t('session.lobby.hostBadgeWithIcon')}</span>
                      </div>
                    ) : null}
                    {/* 参加済みプレイヤースロット */}
                    {playerSlots.map(p => (
                      <div key={p.participant_id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 8, background: 'var(--input-bg, rgba(128,128,128,0.08))' }}>
                        <img src={iconUrl(p.char_id)} alt="" style={{ width: 30, height: 30, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
                        <span style={{ flex: 1, fontSize: '0.95em', fontWeight: 600 }}>{p.display_name}</span>
                        <span style={{ fontSize: '0.82em', color: 'var(--accent-color, #4a6cf7)' }}>{t('session.lobby.joinedBadge')}</span>
                      </div>
                    ))}
                    {/* 空きスロット */}
                    {Array.from({ length: emptyCount }).map((_, i) => (
                      <div key={`empty-${i}`} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 8, border: '1px dashed var(--border-color, rgba(128,128,128,0.3))' }}>
                        <div style={{ width: 30, height: 30, borderRadius: '50%', background: 'var(--border-color, rgba(128,128,128,0.15))', flexShrink: 0 }} />
                        <span style={{ flex: 1, fontSize: '0.88em', opacity: 0.45 }}>{t('session.lobby.waitingSlot')}</span>
                        {assignableChars.length > 0 && (
                          <button
                            onClick={() => openAssignDialog('slot')}
                            style={{ fontSize: '0.75em', padding: '2px 10px', borderRadius: 4, border: '1px solid var(--accent-color, #4a6cf7)', color: 'var(--accent-color, #4a6cf7)', background: 'transparent', cursor: 'pointer' }}
                          >{t('session.lobby.aiAssignBtn')}</button>
                        )}
                      </div>
                    ))}
                  </div>

                  {/* AI割付けウィザード（スロット/キーパー共通） */}
                  {assignDialogTarget && (
                    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
                      onClick={() => setAssignDialogTarget(null)}>
                      <div style={{ background: 'var(--bg-color, #fff)', border: '1px solid var(--border-color, #ddd)', borderRadius: 12, padding: '24px 28px', minWidth: 300, maxWidth: 420, maxHeight: '70vh', overflow: 'auto', boxShadow: '0 8px 32px rgba(0,0,0,0.15)' }}
                        onClick={e => e.stopPropagation()}>
                        <div style={{ fontWeight: 700, marginBottom: 4, fontSize: '1em' }}>
                          {assignDialogTarget === 'keeper' ? t('session.lobby.assignDialogTitleKeeper', { label: keeperLabel }) : t('session.lobby.assignDialogTitleSlot')}
                        </div>
                        <div style={{ fontSize: '0.75em', opacity: 0.5, marginBottom: 14 }}>
                          {(() => {
                            const total = lobbyTrpgMode && assignDialogTarget === 'slot' ? 3 : 2
                            if (assignStep === 'char') return t('session.lobby.assignStepChar', { total })
                            if (assignStep === 'sheet') return t('session.lobby.assignStepSheet', { total })
                            return t('session.lobby.assignStepBackend', { total })
                          })()}
                        </div>

                        {assignStep === 'char' && (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            {assignableChars.map(c => (
                              <button key={c.id} onClick={() => void selectAssignChar(c.id)}
                                style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border-color, #ccc)', background: 'transparent', color: 'inherit', cursor: 'pointer', textAlign: 'left' }}>
                                <img src={iconUrl(c.id)} alt="" style={{ width: 32, height: 32, borderRadius: '50%', objectFit: 'cover' }} onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
                                <span style={{ fontSize: '0.95em' }}>{c.name}</span>
                              </button>
                            ))}
                            {assignableChars.length === 0 && (
                              <div style={{ opacity: 0.5, fontSize: '0.88em', textAlign: 'center', padding: 12 }}>{t('session.lobby.noAssignableChars')}</div>
                            )}
                          </div>
                        )}

                        {assignStep === 'sheet' && (
                          <div>
                            <div style={{ fontSize: '0.85em', opacity: 0.65, marginBottom: 8 }}>
                              {characters.find(c => c.id === assignCharId)?.name ?? assignCharId}
                            </div>
                            <select
                              className="session-select"
                              style={{ width: '100%' }}
                              value={assignSheetId}
                              onChange={e => setAssignSheetId(e.target.value)}
                            >
                              <option value="">{t('session.lobby.noSheetOption')}</option>
                              {assignSheetOptions.map(sid => (
                                <option key={sid} value={sid}>{sid}</option>
                              ))}
                            </select>
                            <div style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between' }}>
                              <button onClick={() => setAssignStep('char')}
                                style={{ padding: '6px 18px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'transparent', color: 'inherit', cursor: 'pointer' }}>{t('session.lobby.backBtn')}</button>
                              <button onClick={() => setAssignStep('backend')}
                                style={{ padding: '6px 18px', borderRadius: 6, border: '1px solid var(--accent-color, #4a6cf7)', background: 'var(--accent-color, #4a6cf7)', color: '#fff', cursor: 'pointer' }}>{t('session.lobby.nextBtn')}</button>
                            </div>
                          </div>
                        )}

                        {assignStep === 'backend' && (
                          <div>
                            <div style={{ fontSize: '0.85em', opacity: 0.65, marginBottom: 8 }}>
                              {characters.find(c => c.id === assignCharId)?.name ?? assignCharId}
                            </div>
                            <select
                              className="session-select"
                              style={{ width: '100%' }}
                              value={assignBackendId}
                              onChange={e => setAssignBackendId(e.target.value)}
                            >
                              <option value="">{t('session.lobby.backendDefaultOption')}</option>
                              {llmBackendOptions.map(b => (
                                <option key={b.id} value={b.id}>{b.label}</option>
                              ))}
                            </select>
                            <div style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between' }}>
                              <button onClick={() => setAssignStep(lobbyTrpgMode && assignDialogTarget === 'slot' ? 'sheet' : 'char')}
                                style={{ padding: '6px 18px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'transparent', color: 'inherit', cursor: 'pointer' }}>{t('session.lobby.backBtn')}</button>
                              <button onClick={confirmAssignDialog}
                                style={{ padding: '6px 18px', borderRadius: 6, border: '1px solid var(--accent-color, #4a6cf7)', background: 'var(--accent-color, #4a6cf7)', color: '#fff', cursor: 'pointer' }}>{t('session.lobby.assignBtn')}</button>
                            </div>
                          </div>
                        )}

                        <div style={{ marginTop: 16, textAlign: 'right' }}>
                          <button onClick={() => setAssignDialogTarget(null)}
                            style={{ padding: '6px 18px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'transparent', color: 'inherit', cursor: 'pointer' }}>{t('common.cancel')}</button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )
            })()}

            {/* 観戦者カウント（スロット表示に含まれないため別出し） */}
            {observerCount > 0 && (
              <div style={{ fontSize: '0.78em', opacity: 0.55, marginBottom: 8 }}>
                {t('session.lobby.observerCountLabel', { n: observerCount })}
              </div>
            )}

            <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
              <button
                onClick={() => void endSession()}
                style={{ padding: '8px 20px', borderRadius: 8, border: '1px solid var(--border-color, #aaa)', background: 'transparent', color: 'inherit', cursor: 'pointer' }}
              >
                {t('common.cancel')}
              </button>
              <button className="session-start-btn" onClick={beginSession} style={{ minWidth: 140 }}>
                {t('session.lobby.beginBtn')}
              </button>
            </div>
          </div>
        </div>
      </div>
    )
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

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 4 }}>
            <button
              className="start-btn"
              onClick={startLocalSession}
              disabled={selectedChars.length < 1 || sessionStarting}
            >
              {t('session.setup.startLocalBtn')}
            </button>
            <button
              className="start-btn"
              onClick={startOnlineSession}
              disabled={sessionStarting}
              style={{ background: '#4a6cf7' }}
            >
              {t('session.setup.startOnlineBtn')}
            </button>
            <button
              style={{ padding: '10px 22px', borderRadius: 8, border: '1px solid #4a6cf7', background: 'transparent', color: '#4a6cf7', cursor: 'pointer', fontSize: '0.95em', fontWeight: 500 }}
              onClick={() => setShowJoinDialog(true)}
            >
              {t('session.join.openBtn')}
            </button>
          </div>
          {showJoinDialog && (
            <JoinDialog
              onJoined={(sid, token, charId, role: 'player' | 'observer' | 'gm', isLobbyActive: boolean, displayName: string) => {
                hostTokenRef.current = token
                sessionIdRef.current = sid
                setSessionId(sid)
                myRoleRef.current = role
                setMyRole(role)
                saveSessionRestoreState({ sessionId: sid, token, role, charId: charId || '', displayName: displayName || '' })
                console.log('[SessionTab] onJoined: isLobbyActive=', isLobbyActive, 'role=', role, 'charId=', charId)
                setLobbyActive(isLobbyActive)
                // プレイヤーとして参加した場合は自分のキャラIDをセット（コントロール表示を切り替える）
                if (role === 'player' && charId) {
                  myCharIdRef.current = charId
                  setHumanCharId(charId)
                  setHumanCharName(displayName || charId)
                }
                setShowJoinDialog(false)
                // playerのみ自己追加（observer/gmはSESSION_STARTEDの参加者リストで届く）
                if (role === 'player' && charId) {
                  setParticipants(prev =>
                    prev.some(x => x.char_id === charId)
                      ? prev
                      : [...prev, { participant_id: charId, char_id: charId, display_name: t('session.join.you'), role, connected: true }]
                  )
                }
              }}
              onClose={() => setShowJoinDialog(false)}
            />
          )}

          {savedSessions.length > 0 && (
            <div className="session-field">
              <label className="session-label">{t('session.setup.savedLabel')}</label>
              <div className="session-saved-list">
                {savedSessions.map(s => (
                  <div key={s.filename} className="session-saved-item" onClick={() => loadSavedSession(s.filename)}>
                    <span className="saved-topic">{s.trpg_scenario_title || s.topic || t('session.setup.savedUntitled')}</span>
                    <span className="saved-meta">
                      {s.character_names.join(' · ')} | Round {s.round}
                      {s.rule_set_label && ` | ${s.rule_set_label}`}
                      {` | ${s.online_mode ? t('session.setup.savedOnline') : t('session.setup.savedOffline')}`}
                    </span>
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
                    <img src={iconUrl(id)} alt="" style={{ width: 28, height: 28, borderRadius: '50%', objectFit: 'cover' }} />
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
  // characters（App.tsxのprop、ローカル専用ポートの/api/characters/でしか取得できず
  // 公開ポート経由のゲストでは常に空）だけでは足りないため、公開ポートでも読める
  // sessionNameMap（GET /{session_id}のname_map）を正本として最後に重ねる。
  const nameMap: Record<string, string> = {
    ...Object.fromEntries(characters.map(c => [c.id, c.name])),
    ...Object.fromEntries(participants.filter(p => p.char_id && p.display_name).map(p => [p.char_id, p.display_name])),
    ...sessionNameMap,
  }

  console.log('[SessionTab] render: sessionId=', sessionId, 'lobbyActive=', lobbyActive)
  if (sessionId && lobbyActive) {
    return (
      <div className="tab-content session-tab" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, minHeight: 300 }}>
        <div style={{ fontSize: '2em' }}>⏳</div>
        <div style={{ fontWeight: 700, fontSize: '1.1em' }}>{t('session.lobby.waitingForHostTitle')}</div>
        <div style={{ opacity: 0.6, fontSize: '0.9em' }}>{t('session.lobby.waitingForHostDesc')}</div>
      </div>
    )
  }

  // 進行権限は常に一人: 人間キーパー（gm）参加中はgmのみ、AIキーパー構成ではホストのみ。
  // ホストはプレイヤー参加・観戦中でもJWTロールが host のまま進行権限を持つ
  const humanGmJoined = participants.some(p => p.role === 'gm')
  const canControlAuto = myRole === 'gm' || (myRole === 'host' && !humanGmJoined)
  const isKeeperUi = myRole === 'host' || myRole === 'gm'
  // イニシアティブに出るプレイヤーはヘッダーの🎭マークで表現できるため、
  // 参加者パネルはイニシアティブに乗らない参加者（gm・observer）のみ表示する
  const offInitiativeParticipants = participants.filter(p => !p.char_id || !initiative.includes(p.char_id))

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
            // 人間担当キャラは🎭マーク・切断中は⚡付きで減光（参加者パネルの代替表示）
            const humanP = participants.find(p => p.char_id === id)
            const isHumanChar = !!humanP || id === myCharIdRef.current
            const disconnected = humanP ? !humanP.connected : false
            const takenOver = aiTakenOverChars.has(id)
            const label = `${isHumanChar ? '🎭' : ''}${takenOver ? '🤖' : disconnected ? '⚡' : ''}${name}${cStr}`
            const canTakeOver = isKeeperUi && disconnected && !takenOver
            return (
              <span
                key={id}
                style={{
                  ...(atMax ? { color: '#e05' } : undefined),
                  ...(disconnected && !takenOver ? { opacity: 0.45 } : undefined),
                }}
                title={takenOver ? t('session.participants.aiTakeover.done') : disconnected ? t('session.participants.disconnected') : undefined}
              >
                {idx > 0 && ' → '}
                {isActive ? <strong>{label}</strong> : label}
                {canTakeOver && (
                  <button
                    onClick={() => aiTakeover(id)}
                    title={t('session.participants.aiTakeover.title')}
                    style={{ border: 'none', background: 'none', cursor: 'pointer', padding: '0 2px', fontSize: '0.9em' }}
                  >🤖</button>
                )}
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
              title={t('session.header.charSheetTitle')}
              style={{ opacity: showSheetPanel ? 1 : 0.55 }}
            >📋</button>
          )}
          {offInitiativeParticipants.length > 0 && (
            <button
              className="novel-hdr-btn"
              onClick={() => setShowParticipantPanel(v => !v)}
              title={t('session.participants.title')}
              style={{ opacity: showParticipantPanel ? 1 : 0.55 }}
            >👥</button>
          )}
          {myRole === 'host' && inviteCode && (
            <InviteCodeDisplay inviteCode={inviteCode} />
          )}
          {myRole === 'host' && (
            <button className="save-btn" onClick={saveCurrentSession} title={t('session.header.saveTitle')}>💾</button>
          )}
          {myRole !== 'host' && (
            <span style={{ fontSize: '0.78em', padding: '3px 10px', borderRadius: 4, border: '1px solid var(--border-color, rgba(128,128,128,0.3))', opacity: 0.75, whiteSpace: 'nowrap' }}>
              {myRole === 'gm' ? t('trpg.role.keeper') : myRole === 'player' ? t('session.roleBadge.player') : t('session.roleBadge.observer')}
            </span>
          )}
          {myRole === 'host'
            ? <button className="end-btn" onClick={() => endSession()}>{t('session.header.endBtn')}</button>
            : <button className="end-btn" style={{ background: '#888' }} onClick={() => endSession(true)}>{t('session.header.leaveBtn')}</button>
          }
        </div>
      </div>

      {isKeeperUi && auditWarnings.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 10px', background: 'rgba(231,76,60,0.12)', borderBottom: '1px solid var(--error-color, #e74c3c)' }}>
          {auditWarnings.map(w => (
            <div key={w.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--error-color, #e74c3c)' }}>
              <span>⚠ {t('session.auditSkipped', { name: nameMap[w.characterId] || w.characterId, reason: w.reason })}</span>
              <button
                onClick={() => setAuditWarnings(prev => prev.filter(x => x.id !== w.id))}
                style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', opacity: 0.7 }}
              >×</button>
            </div>
          ))}
        </div>
      )}

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
                src={standingFallback.has(cid) ? iconUrl(cid) : standingUrl(cid)}
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
        {hiddenSessionHistory.length > 0 && (
          <div className="load-more-wrap">
            <button className="load-more-btn" onClick={() => {
              setMessages(prev => [...hiddenSessionHistory, ...prev])
              setHiddenSessionHistory([])
            }}>
              {t('session.history.showBtn', { n: hiddenSessionHistory.length })}
            </button>
          </div>
        )}
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
                      onDoubleClick={() => window.open(m.imageUrl, '_blank', 'noopener,noreferrer')}
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
                    : <img src={iconUrl(m.character_id)} alt="" className="avatar" />
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
                    {m.audioUrl && !blocked && (
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
      {offInitiativeParticipants.length > 0 && showParticipantPanel && (
        <div style={{ width: 160, overflowY: 'auto', borderLeft: '1px solid var(--border-color, #444)', flexShrink: 0 }}>
          <ParticipantList participants={offInitiativeParticipants} />
        </div>
      )}
      {trpgMode && showSheetPanel && Object.keys(charSheetData).length > 0 && (
        <div style={{ width: 220, overflowY: 'auto', borderLeft: '1px solid var(--border-color, #444)', padding: '10px 8px', flexShrink: 0, fontSize: '0.8em' }}>
          {Object.entries(charSheetData).map(([charId, sheet]) => {
            const stats: Record<string, { current: number; max?: number }> = sheet.stats ?? {}
            const isDead = Object.values(stats).some(v => v.current <= 0)
            return (
              <div key={charId} style={{ marginBottom: 16, opacity: isDead ? 0.5 : 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 6 }}>
                  <img src={iconUrl(charId)} alt="" style={{ width: 20, height: 20, borderRadius: '50%', objectFit: 'cover', filter: isDead ? 'grayscale(1)' : 'none' }} />
                  <span style={{ fontWeight: 600 }}>{isDead ? '💀 ' : ''}{charMap[charId]?.name ?? charId}</span>
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ opacity: 0.5 }}>
                      <th style={{ textAlign: 'left', padding: '1px 3px', fontWeight: 'normal' }}>{t('session.stats.ability')}</th>
                      <th style={{ textAlign: 'right', padding: '1px 3px', fontWeight: 'normal' }}>{t('session.stats.current')}</th>
                      <th style={{ textAlign: 'right', padding: '1px 3px', fontWeight: 'normal' }}>{t('session.stats.max')}</th>
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
                {isDead && <div style={{ marginTop: 4, fontSize: '0.85em', opacity: 0.7 }}>{t('session.stats.deadStatus')}</div>}
              </div>
            )
          })}
        </div>
      )}
      </div>

      <div className="session-controls" style={myRole === 'observer' ? { display: 'none' } : undefined}>
        {humanCharId && (
          <>
            <div className="session-controls-row">
              {canControlAuto ? (
                <button
                  className={`auto-advance-btn ${autoAdvance ? 'active' : ''}`}
                  onClick={toggleAutoAdvance}
                  disabled={waitingForHuman}
                  title={autoAdvance ? t('session.ctrl.autoAdvance.stopTitle') : t('session.ctrl.autoAdvance.startTitle')}
                >
                  {autoAdvance ? t('session.ctrl.autoBtn.stop') : t('session.ctrl.autoBtn.auto')}
                </button>
              ) : autoAdvance ? (
                <span className="auto-advance-btn active" style={{ cursor: 'default', opacity: 0.7 }} title={t('session.autoAdvance.keeperActiveTitle')}>{t('session.autoAdvance.keeperActiveLabel')}</span>
              ) : null}
              {autoStopMsg && !autoAdvance && (
                <span style={{ fontSize: 11, color: 'var(--error-color, #e74c3c)', opacity: 0.85 }}>⚠ {autoStopMsg}</span>
              )}
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
              {isKeeperUi && (
                <button onClick={() => void authFetch(`/api/session/${sessionId}/ai_resume`, { method: 'POST' })} disabled={waitingForHuman || interruptMode || loading || autoAdvance} className="next-btn">{t('session.ctrl.nextBtn')}</button>
              )}
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
        {!humanCharId && isKeeperUi && waitingForKeeperTurn && (
          <div className="session-controls-row" style={{ background: 'rgba(74,108,247,0.12)', border: '1px solid #4a6cf7', borderRadius: 8, padding: '6px 10px' }}>
            <span style={{ fontWeight: 600, color: '#4a6cf7' }}>{t('trpg.keeper.turnBanner')}</span>
          </div>
        )}
        {!humanCharId && isKeeperUi && <div className="session-controls-row">
          {canControlAuto ? (
            <button
              className={`auto-advance-btn ${autoAdvance ? 'active' : ''}`}
              onClick={toggleAutoAdvance}
              title={autoAdvance ? t('session.ctrl.autoAdvance.stopTitle') : t('session.ctrl.autoAdvance.startTitle')}
            >
              {autoAdvance ? t('session.ctrl.autoBtn.stop') : t('session.ctrl.autoBtn.auto')}
            </button>
          ) : autoAdvance ? (
            <span className="auto-advance-btn active" style={{ cursor: 'default', opacity: 0.7 }} title={t('session.autoAdvance.keeperActiveTitle')}>{t('session.autoAdvance.keeperActiveLabel')}</span>
          ) : null}
          {autoStopMsg && !autoAdvance && (
            <span style={{ fontSize: 11, color: 'var(--error-color, #e74c3c)', opacity: 0.85 }}>⚠ {autoStopMsg}</span>
          )}
          <input
            className="keeper-input"
            type="text"
            value={keeperInput}
            onChange={e => setKeeperInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addKeeperAction() } }}
            placeholder={t('session.ctrl.keeperInput.placeholder')}
          />
          <button onClick={addKeeperAction} disabled={!keeperInput.trim() || (actionsPerTurn > 0 && pendingActions.length >= actionsPerTurn)} className="keeper-add-btn">{t('session.ctrl.queueBtn')}</button>
          <button onClick={commitKeeperActions} disabled={pendingActions.length === 0} className="keeper-send-btn">{t('session.ctrl.keeperSendBtn')}</button>
          <button onClick={() => setPendingActions([])} disabled={pendingActions.length === 0} className="keeper-redo-btn">{t('session.ctrl.discardBtn')}</button>
          <button onClick={() => void authFetch(`/api/session/${sessionId}/ai_resume`, { method: 'POST' })} disabled={loading || autoAdvance} className="next-btn">{t('session.ctrl.nextBtn')}</button>
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
        {!humanCharId && isKeeperUi && <div className="session-controls-row">
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
                    onClick={() => rollPendingJudgment(j, idx)}
                  >{t('trpg.judgment.roll')}</button>
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
                void authFetch(`/api/session/${sessionId}/ai_resume`, { method: 'POST' })
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
                        <img src={iconUrl(diceDialogChars[0])} alt="" style={{ width: 22, height: 22, borderRadius: '50%', objectFit: 'cover' }} />
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
                            <img src={iconUrl(id)} alt="" style={{ width: 18, height: 18, borderRadius: '50%', objectFit: 'cover' }} />
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
                      <option value="">{t('common.selectPlaceholder')}</option>
                      {allStatKeys.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <button className="keeper-send-btn" disabled={noChars || !diceDialogStatKey} onClick={() => rollDiceDialog('stat', diceDialogStatKey)}>{t('trpg.diceDialog.rollBtn')}</button>
                  </div>
                )}
                {allSkillKeys.length > 0 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 600, minWidth: 72, flexShrink: 0 }}>{t('trpg.diceDialog.skill')}</span>
                    <select className="session-select" style={{ flex: 1 }} value={diceDialogSkillKey} onChange={e => setDiceDialogSkillKey(e.target.value)}>
                      <option value="">{t('common.selectPlaceholder')}</option>
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
