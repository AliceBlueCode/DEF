import { useState, useEffect, useCallback } from 'react'
import Toggle from './Toggle'

const SEXUAL_PRESETS: Record<string, string[]> = {
  general: ['general'],
  nsfw:    ['general', 'nsfw'],
  hentai:  ['general', 'nsfw', 'hentai'],
}

const VIOLENCE_PRESETS: Record<string, string[]> = {
  general:  ['general'],
  violence: ['general', 'violence'],
  extreme:  ['general', 'violence', 'gore', 'extreme'],
}

function toPresetKey(val: unknown, presets: Record<string, string[]>): string {
  const arr = Array.isArray(val) ? [...val].sort() : ['general']
  for (const [k, v] of Object.entries(presets)) {
    if (JSON.stringify([...v].sort()) === JSON.stringify(arr)) return k
  }
  return Object.keys(presets)[0]
}

export default function Sidebar() {
  const [settings, setSettings] = useState<Record<string, unknown>>({})

  useEffect(() => {
    fetch('/api/settings/')
      .then(r => r.json())
      .then(data => setSettings(data.settings || {}))
  }, [])

  const get = useCallback(<T,>(key: string, def: T): T =>
    (key in settings ? settings[key] : def) as T, [settings])

  const set = useCallback((key: string, value: unknown) => {
    setSettings(prev => ({ ...prev, [key]: value }))
    fetch('/api/settings/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: { [key]: value } }),
    })
  }, [])

  return (
    <aside className="sidebar">

      <div className="sidebar-section">
        <h4>チャット設定</h4>
        <div className="sidebar-row">
          <span>キャラ挨拶</span>
          <Toggle checked={get('character_greeting', true)} onChange={v => set('character_greeting', v)} />
        </div>
        <div className="sidebar-row">
          <span>TTS 有効</span>
          <Toggle checked={get('tts_enabled', true)} onChange={v => set('tts_enabled', v)} />
        </div>
        <div className="sidebar-row">
          <span>ユーザー TTS</span>
          <Toggle checked={get('tts_human_enabled', false)} onChange={v => set('tts_human_enabled', v)} />
        </div>
        <div className="sidebar-row">
          <span>Undo 件数</span>
          <input
            type="number" min={1} max={10}
            className="sidebar-number"
            value={get('undo_max_history', 5)}
            onChange={e => set('undo_max_history', Number(e.target.value))}
          />
        </div>
      </div>

      <div className="sidebar-section">
        <h4>安全設定</h4>
        <div className="sidebar-col">
          <span>安全レベル</span>
          <select
            className="sidebar-select"
            value={get('safety_level', 'warn')}
            onChange={e => set('safety_level', e.target.value)}
          >
            <option value="off">オフ</option>
            <option value="warn">警告</option>
            <option value="mask">マスク</option>
          </select>
        </div>
        <div className="sidebar-col">
          <span>性的コンテンツ</span>
          <select
            className="sidebar-select"
            value={toPresetKey(get('allowed_rating_sexual', ['general']), SEXUAL_PRESETS)}
            onChange={e => set('allowed_rating_sexual', SEXUAL_PRESETS[e.target.value])}
          >
            <option value="general">全年齢</option>
            <option value="nsfw">R-15相当</option>
            <option value="hentai">R-18相当</option>
          </select>
        </div>
        <div className="sidebar-col">
          <span>暴力コンテンツ</span>
          <select
            className="sidebar-select"
            value={toPresetKey(get('allowed_rating_violence', ['general']), VIOLENCE_PRESETS)}
            onChange={e => set('allowed_rating_violence', VIOLENCE_PRESETS[e.target.value])}
          >
            <option value="general">全年齢</option>
            <option value="violence">一般暴力</option>
            <option value="extreme">過激</option>
          </select>
        </div>
      </div>

    </aside>
  )
}
