// SessionTab.tsx から分離した、コンポーネント非依存の純粋関数・型。
// `SessionTab.tsx`分割の第一段階（TODO.md「SessionTab.tsxのコンポーネント分割」参照）。

export type Character = { id: string; name: string; image_color?: string; player_type?: string }

export type SessionMessage = {
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
  // AIターン自動生成の挿絵/音声（TURN_IMAGE_READY・TURN_AUDIO_READY）をこのメッセージに
  // 紐付けるための識別子。サーバー側は history のインデックスを持たないため round+turn を使う
  turnRound?: number
  turnTurn?: number
}

// 生の history 配列(セーブファイル読み込み・GET /{session_id}どちらも同じ形)から
// 表示用の SessionMessage[] を組み立てる。loadSavedSession() と、接続時の
// 履歴取得の両方から使う共通ロジック。
export function reconstructMessages(
  history: any[],
  nameMap: Record<string, string>,
  charMap: Record<string, Character>,
): SessionMessage[] {
  // _dice 旧データ用: "🎲 CharName【stat】..." からキャラ名を逆引き
  const reverseNameMap: Record<string, string> = {}
  for (const [id, n] of Object.entries(nameMap)) reverseNameMap[n] = id

  return history.map(h => {
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
}

// リロード後もセッションへ復帰できるよう、参加/作成が成功した時点の最小限の
// 情報をsessionStorageへ書く(タブを閉じれば消える。localStorageではなく
// sessionStorageなのは、複数タブでホスト/ゲストを別々に開くテスト等での
// 汚染を避けるため)。App.tsxは同じキーを「起動時にsessionタブを開くか」の
// 判定にのみ使い、値の中身は読まない。
const SESSION_RESTORE_KEY = 'def_active_session'

export type SessionRestoreState = {
  sessionId: string
  token: string
  role: 'host' | 'player' | 'observer' | 'gm'
  charId: string
  displayName: string
}

export function saveSessionRestoreState(state: SessionRestoreState) {
  try { sessionStorage.setItem(SESSION_RESTORE_KEY, JSON.stringify(state)) } catch { /* ignore */ }
}

export function loadSessionRestoreState(): SessionRestoreState | null {
  try {
    const raw = sessionStorage.getItem(SESSION_RESTORE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

export function clearSessionRestoreState() {
  try { sessionStorage.removeItem(SESSION_RESTORE_KEY) } catch { /* ignore */ }
}

// ゲスト（招待コードでオンボーディング画面からjoinした参加者）判定専用のマーカー。
// def_active_session（ホストがローカルポートで自セッションに追加参加する場合にも
// セットされる）だけでは、host/guestを区別できないため別キーとして持つ
// （2026-08-23、GuestGate.tsx参照）。GuestOnboardingFlow.tsxがjoin成功時のみセットする。
const GUEST_MODE_KEY = 'def_guest_mode'

export function markGuestMode() {
  try { sessionStorage.setItem(GUEST_MODE_KEY, '1') } catch { /* ignore */ }
}

export function isGuestMode(): boolean {
  try { return sessionStorage.getItem(GUEST_MODE_KEY) === '1' } catch { return false }
}

const SEXUAL_TAGS = ['sfw', 'nsfw', 'hentai']
const VIOLENCE_TAGS = ['violence', 'gore', 'extreme']

export function isContentBlocked(tags: string[], allowedSexual: string[], allowedViolence: string[]): boolean {
  return tags.some(tag =>
    (SEXUAL_TAGS.includes(tag) && !allowedSexual.includes(tag)) ||
    (VIOLENCE_TAGS.includes(tag) && !allowedViolence.includes(tag))
  )
}
