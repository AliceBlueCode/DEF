import { useState, useEffect, useCallback } from 'react'
import ApiKeyDialog from './ApiKeyDialog'
import BackendDirDialog from './BackendDirDialog'
import ModelProfileDialog from './ModelProfileDialog'
import CivitaiDialog from './CivitaiDialog'
import HuggingFaceDialog from './HuggingFaceDialog'
import Toggle from './Toggle'

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
  theme: 'dark' | 'light'
  onThemeToggle: () => void
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

const C2_OPTIONS = [
  { value: 'none',    label: '利用しない' },
  { value: 'argos',   label: 'Argos Translate (オフライン)' },
  { value: 'library', label: 'Google翻訳 (無料)' },
  { value: 'deepl',   label: 'DeepL API' },
  { value: 'llm',     label: 'LLM翻訳' },
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
  { label: '512×768',   w: 512,  h: 768 },
  { label: '768×512',   w: 768,  h: 512 },
  { label: '768×1024',  w: 768,  h: 1024 },
  { label: '1024×576',  w: 1024, h: 576 },
  { label: '1216×832',  w: 1216, h: 832 },
  { label: '832×1216',  w: 832,  h: 1216 },
  { label: '1024×1024', w: 1024, h: 1024 },
]

function sizeLabel(w: number, h: number) {
  const p = SIZE_PRESETS.find(p => p.w === w && p.h === h)
  return p ? p.label : `${w}×${h}`
}

function llmModelKey(backend: string): string {
  return backend === 'textgen_webui' ? 'tgw_autoload_model' : `llm_ext_model_${backend}`
}

function t2iModelKey(backend: string): string {
  return `t2i_model_${backend}`
}


