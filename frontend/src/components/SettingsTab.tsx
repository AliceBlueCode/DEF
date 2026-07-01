import { useState, useEffect, useCallback } from 'react'
import ApiKeyDialog from './ApiKeyDialog'

type BackendInfo = {
  backends: string[]
  labels: Record<string, string>
  default: string
}

type Props = {
  llmBackend: string
  onLlmBackendChange: (b: string) => void
  t2iBackend: string
  onT2iBackendChange: (b: string) => void
  ttsBackend: string
  onTtsBackendChange: (b: string) => void
  candidateCount: number
  onCandidateCountChange: (n: number) => void
}

const LANG_OPTIONS = [
  { value: 'ja', label: '日本語' },
  { value: 'en', label: 'English' },
  { value: 'zh', label: '中文' },
  { value: 'ko', label: '한국어' },
  { value: 'es', label: 'Español' },
  { value: 'fr', label: 'Français' },
  { value: 'de', label: 'Deutsch' },
]

const T2I_TRIGGER_OPTIONS = [
  { value: 'end',      label: '各サイクル末（演出先行型）' },
  { value: 'start',    label: '各サイクル頭（状況先行型）' },
  { value: 'manual',   label: '手動オンデマンド' },
  { value: 'interval', label: '時間インターバル自動' },
]

const T2I_FORMAT_OPTIONS = [
  { value: 'danbooru', label: 'Danbooru タグ形式' },
  { value: 'natural',  label: '自然言語（Flux 等）' },
  { value: 'e621',     label: 'e621 タグ形式' },
  { value: 'other',    label: 'その他' },
]

const SIZE_PRESETS = [
  { label: '512×512',   w: 512,  h: 512 },
  { label: '768×512',   w: 768,  h: 512 },
  { label: '1024×576',  w: 1024, h: 576 },
  { label: '1216×832',  w: 1216, h: 832 },
  { label: '832×1216',  w: 832,  h: 1216 },
  { label: '1024×1024', w: 1024, h: 1024 },
]

function sizeLabel(w: number, h: number) {
  const p = SIZE_PRESETS.find(p => p.w === w && p.h === h)
  return p ? p.label : `${w}×${h}`
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="toggle-switch">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} />
      <span className="toggle-track"><span className="toggle-thumb" /></span>
    </label>
  )
}

