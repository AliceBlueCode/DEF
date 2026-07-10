import { useState, useEffect, useCallback, useRef } from 'react'
import Toggle from './Toggle'
import RatingDialog from './RatingDialog'
import { useT } from '../i18n'

const SEXUAL_PRESETS: Record<string, string[]> = {
  general: ['general'],
  sfw:     ['general', 'sfw'],
  nsfw:    ['general', 'sfw', 'nsfw'],
  hentai:  ['general', 'sfw', 'nsfw', 'hentai'],
}

const VIOLENCE_PRESETS: Record<string, string[]> = {
  general:  ['general'],
  violence: ['general', 'violence'],
  gore:     ['general', 'violence', 'gore'],
  extreme:  ['general', 'violence', 'gore', 'extreme'],
}

const FORCE_RATING_TAGS = ['nsfw', 'hentai', 'violence', 'gore', 'extreme', 'sfw']

function toPresetKey(val: unknown, presets: Record<string, string[]>): string {
  const arr = Array.isArray(val) ? [...val].sort() : ['general']
  for (const [k, v] of Object.entries(presets)) {
    if (JSON.stringify([...v].sort()) === JSON.stringify(arr)) return k
  }
  return Object.keys(presets)[0]
}

export default function Sidebar() {
  const [settings, setSettings] = useState<Record<string, unknown>>({})
  const [vramLocked, setVramLocked] = useState(false)
  const [forceEnabled, setForceEnabled] = useState(false)
  const [forceTag, setForceTag] = useState('nsfw')
  const [showRating, setShowRating] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const vramTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    fetch('/api/settings/')
      .then(r => r.json())
      .then(data => setSettings(data.settings || {}))

    fetch('/api/chat/force-rating')
      .then(r => r.json())
      .then(data => {
        setForceEnabled(data.enabled ?? false)
        setForceTag(data.tag ?? 'nsfw')
      })

    const poll = () => {
      fetch('/api/chat/vram-lock')
        .then(r => r.json())
        .then(data => setVramLocked(data.locked ?? false))
        .catch(() => {})
      fetch('/api/chat/force-rating')
        .then(r => r.json())
        .then(data => setForceEnabled(data.enabled ?? false))
        .catch(() => {})
    }
    poll()
    vramTimerRef.current = setInterval(poll, 3000)
    return () => { if (vramTimerRef.current) clearInterval(vramTimerRef.current) }
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
    window.dispatchEvent(new CustomEvent('def-settings-change', { detail: { key, value } }))
  }, [])

  const updateForceRating = (enabled: boolean, tag: string) => {
    fetch('/api/chat/force-rating', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled, tag }),
    })
  }

  const handleForceEnabled = (v: boolean) => {
    setForceEnabled(v)
    updateForceRating(v, forceTag)
  }

  const handleForceTag = (tag: string) => {
    setForceTag(tag)
    updateForceRating(forceEnabled, tag)
  }

  const sexualKey = toPresetKey(get('allowed_rating_sexual', ['general']), SEXUAL_PRESETS)
  const violenceKey = toPresetKey(get('allowed_rating_violence', ['general']), VIOLENCE_PRESETS)

  const t = useT()
  const handleSexual = (key: string) => set('allowed_rating_sexual', SEXUAL_PRESETS[key])
  const handleViolence = (key: string) => set('allowed_rating_violence', VIOLENCE_PRESETS[key])

  return (
    <aside className={`sidebar${collapsed ? ' sidebar-collapsed' : ''}`}>
      <button className="sidebar-toggle" onClick={() => setCollapsed(c => !c)} title={collapsed ? t('sidebar.toggleBtn.open') : t('sidebar.toggleBtn.close')}>
        {collapsed ? '▶' : '◀'}
      </button>

      <div className="sidebar-section">
        <button className="rating-open-btn" onClick={() => setShowRating(true)}>
          {t('sidebar.ratingBtn')}
        </button>
        <div className="sidebar-col" style={{ marginTop: 6 }}>
          <span>{t('sidebar.safetyLevel.label')}</span>
          <select
            className="sidebar-select"
            value={(get('safety_level', 'off') as string) === 'warn' ? 'off' : get('safety_level', 'off')}
            onChange={e => set('safety_level', e.target.value)}
          >
            <option value="off">{t('sidebar.safetyLevel.off')}</option>
            <option value="mask">{t('sidebar.safetyLevel.mask')}</option>
          </select>
        </div>
      </div>

      <div className="sidebar-section">
        <h4>{t('sidebar.section.chatSettings')}</h4>
        <div className="sidebar-row">
          <span>{t('sidebar.aiTtsEnabled')}</span>
          <Toggle checked={get('tts_enabled', true)} onChange={v => set('tts_enabled', v)} />
        </div>
        <div className="sidebar-row">
          <span>{t('sidebar.userTtsEnabled')}</span>
          <Toggle checked={get('tts_human_enabled', false)} onChange={v => set('tts_human_enabled', v)} />
        </div>
        <div className="sidebar-row">
          <span>{t('sidebar.forceNext')}</span>
          <Toggle checked={forceEnabled} onChange={handleForceEnabled} />
        </div>
        {forceEnabled && (
          <div className="sidebar-col">
            <span>{t('sidebar.forceTag')}</span>
            <select
              className="sidebar-select"
              value={forceTag}
              onChange={e => handleForceTag(e.target.value)}
            >
              {FORCE_RATING_TAGS.map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
        )}
        <div className="sidebar-row">
          <span>{t('sidebar.voteForceApprove')}</span>
          <Toggle checked={get('vote_force_approve', false)} onChange={v => set('vote_force_approve', v)} />
        </div>
      </div>


      <div className="sidebar-section">
        <div className={`vram-status ${vramLocked ? 'vram-locked' : 'vram-free'}`}>
          {vramLocked ? t('sidebar.vram.locked') : t('sidebar.vram.free')}
        </div>
      </div>

      {showRating && (
        <RatingDialog
          sexualKey={sexualKey}
          violenceKey={violenceKey}
          onChangeSexual={handleSexual}
          onChangeViolence={handleViolence}
          onClose={() => setShowRating(false)}
        />
      )}
    </aside>
  )
}