export default function SettingsTab({
  llmBackend, onLlmBackendChange,
  t2iBackend, onT2iBackendChange,
  ttsBackend, onTtsBackendChange,
  candidateCount, onCandidateCountChange,
  theme, onThemeToggle,
}: Props) {
  const [llmBackends, setLlmBackends] = useState<BackendInfo | null>(null)
  const [t2iBackends, setT2iBackends] = useState<BackendInfo | null>(null)
  const [llmModels, setLlmModels] = useState<string[]>([])
  const [t2iModels, setT2iModels] = useState<string[]>([])
  const [t2iWorkflows, setT2iWorkflows] = useState<string[]>([])
  const [civitaiModels, setCivitaiModels] = useState<{label: string; model_air: string}[]>([])
  const [showApiKeyDialog, setShowApiKeyDialog] = useState(false)
  const [showBackendDirDialog, setShowBackendDirDialog] = useState(false)
  const [showModelProfile, setShowModelProfile] = useState(false)
  const [showCivitai, setShowCivitai] = useState(false)
  const [showHf, setShowHf] = useState(false)
  const [appSettings, setAppSettings] = useState<Record<string, unknown>>({})
  const [appVersion, setAppVersion] = useState('')
  const [llmLaunchMsg, setLlmLaunchMsg] = useState('')
  const [ttsLaunchMsg, setTtsLaunchMsg] = useState('')
  const [t2iLaunchMsg, setT2iLaunchMsg] = useState('')
  const [llmDebug, setLlmDebug] = useState(false)
  const [ttsDebug, setTtsDebug] = useState(false)
  const [t2iDebug, setT2iDebug] = useState(false)
  const [t2iQualityTags, setT2iQualityTags] = useState('')
  const [t2iNegPrompt, setT2iNegPrompt] = useState('')
  const [t2iQualitySaveMsg, setT2iQualitySaveMsg] = useState('')

  useEffect(() => {
    fetch('/api/settings/version')
      .then(r => r.json())
      .then(data => setAppVersion(data.version || ''))
      .catch(() => {})
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

  const t2iMKey = t2iModelKey(t2iBackend)

  const fetchLlmModels = useCallback((backend: string) => {
    if (!backend) return
    setLlmModels([])
    fetch(`/api/settings/llm-models?backend=${encodeURIComponent(backend)}`)
      .then(r => r.json())
      .then(data => setLlmModels(data.models || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetchLlmModels(llmBackend)
  }, [llmBackend])

  useEffect(() => {
    const model = (appSettings[t2iMKey] as string) || ''
    if (!model) return
    fetch(`/api/settings/t2i-quality?model=${encodeURIComponent(model)}`)
      .then(r => r.json())
      .then(data => {
        setT2iQualityTags(data.quality_tags ?? '')
        setT2iNegPrompt(data.negative_prompt ?? '')
      })
      .catch(() => {})
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appSettings[t2iMKey], t2iBackend])

  useEffect(() => {
    if (t2iBackend !== 'civitai') return
    fetch('/api/settings/civitai-models')
      .then(r => r.json())
      .then(data => setCivitaiModels(data.models || []))
  }, [t2iBackend, showCivitai])

  useEffect(() => {
    if (!t2iBackend) return
    setT2iModels([])
    setT2iWorkflows([])
    fetch(`/api/settings/t2i-models?backend=${encodeURIComponent(t2iBackend)}`)
      .then(r => r.json())
      .then(data => {
        setT2iModels(data.models || [])
        setT2iWorkflows(data.workflows || [])
      })
      .catch(() => {})
  }, [t2iBackend])

  const get = useCallback(<T,>(key: string, def: T): T => {
    return (key in appSettings ? appSettings[key] : def) as T
  }, [appSettings])

  const LOCAL_BACKENDS: Record<string, string[]> = {
    llm: ['textgen_webui', 'ollama'],
    tts: ['voicevox', 'kokoro', 'irodori'],
    t2i: ['a1111', 'comfyui'],
  }

  const stopBackend = (id: string) => {
    if (!id) return
    fetch(`/api/settings/stop-backend?id=${id}`).catch(() => {})
  }

  const launchBackend = async (id: string, setMsg: (m: string) => void, afterLaunch?: () => void) => {
    setMsg('起動確認中...')
    try {
      const res = await fetch(`/api/settings/launch-backend?id=${id}`)
      const data = await res.json()
      if (data.status === 'already_running') { setMsg('✓ 起動中'); afterLaunch?.() }
      else if (data.status === 'launched') { setMsg('✓ 起動しました'); afterLaunch?.() }
      else if (data.status === 'error') setMsg(`✗ ${data.message || 'エラー'}`)
      else setMsg('')
    } catch { setMsg('✗ 接続エラー') }
    setTimeout(() => setMsg(''), 5000)
  }

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

  const modelKey = llmModelKey(llmBackend)

  return (
    <div className="tab-content settings-tab">
      <h2>設定</h2>

      {/* ── LLM バックエンド ── */}
      <div className="settings-section">
        <h3>
          LLM バックエンド
          <label className="debug-mode-label">
            <input type="checkbox" checked={llmDebug} onChange={e => setLlmDebug(e.target.checked)} />
            多重起動
          </label>
        </h3>
        {llmBackends && (
          <select value={llmBackend} onChange={async e => {
            const b = e.target.value
            if (!llmDebug && LOCAL_BACKENDS.llm.includes(llmBackend) && llmBackend !== b) stopBackend(llmBackend)
            onLlmBackendChange(b)
            if (LOCAL_BACKENDS.llm.includes(b)) launchBackend(b, setLlmLaunchMsg, () => fetchLlmModels(b))
            else setLlmLaunchMsg('')
          }}>
            {llmBackends.backends.map(b => (
              <option key={b} value={b}>{llmBackends.labels[b] || b}</option>
            ))}
          </select>
        )}
        {llmLaunchMsg && <div className="tts-launch-msg">{llmLaunchMsg}</div>}
        <div className="settings-row" style={{ marginTop: 8 }}>
          <label>モデル</label>
          <div style={{ display: 'flex', gap: 6, flex: 1 }}>
            {llmModels.length > 0 ? (
              <select
                style={{ flex: 1 }}
                value={get(modelKey, llmModels[0])}
                onChange={e => {
                  const m = e.target.value
                  set(modelKey, m)
                  if (llmBackend === 'textgen_webui' && m) {
                    setLlmLaunchMsg('⏳ モデルをロード中...')
                    fetch(`/api/settings/load-llm-model?backend=textgen_webui&model=${encodeURIComponent(m)}`)
                      .then(r => r.json())
                      .then(data => {
                        if (data.status === 'ok') setLlmLaunchMsg('✅ モデルロード完了')
                        else setLlmLaunchMsg(`⚠ ${data.message || data.status}`)
                      })
                      .catch(e => setLlmLaunchMsg(`⚠ ${e}`))
                  }
                }}
              >
                {llmModels.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            ) : (
              <span style={{ flex: 1, fontSize: '0.82em', color: '#888', alignSelf: 'center' }}>
                (バックエンド起動後に取得)
              </span>
            )}
            <button className="turn-btn" onClick={() => fetchLlmModels(llmBackend)} title="モデル一覧を更新">🔄</button>
          </div>
        </div>
        {get(modelKey, llmModels[0] ?? '') && (
          <button className="profile-open-btn" style={{ marginTop: 8 }} onClick={() => setShowModelProfile(true)}>
            📋 モデルプロファイル編集
          </button>
        )}
      </div>

      <div className="settings-section">
        <h3>
          TTS バックエンド
          <label className="debug-mode-label">
            <input type="checkbox" checked={ttsDebug} onChange={e => setTtsDebug(e.target.checked)} />
            多重起動
          </label>
        </h3>
        <select value={ttsBackend} onChange={async e => {
          const b = e.target.value
          if (!ttsDebug && LOCAL_BACKENDS.tts.includes(ttsBackend) && ttsBackend !== b) stopBackend(ttsBackend)
          onTtsBackendChange(b)
          if (LOCAL_BACKENDS.tts.includes(b)) launchBackend(b, setTtsLaunchMsg)
          else setTtsLaunchMsg('')
        }}>
          <option value="voicevox">VOICEVOX (ローカル)</option>
          <option value="kokoro">Kokoro TTS (ローカル)</option>
          <option value="irodori">Irodori-TTS (ローカル)</option>
          <option value="gemini">Gemini TTS API</option>
        </select>
        {ttsLaunchMsg && <div className="tts-launch-msg">{ttsLaunchMsg}</div>}
      </div>

      {/* ── T2I バックエンド ── */}
      <div className="settings-section">
        <h3>
          T2I バックエンド
          <label className="debug-mode-label">
            <input type="checkbox" checked={t2iDebug} onChange={e => setT2iDebug(e.target.checked)} />
            多重起動
          </label>
        </h3>
        {t2iBackends && (
          <select value={t2iBackend} onChange={async e => {
            const b = e.target.value
            if (!t2iDebug && LOCAL_BACKENDS.t2i.includes(t2iBackend) && t2iBackend !== b) stopBackend(t2iBackend)
            onT2iBackendChange(b)
            if (LOCAL_BACKENDS.t2i.includes(b)) launchBackend(b, setT2iLaunchMsg)
            else setT2iLaunchMsg('')
          }}>
            {t2iBackends.backends.map(b => (
              <option key={b} value={b}>{t2iBackends.labels[b] || b}</option>
            ))}
          </select>
        )}
        {t2iLaunchMsg && <div className="tts-launch-msg">{t2iLaunchMsg}</div>}
        {t2iModels.length > 0 && (
          <div className="settings-row" style={{ marginTop: 8 }}>
            <label>モデル</label>
            <select
              value={get(t2iMKey, t2iModels[0])}
              onChange={e => set(t2iMKey, e.target.value)}
            >
              {t2iModels.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
        )}
        {t2iWorkflows.length > 0 && (
          <div className="settings-row" style={{ marginTop: 8 }}>
            <label>ワークフロー</label>
            <select
              value={get('comfyui_workflow', t2iWorkflows[0])}
              onChange={e => set('comfyui_workflow', e.target.value)}
            >
              {t2iWorkflows.map(w => <option key={w} value={w}>{w}</option>)}
            </select>
          </div>
        )}
        {t2iBackend === 'civitai' && civitaiModels.length > 0 && (
          <div className="settings-row" style={{ marginTop: 8 }}>
            <label>モデル</label>
            <select
              value={get(t2iMKey, civitaiModels[0]?.model_air ?? '') as string}
              onChange={e => set(t2iMKey, e.target.value)}
            >
              {civitaiModels.map(m => (
                <option key={m.model_air} value={m.model_air}>
                  {m.label !== m.model_air ? m.label : m.model_air}
                </option>
              ))}
            </select>
          </div>
        )}
        {t2iBackend === 'civitai' && (
          <button className="profile-open-btn" style={{ marginTop: 8 }} onClick={() => setShowCivitai(true)}>
            🎨 Civitai モデル管理
          </button>
        )}
        {t2iBackend === 'huggingface' && (
          <>
            {get(t2iMKey, '') && (
              <div className="settings-row" style={{ marginTop: 4 }}>
                <label>選択中</label>
                <span style={{ fontSize: '0.82em', fontFamily: 'monospace', color: '#a8d8f0' }}>
                  {get(t2iMKey, '') as string}
                </span>
              </div>
            )}
            <button className="profile-open-btn" style={{ marginTop: 8 }} onClick={() => setShowHf(true)}>
              🤗 HuggingFace モデル管理
            </button>
          </>
        )}
        {get(t2iMKey, '') && (
          <div className="t2i-quality-section">
            <div className="settings-row" style={{ marginTop: 12 }}>
              <label>品質タグ</label>
              <input
                type="text"
                className="settings-text-input"
                value={t2iQualityTags}
                onChange={e => setT2iQualityTags(e.target.value)}
                placeholder="masterpiece, best quality"
              />
            </div>
            <div className="settings-row" style={{ marginTop: 6 }}>
              <label>ネガプロンプト</label>
              <input
                type="text"
                className="settings-text-input"
                value={t2iNegPrompt}
                onChange={e => setT2iNegPrompt(e.target.value)}
                placeholder="lowres, bad anatomy, worst quality"
              />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
              <button className="profile-open-btn" onClick={async () => {
                const model = get(t2iMKey, '') as string
                if (!model) return
                await fetch('/api/settings/t2i-quality', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ model, quality_tags: t2iQualityTags, negative_prompt: t2iNegPrompt }),
                })
                setT2iQualitySaveMsg('✓ 保存しました')
                setTimeout(() => setT2iQualitySaveMsg(''), 3000)
              }}>
                💾 保存
              </button>
              {t2iQualitySaveMsg && <span className="tts-launch-msg">{t2iQualitySaveMsg}</span>}
            </div>
          </div>
        )}
      </div>

      <div className="settings-section">
        <h3>バックエンド / APIキー</h3>
        <div className="settings-btn-row">
          <button className="api-key-open-btn" onClick={() => setShowBackendDirDialog(true)}>
            📁 バックエンド設定
          </button>
          <button className="api-key-open-btn" onClick={() => setShowApiKeyDialog(true)}>
            🔑 APIキー管理
          </button>
        </div>
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
          <label>感情タグ自動挿入</label>
          <Toggle checked={get('emotion_tag_enabled', true)} onChange={v => set('emotion_tag_enabled', v)} />
        </div>
        <div className="settings-row">
          <label>翻訳方式 (C2)</label>
          <select value={get('c2_method', 'none')} onChange={e => set('c2_method', e.target.value)}>
            {C2_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div className="settings-row">
          <label>チャット挿絵サイズ</label>
          <select
            value={sizeLabel(get('t2i_width', 512), get('t2i_height', 768))}
            onChange={e => {
              const p = SIZE_PRESETS.find(p => p.label === e.target.value)
              if (p) setSize('t2i_width', 't2i_height', p.w, p.h)
            }}
          >
            {SIZE_PRESETS.map(p => <option key={p.label} value={p.label}>{p.label}</option>)}
          </select>
        </div>
      </div>

      <div className="settings-divider" />

      {/* ── チャット設定 ── */}
      <div className="settings-section">
        <h3>チャット設定</h3>
        <div className="settings-row">
          <label>キャラ挨拶</label>
          <Toggle checked={get('character_greeting', true)} onChange={v => set('character_greeting', v)} />
        </div>
        <div className="settings-row">
          <label>Undo 件数</label>
          <input
            type="number" min={1} max={10}
            className="settings-number"
            value={get('undo_max_history', 5)}
            onChange={e => set('undo_max_history', Number(e.target.value))}
          />
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
        <div className="settings-row">
          <label>セッション挿絵サイズ</label>
          <select
            value={sizeLabel(get('session_t2i_width', 512), get('session_t2i_height', 512))}
            onChange={e => {
              const p = SIZE_PRESETS.find(p => p.label === e.target.value)
              if (p) setSize('session_t2i_width', 'session_t2i_height', p.w, p.h)
            }}
          >
            {SIZE_PRESETS.map(p => <option key={p.label} value={p.label}>{p.label}</option>)}
          </select>
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
        <h3>表示設定</h3>
        <div className="settings-row">
          <label>ダークモード</label>
          <Toggle checked={theme === 'dark'} onChange={onThemeToggle} />
        </div>
      </div>

      <div className="settings-divider" />

      <div className="settings-section">
        <p className="version-info">{appVersion ? `DEF(kari) v${appVersion}` : 'DEF(kari)'}</p>
      </div>

      {showApiKeyDialog && <ApiKeyDialog onClose={() => setShowApiKeyDialog(false)} />}
      {showBackendDirDialog && <BackendDirDialog onClose={() => setShowBackendDirDialog(false)} />}
      {showModelProfile && (
        <ModelProfileDialog
          model={get(modelKey, llmModels[0] ?? '') as string}
          onClose={() => setShowModelProfile(false)}
        />
      )}
      {showCivitai && (
        <CivitaiDialog
          currentModel={get(t2iMKey, '') as string}
          onSelect={id => set(t2iMKey, id)}
          onClose={() => setShowCivitai(false)}
        />
      )}
      {showHf && (
        <HuggingFaceDialog
          currentModel={get(t2iMKey, '') as string}
          onSelect={id => set(t2iMKey, id)}
          onClose={() => setShowHf(false)}
        />
      )}
    </div>
  )
}