export default function SettingsTab({
  llmBackend, onLlmBackendChange,
  t2iBackend, onT2iBackendChange,
  ttsBackend, onTtsBackendChange,
  candidateCount, onCandidateCountChange,
}: Props) {
  const [llmBackends, setLlmBackends] = useState<BackendInfo | null>(null)
  const [t2iBackends, setT2iBackends] = useState<BackendInfo | null>(null)
  const [showApiKeyDialog, setShowApiKeyDialog] = useState(false)
  const [appSettings, setAppSettings] = useState<Record<string, unknown>>({})

  useEffect(() => {
    fetch('/api/settings/backends')
      .then(r => r.json())
      .then(data => {
        if (data.llm) setLlmBackends(data.llm)
        if (data.t2i) setT2iBackends(data.t2i)
      })
    fetch('/api/settings/')
      .then(r => r.json())
      .then(data => setAppSettings(data.settings || {}))
  }, [])

  const get = useCallback(<T,>(key: string, def: T): T => {
    return (key in appSettings ? appSettings[key] : def) as T
  }, [appSettings])

  const set = useCallback(async (key: string, value: unknown) => {
    setAppSettings(prev => ({ ...prev, [key]: value }))
    fetch('/api/settings/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: { [key]: value } }),
    })
  }, [])

  const setSize = (widthKey: string, heightKey: string, w: number, h: number) => {
    setAppSettings(prev => ({ ...prev, [widthKey]: w, [heightKey]: h }))
    fetch('/api/settings/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings: { [widthKey]: w, [heightKey]: h } }),
    })
  }

  return (
    <div className="tab-content settings-tab">
      <h2>設定</h2>

      {/* ── バックエンド ── */}
      <div className="settings-section">
        <h3>LLM バックエンド</h3>
        {llmBackends && (
          <select value={llmBackend} onChange={e => onLlmBackendChange(e.target.value)}>
            {llmBackends.backends.map(b => (
              <option key={b} value={b}>{llmBackends.labels[b] || b}</option>
            ))}
          </select>
        )}
      </div>

      <div className="settings-section">
        <h3>TTS バックエンド</h3>
        <select value={ttsBackend} onChange={e => onTtsBackendChange(e.target.value)}>
          <option value="voicevox">VOICEVOX (ローカル)</option>
          <option value="kokoro">Kokoro TTS (ローカル)</option>
          <option value="irodori">Irodori-TTS (ローカル)</option>
          <option value="gemini">Gemini TTS API</option>
        </select>
      </div>

      <div className="settings-section">
        <h3>T2I バックエンド</h3>
        {t2iBackends && (
          <select value={t2iBackend} onChange={e => onT2iBackendChange(e.target.value)}>
            {t2iBackends.backends.map(b => (
              <option key={b} value={b}>{t2iBackends.labels[b] || b}</option>
            ))}
          </select>
        )}
      </div>

      <div className="settings-section">
        <h3>APIキー</h3>
        <button className="api-key-open-btn" onClick={() => setShowApiKeyDialog(true)}>
          🔑 APIキー管理を開く
        </button>
      </div>

      <div className="settings-divider" />

      {/* ── 基本設定 ── */}
      <div className="settings-section">
        <h3>基本設定</h3>
        <div className="settings-row">
          <label>言語</label>
          <select value={get('user_language', 'ja')} onChange={e => set('user_language', e.target.value)}>
            {LANG_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
      </div>

      <div className="settings-divider" />

      {/* ── チャット設定 ── */}
      <div className="settings-section">
        <h3>チャット設定</h3>
        <div className="settings-row">
          <label>キャラクター挨拶</label>
          <Toggle checked={get('character_greeting', true)} onChange={v => set('character_greeting', v)} />
        </div>
        <div className="settings-row">
          <label>Undo 最大件数</label>
          <input
            type="number" min={1} max={10}
            className="settings-number"
            value={get('undo_max_history', 5)}
            onChange={e => set('undo_max_history', Number(e.target.value))}
          />
        </div>
      </div>

      <div className="settings-divider" />

      {/* ── T2I設定 ── */}
      <div className="settings-section">
        <h3>T2I 設定</h3>
        <div className="settings-row">
          <label>T2I トリガー</label>
          <select value={get('t2i_trigger_mode', 'end')} onChange={e => set('t2i_trigger_mode', e.target.value)}>
            {T2I_TRIGGER_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div className="settings-row">
          <label>プロンプト記法</label>
          <select value={get('t2i_prompt_format', 'danbooru')} onChange={e => set('t2i_prompt_format', e.target.value)}>
            {T2I_FORMAT_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div className="settings-row">
          <label>感情タグ</label>
          <Toggle checked={get('emotion_tag_enabled', true)} onChange={v => set('emotion_tag_enabled', v)} />
        </div>
      </div>

      <div className="settings-divider" />

      {/* ── セッション設定 ── */}
      <div className="settings-section">
        <h3>セッション設定</h3>
        <div className="settings-row">
          <label>アクション数 / ターン</label>
          <div className="count-buttons">
            {[1,2,3,4,5].map(n => (
              <button key={n} className={`count-btn ${get('session_actions_per_turn', 3) === n ? 'active' : ''}`}
                onClick={() => set('session_actions_per_turn', n)}>{n}</button>
            ))}
          </div>
        </div>
        <div className="settings-row">
          <label>リピートペナルティ</label>
          <input
            type="number" min={0} max={10}
            className="settings-number"
            value={get('session_repeat_penalty_count', 3)}
            onChange={e => set('session_repeat_penalty_count', Number(e.target.value))}
          />
        </div>
      </div>

      <div className="settings-divider" />

      {/* ── エピソード設定 ── */}
      <div className="settings-section">
        <h3>エピソード設定</h3>
        <div className="settings-row">
          <label>AI 候補数</label>
          <div className="count-buttons">
            {[1,2,3,4,5].map(n => (
              <button key={n} className={`count-btn ${candidateCount === n ? 'active' : ''}`}
                onClick={() => onCandidateCountChange(n)}>{n}</button>
            ))}
          </div>
        </div>
        <div className="settings-row">
          <label>挿絵サイズ</label>
          <select
            value={sizeLabel(get('episode_t2i_width', 1216), get('episode_t2i_height', 832))}
            onChange={e => {
              const p = SIZE_PRESETS.find(p => p.label === e.target.value)
              if (p) setSize('episode_t2i_width', 'episode_t2i_height', p.w, p.h)
            }}
          >
            {SIZE_PRESETS.map(p => <option key={p.label} value={p.label}>{p.label}</option>)}
          </select>
        </div>
      </div>

      <div className="settings-divider" />

      <div className="settings-section">
        <p className="version-info">DEF(kari) v1.0.0</p>
      </div>

      {showApiKeyDialog && <ApiKeyDialog onClose={() => setShowApiKeyDialog(false)} />}
    </div>
  )
}
