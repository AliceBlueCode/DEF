import { useRef, useState } from 'react'
import { useT } from '../i18n'

export type Slot = { char_id: string; char_name: string; available: boolean }
export type SlotData = { human_slots: Slot[]; online_mode: boolean; gm_taken: boolean; waiting_for_gm: boolean; trpg_mode: boolean; trpg_rulebook: string }

export type JoinResult = {
  sessionId: string
  playerToken: string
  charId: string
  role: 'player' | 'observer' | 'gm'
  lobbyActive: boolean
  displayName: string
  sheetId: string
  sheetData: any
}

// DEFキャラJSON: game_rules_sheetsはbase_profileの兄弟キー（data/public/characters/*/
// profile.json参照）。flat形式・versioned形式の両方に対応する
// （def_kari/characters.pyの_extract_game_sheets_from_guest_jsonと同じ判定ロジック）。
function extractGameSheets(characterJson: Record<string, unknown>): Record<string, any> {
  for (const v of Object.values(characterJson)) {
    if (v && typeof v === 'object' && (v as any).base_profile) {
      return (v as any).game_rules_sheets ?? {}
    }
  }
  return (characterJson.game_rules_sheets as Record<string, any>) ?? {}
}

// JoinDialog.tsx（モーダル、ホストがローカルポート経由で自セッションへ追加参加する用途）と
// GuestOnboardingFlow.tsx（公開ポート経由の実ゲスト向け専用画面）の両方から使う共有ロジック。
// モバイル二重タップ対策・オンライン+空スロット判定・TRPGシート絞り込み等、実機バグ修正の
// 積み重ねを一箇所に保つため、ロジックはここに集約しJSXは各呼び出し元に委ねる
// （2026-08-23、TERMS同意オンボーディング画面の実装にあわせて抽出）。
export function useJoinFlow() {
  const t = useT()
  const [inviteCode, setInviteCode] = useState('')
  const [slots, setSlots] = useState<Slot[]>([])
  const [selectedSlot, setSelectedSlot] = useState<string>('__observer__')
  const [slotsLoaded, setSlotsLoaded] = useState(false)
  const [onlineMode, setOnlineMode] = useState(false)
  const [gmTaken, setGmTaken] = useState(false)
  const [waitingForGm, setWaitingForGm] = useState(false)
  const [charJson, setCharJson] = useState<Record<string, unknown> | null>(null)
  const [charJsonName, setCharJsonName] = useState('')
  const [trpgMode, setTrpgMode] = useState(false)
  const [trpgRulebook, setTrpgRulebook] = useState('')
  const [sheetOptions, setSheetOptions] = useState<string[]>([])
  const [selectedSheetId, setSelectedSheetId] = useState('')
  const [parsedSheets, setParsedSheets] = useState<Record<string, any>>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const lastFetchedCode = useRef('')

  const fetchSlots = async (code: string, resetSelection = true): Promise<SlotData | null> => {
    const normalized = code.trim().toUpperCase()
    if (!normalized || normalized === lastFetchedCode.current) return null
    lastFetchedCode.current = normalized
    try {
      const res = await fetch('/api/session/available-slots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ invite_code: normalized }),
      })
      if (!res.ok) {
        setSlots([])
        setSlotsLoaded(false)
        return null
      }
      const data: SlotData = await res.json()
      setSlots(data.human_slots ?? [])
      setOnlineMode(data.online_mode ?? false)
      setGmTaken(data.gm_taken ?? false)
      setWaitingForGm(data.waiting_for_gm ?? false)
      setTrpgMode(data.trpg_mode ?? false)
      setTrpgRulebook(data.trpg_rulebook ?? '')
      setSlotsLoaded(true)
      if (resetSelection) setSelectedSlot('__observer__')
      setError('')
      return data
    } catch {
      setSlots([])
      setSlotsLoaded(false)
      return null
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = ev => {
      try {
        const json = JSON.parse(ev.target?.result as string)
        setCharJson(json)
        // DEFキャラJSON: {version: {base_profile: {name: ...}}} またはフラット {name: ...}
        const topVal = Object.values(json)[0] as Record<string, any> | undefined
        const extractedName: string = json.name ?? topVal?.base_profile?.name ?? file.name
        setCharJsonName(extractedName)
        // TRPGモードのセッションでは、持ち込みJSONに埋め込まれたgame_rules_sheetsのうち
        // セッションのルールブック(trpgRulebook)と一致するものだけを選択肢にする
        // （2026-08-23、TRPGモードのゲスト参加時にキャラクターシートを選べない問題への対応）。
        if (trpgMode) {
          const sheets = extractGameSheets(json)
          setParsedSheets(sheets)
          const matching = Object.entries(sheets)
            .filter(([, sheet]: [string, any]) => sheet?.rulebook_id === trpgRulebook)
            .map(([sid]) => sid)
          setSheetOptions(matching)
          setSelectedSheetId(matching.length === 1 ? matching[0] : '')
        } else {
          setParsedSheets({})
          setSheetOptions([])
          setSelectedSheetId('')
        }
        setError('')
      } catch {
        setError(t('session.join.errorBadJson'))
        setCharJson(null)
        setCharJsonName('')
        setParsedSheets({})
        setSheetOptions([])
        setSelectedSheetId('')
      }
    }
    reader.readAsText(file)
  }

  const join = async (): Promise<JoinResult | null> => {
    setError('')
    const code = inviteCode.trim().toUpperCase()
    if (!code) { setError(t('session.join.errorNoCode')); return null }

    // 参加ボタン押下時は最新スロット状態を取得（ホストの役割変更を反映するため）
    const hadSlotsLoaded = slotsLoaded
    lastFetchedCode.current = ''
    const fresh = await fetchSlots(code, false)  // 選択をリセットしない
    if (!fresh) {
      // 初回取得失敗 or 同コード再実行はスロット未ロードとして扱う
      if (!hadSlotsLoaded) return null
      // すでにスロットが表示済みなら古いデータでそのまま進む
    } else {
      // 新データで keeper 埋まり判定
      if (selectedSlot === '__gm__' && fresh.gm_taken) {
        setError(t('session.join.errorGmTaken'))
        return null
      }
      if (hadSlotsLoaded) {
        // 既に表示済みのスロット一覧と比較し、他ゲストの参加等で変わっていたら
        // 選び直させる。コード入力後スロット一覧が表示される前に「参加」を
        // 押した場合（＝このfetchSlotsが初回ロードを兼ねている）は、
        // 比較対象となる旧スロット一覧がまだ空のstateしかなく、常に不一致
        // 判定になって無反応（無言でreturn）に見えるバグになっていた
        // （スマホで「コード入力→即タップ」した際に再現、2026-08-10）。
        const freshIds = (fresh.human_slots ?? []).map((s: Slot) => s.char_id)
        const currentIds = slots.map(s => s.char_id)
        if (JSON.stringify(freshIds) !== JSON.stringify(currentIds)) return null
      } else {
        // オンラインモードは human_slots が空でも「プレイヤーとして参加」
        // （キャラJSON持ち込み）が常に選べる（slotsLoaded時のJSX参照）ため、
        // online_mode自体も選択肢ありとして扱う。ここに online_mode を含め忘れると、
        // human_slotsが空でwaiting_for_gmもfalseなオンラインセッションで「プレイヤー
        // として参加」を選ぶ機会が無いまま、無言で観戦者として参加してしまう
        // （2026-08-10、実機検証で発覚）。
        const hasChoices = fresh.online_mode || (fresh.human_slots ?? []).length > 0 || fresh.waiting_for_gm
        if (hasChoices) {
          // 初回ロードでは選択肢をまだ提示できていないため、参加枠一覧を表示して
          // 選んでもらう（観戦者以外を選べる可能性があるのに無言で観戦者として
          // 参加させてしまわないよう、ここでは一旦止める）。
          setError(t('session.join.hintReselect'))
          return null
        }
        // 選択肢が観戦者しか無いセッションでは、そのまま観戦者として参加を続行する。
      }
    }

    // オンラインモードでプレイヤーとして参加する場合はJSONが必要
    if ((fresh?.online_mode ?? onlineMode) && selectedSlot === '__player__' && !charJson) {
      setError(t('session.join.errorNoCharJson'))
      return null
    }

    setLoading(true)
    try {
      const isOnlinePlayer = onlineMode && selectedSlot === '__player__'
      const isGm = selectedSlot === '__gm__'
      const claimCharId = (!onlineMode && selectedSlot !== '__observer__') ? selectedSlot : ''
      const res = await fetch('/api/session/join', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          invite_code: code,
          claim_char_id: claimCharId,
          character_json: isOnlinePlayer ? charJson : {},
          join_as_gm: isGm,
          game_sheet_id: isOnlinePlayer ? selectedSheetId : '',
        }),
      })
      const data = await res.json()
      if (!res.ok) {
        setError(data.detail ?? t('session.join.errorFailed'))
        return null
      }
      console.log('[useJoinFlow] join response:', { session_id: data.session_id, role: data.role, lobby_active: data.lobby_active, display_name: data.display_name })
      const sheetId = isOnlinePlayer ? selectedSheetId : ''
      return {
        sessionId: data.session_id,
        playerToken: data.player_token,
        charId: data.character_id,
        role: data.role ?? 'observer',
        lobbyActive: data.lobby_active ?? false,
        displayName: data.display_name ?? '',
        sheetId,
        sheetData: sheetId ? parsedSheets[sheetId] : null,
      }
    } catch {
      setError(t('session.join.errorFailed'))
      return null
    } finally {
      setLoading(false)
    }
  }

  return {
    inviteCode, setInviteCode,
    slots, selectedSlot, setSelectedSlot,
    slotsLoaded, setSlotsLoaded,
    onlineMode, gmTaken, waitingForGm,
    charJson, charJsonName,
    trpgMode, sheetOptions, selectedSheetId, setSelectedSheetId,
    error, setError,
    loading,
    lastFetchedCode,
    fetchSlots, handleFileSelect, join,
  }
}
