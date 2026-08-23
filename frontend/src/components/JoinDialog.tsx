import { useState, useRef } from 'react'
import { useT } from '../i18n'

type Slot = { char_id: string; char_name: string; available: boolean }
type SlotData = { human_slots: Slot[]; online_mode: boolean; gm_taken: boolean; waiting_for_gm: boolean; trpg_mode: boolean; trpg_rulebook: string }

type Props = {
  onJoined: (sessionId: string, playerToken: string, charId: string, role: 'player' | 'observer' | 'gm', lobbyActive: boolean, displayName: string, sheetId: string, sheetData: any) => void
  onClose: () => void
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

const S = {
  overlay: { position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 } as React.CSSProperties,
  box: { background: 'var(--bg-color, #fff)', border: '1px solid var(--border-color, #ddd)', borderRadius: 12, padding: '28px 32px', minWidth: 340, maxWidth: 460, width: '90vw', boxShadow: '0 8px 32px rgba(0,0,0,0.15)', display: 'flex', flexDirection: 'column', gap: 16 } as React.CSSProperties,
  title: { margin: 0, fontSize: '1.1em', fontWeight: 700 } as React.CSSProperties,
  label: { fontSize: '0.82em', opacity: 0.55, marginBottom: 4 } as React.CSSProperties,
  input: { width: '100%', boxSizing: 'border-box', padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'var(--input-bg, #f5f5f5)', color: 'inherit', fontSize: '0.95em' } as React.CSSProperties,
  error: { color: 'var(--danger-color, #d32)', fontSize: '0.85em' } as React.CSSProperties,
  actions: { display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 4 } as React.CSSProperties,
  cancelBtn: { padding: '7px 18px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'transparent', color: 'inherit', cursor: 'pointer' } as React.CSSProperties,
  submitBtn: { padding: '7px 20px', borderRadius: 6, border: 'none', background: '#4a6cf7', color: '#fff', cursor: 'pointer', fontWeight: 600 } as React.CSSProperties,
}

export default function JoinDialog({ onJoined, onClose }: Props) {
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
  const fileInputRef = useRef<HTMLInputElement>(null)

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

  const join = async () => {
    setError('')
    const code = inviteCode.trim().toUpperCase()
    if (!code) { setError(t('session.join.errorNoCode')); return }

    // 参加ボタン押下時は最新スロット状態を取得（ホストの役割変更を反映するため）
    const hadSlotsLoaded = slotsLoaded
    lastFetchedCode.current = ''
    const fresh = await fetchSlots(code, false)  // 選択をリセットしない
    if (!fresh) {
      // 初回取得失敗 or 同コード再実行はスロット未ロードとして扱う
      if (!hadSlotsLoaded) return
      // すでにスロットが表示済みなら古いデータでそのまま進む
    } else {
      // 新データで keeper 埋まり判定
      if (selectedSlot === '__gm__' && fresh.gm_taken) {
        setError(t('session.join.errorGmTaken'))
        return
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
        if (JSON.stringify(freshIds) !== JSON.stringify(currentIds)) return
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
          return
        }
        // 選択肢が観戦者しか無いセッションでは、そのまま観戦者として参加を続行する。
      }
    }

    // オンラインモードでプレイヤーとして参加する場合はJSONが必要
    if ((fresh?.online_mode ?? onlineMode) && selectedSlot === '__player__' && !charJson) {
      setError(t('session.join.errorNoCharJson'))
      return
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
        return
      }
      console.log('[JoinDialog] join response:', { session_id: data.session_id, role: data.role, lobby_active: data.lobby_active, display_name: data.display_name })
      const sheetId = isOnlinePlayer ? selectedSheetId : ''
      onJoined(data.session_id, data.player_token, data.character_id, data.role ?? 'observer', data.lobby_active ?? false, data.display_name ?? '', sheetId, sheetId ? parsedSheets[sheetId] : null)
    } catch {
      setError(t('session.join.errorFailed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={S.overlay} onClick={onClose}>
      <div style={S.box} onClick={e => e.stopPropagation()}>
        <h3 style={S.title}>{t('session.join.title')}</h3>

        <div>
          <div style={S.label}>{t('session.join.codeLabel')}</div>
          <input
            style={S.input}
            placeholder="SFW-ABK-492"
            value={inviteCode}
            onChange={e => {
              setInviteCode(e.target.value)
              setSlotsLoaded(false)
              lastFetchedCode.current = ''
            }}
            onBlur={() => void fetchSlots(inviteCode)}
            onKeyDown={e => {
              if (e.key === 'Enter') void fetchSlots(inviteCode)
            }}
            autoFocus
          />
        </div>

        {slotsLoaded && (
          <div>
            <div style={S.label}>{t('session.join.slotLabel')}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', padding: '6px 8px', borderRadius: 6, background: selectedSlot === '__observer__' ? 'var(--input-bg, rgba(128,128,128,0.15))' : 'transparent' }}>
                <input type="radio" name="slot" value="__observer__" checked={selectedSlot === '__observer__'} onChange={() => setSelectedSlot('__observer__')} />
                <span style={{ fontSize: '0.9em' }}>👁 {t('session.join.observerSlot')}</span>
              </label>

              {onlineMode ? (
                <>
                  {/* キーパーとして参加（ホストが「参加者を待つ」を選んだ時のみ表示） */}
                  {waitingForGm && (
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: gmTaken ? 'not-allowed' : 'pointer', opacity: gmTaken ? 0.4 : 1, padding: '6px 8px', borderRadius: 6, background: selectedSlot === '__gm__' ? 'var(--input-bg, rgba(128,128,128,0.15))' : 'transparent' }}>
                      <input type="radio" name="slot" value="__gm__" disabled={gmTaken} checked={selectedSlot === '__gm__'} onChange={() => !gmTaken && setSelectedSlot('__gm__')} />
                      <span style={{ fontSize: '0.9em' }}>{t('session.join.gmSlot')}</span>
                      {gmTaken && <span style={{ fontSize: '0.75em', opacity: 0.6 }}>{t('session.join.gmTakenBadge')}</span>}
                    </label>
                  )}
                  {/* プレイヤーとして参加（キャラJSON持ち込み） */}
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', padding: '6px 8px', borderRadius: 6, background: selectedSlot === '__player__' ? 'var(--input-bg, rgba(128,128,128,0.15))' : 'transparent' }}>
                    <input type="radio" name="slot" value="__player__" checked={selectedSlot === '__player__'} onChange={() => setSelectedSlot('__player__')} />
                    <span style={{ fontSize: '0.9em' }}>{t('session.join.playerSlot')}</span>
                  </label>
                </>
              ) : (
                slots.map(slot => (
                  <label
                    key={slot.char_id}
                    style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: slot.available ? 'pointer' : 'not-allowed', opacity: slot.available ? 1 : 0.4, padding: '6px 8px', borderRadius: 6, background: selectedSlot === slot.char_id ? 'var(--input-bg, rgba(128,128,128,0.15))' : 'transparent' }}
                  >
                    <input
                      type="radio"
                      name="slot"
                      value={slot.char_id}
                      disabled={!slot.available}
                      checked={selectedSlot === slot.char_id}
                      onChange={() => slot.available && setSelectedSlot(slot.char_id)}
                    />
                    <span style={{ fontSize: '0.9em' }}>🎭 {slot.char_name}</span>
                    {!slot.available && <span style={{ fontSize: '0.75em', opacity: 0.6 }}>{t('session.join.slotTaken')}</span>}
                  </label>
                ))
              )}
            </div>

            {onlineMode && selectedSlot === '__player__' && (
              <div style={{ marginTop: 10 }}>
                <div style={S.label}>{t('session.join.charJsonLabel')}</div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".json"
                  style={{ display: 'none' }}
                  onChange={handleFileSelect}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  style={{ padding: '7px 16px', borderRadius: 6, border: '1px solid var(--border-color, #ccc)', background: 'transparent', color: 'inherit', cursor: 'pointer', fontSize: '0.9em' }}
                >
                  {charJsonName ? `✓ ${charJsonName}` : t('session.join.selectJsonBtn')}
                </button>
                {trpgMode && charJson && sheetOptions.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <div style={S.label}>{t('session.join.sheetLabel')}</div>
                    <select
                      className="session-select"
                      style={S.input}
                      value={selectedSheetId}
                      onChange={e => setSelectedSheetId(e.target.value)}
                    >
                      <option value="">{t('trpg.gameChar.noSheet')}</option>
                      {sheetOptions.map(sid => (
                        <option key={sid} value={sid}>{sid}</option>
                      ))}
                    </select>
                  </div>
                )}
                {trpgMode && charJson && sheetOptions.length === 0 && (
                  <div style={{ ...S.label, marginTop: 10 }}>{t('session.join.noSheetMatch')}</div>
                )}
              </div>
            )}
          </div>
        )}

        {error && <div style={S.error}>{error}</div>}

        <div style={S.actions}>
          <button style={S.cancelBtn} onClick={onClose}>{t('common.cancel')}</button>
          <button style={{ ...S.submitBtn, opacity: loading ? 0.6 : 1 }} onClick={join} disabled={loading || !inviteCode.trim()}>
            {loading ? '...' : t('session.join.submit')}
          </button>
        </div>
      </div>
    </div>
  )
}
