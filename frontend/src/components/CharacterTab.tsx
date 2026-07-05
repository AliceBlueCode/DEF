import { useState, useEffect, useRef } from 'react'
import { useT } from '../i18n'

type Character = { id: string; name: string }

type Props = {
  characters: Character[]
  selectedChar: string
  onCharChange: (id: string) => void
  onHistoryCleared: () => void
  ttsBackend: string
}

type CharDetail = {
  name: string
  persona_description?: string
  speech_style?: string
  appearance_tags?: string
  image_name_tags?: string
  [key: string]: unknown
}

type VVSpeaker = { id: number; label: string }

export default function CharacterTab({ characters, selectedChar, onCharChange, onHistoryCleared, ttsBackend }: Props) {
  const t = useT()
  const [char, setChar] = useState<CharDetail | null>(null)
  const [clearing, setClearing] = useState(false)

  // 1. 音声設定
  const [vvSpeakers, setVvSpeakers] = useState<VVSpeaker[]>([])
  const [vvRunning, setVvRunning] = useState(false)
  const [iroVoices, setIroVoices] = useState<string[]>([])
  const [iroRunning, setIroRunning] = useState(false)
  const [selectedVvSpeaker, setSelectedVvSpeaker] = useState<number>(2)
  const [selectedIroVoice, setSelectedIroVoice] = useState('')
  const [savingVoice, setSavingVoice] = useState(false)
  const [voiceSaveMsg, setVoiceSaveMsg] = useState('')
  const [testAudioUrl, setTestAudioUrl] = useState('')
  const [testingVoice, setTestingVoice] = useState(false)

  // 2. キャラ画像
  const [imgRefresh, setImgRefresh] = useState(0)
  const [generatingIcon, setGeneratingIcon] = useState(false)
  const [generatingStanding, setGeneratingStanding] = useState(false)
  const [imgMsg, setImgMsg] = useState('')
  const iconInputRef = useRef<HTMLInputElement>(null)
  const standingInputRef = useRef<HTMLInputElement>(null)

  // 3. プロファイルJSON編集
  const [rawProfile, setRawProfile] = useState('')
  const [profileMsg, setProfileMsg] = useState('')
  const [savingProfile, setSavingProfile] = useState(false)
  const [imageColor, setImageColor] = useState('#2a2a2a')
  const [, setColorSaving] = useState(false)

  // キャラ詳細フェッチ
  useEffect(() => {
    if (!selectedChar) return
    fetch(`/api/characters/${selectedChar}`)
      .then(r => r.json())
      .then(data => setChar(data.character || null))
  }, [selectedChar])

  // 音声設定フェッチ（バックエンド問わず両方確認）
  useEffect(() => {
    fetch('/api/tts/speakers')
      .then(r => r.json())
      .then(data => {
        setVvRunning(data.running ?? false)
        setVvSpeakers(data.speakers ?? [])
      })
      .catch(() => {})
    fetch('/api/tts/voices')
      .then(r => r.json())
      .then(data => {
        setIroRunning(data.running ?? false)
        setIroVoices(data.voices ?? [])
      })
      .catch(() => {})
  }, [])

  // キャラ切替時に現在の音声設定を読み込む
  useEffect(() => {
    if (!selectedChar) return
    fetch(`/api/characters/${selectedChar}/raw-profile`)
      .then(r => r.json())
      .then(data => {
        const profile = data.profile || {}
        const dmc = profile.default_model_config || {}
        setSelectedVvSpeaker(dmc.voicevox_speaker_id ?? 2)
        setSelectedIroVoice(dmc.irodori_speaker_id ?? '')
        setImageColor(profile.image_color || '#2a2a2a')
        setRawProfile(JSON.stringify(profile, null, 2))
      })
      .catch(() => {})
    setVoiceSaveMsg('')
    setImgMsg('')
    setProfileMsg('')
    setTestAudioUrl('')
  }, [selectedChar])

  const saveImageColor = async (color: string) => {
    if (!selectedChar) return
    setColorSaving(true)
    try {
      const res = await fetch(`/api/characters/${selectedChar}/raw-profile`)
      const data = await res.json()
      const profile = { ...(data.profile || {}), image_color: color }
      await fetch(`/api/characters/${selectedChar}/raw-profile`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile }),
      })
      setRawProfile(JSON.stringify(profile, null, 2))
    } finally {
      setColorSaving(false)
    }
  }

  const clearHistory = async () => {
    if (!selectedChar) return
    if (!window.confirm(t('char.history.deleteConfirm'))) return
    setClearing(true)
    try {
      await fetch(`/api/chat/history/${selectedChar}`, { method: 'DELETE' })
      onHistoryCleared()
    } finally {
      setClearing(false)
    }
  }

  const saveVoiceSettings = async (backend: string, speakerId: number | string) => {
    if (!selectedChar) return
    setSavingVoice(true)
    setVoiceSaveMsg('')
    try {
      const r = await fetch(`/api/characters/${selectedChar}/voice-settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend, speaker_id: speakerId }),
      })
      const data = await r.json()
      setVoiceSaveMsg(data.status === 'ok' ? t('char.msg.voiceSaved') : (data.error || t('char.msg.voiceError')))
    } finally {
      setSavingVoice(false)
    }
  }

  const testVoice = async (backend: string, speakerId: number | string) => {
    setTestingVoice(true)
    if (testAudioUrl) URL.revokeObjectURL(testAudioUrl)
    setTestAudioUrl('')
    try {
      const r = await fetch('/api/tts/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ backend, speaker_id: speakerId, text: 'あめんぼ、あかいな、あいうえお' }),
      })
      if (r.ok) {
        const blob = await r.blob()
        setTestAudioUrl(URL.createObjectURL(blob))
      }
    } finally {
      setTestingVoice(false)
    }
  }

  const uploadImage = async (kind: 'icon' | 'standing', file: File) => {
    const form = new FormData()
    form.append('file', file)
    setImgMsg('')
    const r = await fetch(`/api/characters/${selectedChar}/${kind}`, { method: 'POST', body: form })
    const data = await r.json()
    if (data.status === 'ok') {
      setImgRefresh(n => n + 1)
      setImgMsg(kind === 'icon' ? t('char.msg.iconSaved') : t('char.msg.standingSaved'))
    } else {
      setImgMsg(data.error || t('char.msg.uploadFailed'))
    }
  }

  const generateImage = async (kind: 'icon' | 'standing') => {
    if (kind === 'icon') setGeneratingIcon(true)
    else setGeneratingStanding(true)
    setImgMsg('')
    try {
      const r = await fetch(`/api/characters/${selectedChar}/${kind}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      const data = await r.json()
      if (data.status === 'ok') {
        setImgRefresh(n => n + 1)
        setImgMsg(kind === 'icon' ? t('char.msg.iconGenerated') : t('char.msg.standingGenerated'))
      } else {
        setImgMsg(data.error || t('char.msg.generateFailed'))
      }
    } finally {
      if (kind === 'icon') setGeneratingIcon(false)
      else setGeneratingStanding(false)
    }
  }

  const saveRawProfile = async () => {
    if (!selectedChar) return
    setSavingProfile(true)
    setProfileMsg('')
    let parsed: unknown
    try {
      parsed = JSON.parse(rawProfile)
    } catch {
      setProfileMsg(t('char.msg.jsonParseError'))
      setSavingProfile(false)
      return
    }
    try {
      const r = await fetch(`/api/characters/${selectedChar}/raw-profile`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile: parsed }),
      })
      const data = await r.json()
      setProfileMsg(data.status === 'ok' ? t('char.msg.voiceSaved') : (data.error || t('char.msg.voiceError')))
      if (data.status === 'ok') {
        // キャラ名等が変わった場合に再取得
        fetch(`/api/characters/${selectedChar}`)
          .then(r => r.json())
          .then(d => setChar(d.character || null))
      }
    } finally {
      setSavingProfile(false)
    }
  }

  const showVv = vvRunning && (ttsBackend === 'voicevox' || !ttsBackend)
  const showIro = iroRunning && ttsBackend === 'irodori'

  return (
    <div className="tab-content character-tab">
      <div className="chat-char-bar">
        <select value={selectedChar} onChange={e => onCharChange(e.target.value)}>
          {characters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.82em', color: '#aaa', flexShrink: 0 }}>
          {t('char.imageColor.label')}
          <input
            type="color"
            value={imageColor}
            onChange={e => setImageColor(e.target.value)}
            onBlur={e => saveImageColor(e.target.value)}
            style={{ width: 32, height: 24, border: 'none', cursor: 'pointer', borderRadius: 4, padding: 2 }}
          />
        </label>
      </div>

      {char && <>
      <div className="char-header">
        <div className="char-images">
          <div className="char-icon-large">
            <img src={`/api/characters/${selectedChar}/icon?r=${imgRefresh}`} alt={char.name} />
          </div>
          <div className="char-standing">
            <img
              src={`/api/characters/${selectedChar}/standing?r=${imgRefresh}`}
              alt={char.name}
              onError={e => (e.currentTarget.style.display = 'none')}
            />
          </div>
        </div>
        <h2>{char.name}</h2>
      </div>

      <div className="char-profile">
        {char.persona_description && (
          <div className="profile-section">
            <h3>{t('char.profile.personality')}</h3>
            <p>{char.persona_description as string}</p>
          </div>
        )}
        {char.speech_style && (
          <div className="profile-section">
            <h3>{t('char.profile.speechStyle')}</h3>
            <p>{char.speech_style as string}</p>
          </div>
        )}
        {char.appearance_tags && (
          <div className="profile-section">
            <h3>{t('char.profile.appearanceTags')}</h3>
            <p className="appearance-tags">{char.appearance_tags as string}</p>
          </div>
        )}
        {char.image_name_tags && (
          <div className="profile-section">
            <h3>{t('char.profile.nameTags')}</h3>
            <p className="appearance-tags">{char.image_name_tags as string}</p>
          </div>
        )}
      </div>

      {/* ===== キャラ画像 + 音声設定 ===== */}
      <div className="char-section">
        <h3 className="char-section-title">{t('char.section.imageVoice.title')}</h3>
        <div className="char-img-edit-row">
          <div className="char-img-edit-col">
            <p className="char-img-label">{t('char.icon.label')}</p>
            <img
              className="char-img-preview"
              src={`/api/characters/${selectedChar}/icon?r=${imgRefresh}`}
              alt="icon"
              onError={e => (e.currentTarget.style.display = 'none')}
            />
            <input
              ref={iconInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              style={{ display: 'none' }}
              onChange={e => e.target.files?.[0] && uploadImage('icon', e.target.files[0])}
            />
            <button className="char-btn" onClick={() => iconInputRef.current?.click()}>
              {t('char.uploadBtn')}
            </button>
            <button
              className="char-btn"
              onClick={() => generateImage('icon')}
              disabled={generatingIcon}
            >
              {generatingIcon ? t('char.generateBtn.loading') : t('char.generateBtn')}
            </button>
          </div>
          <div className="char-img-edit-col">
            <p className="char-img-label">{t('char.standing.label')}</p>
            <img
              className="char-img-preview standing-preview"
              src={`/api/characters/${selectedChar}/standing?r=${imgRefresh}`}
              alt="standing"
              onError={e => (e.currentTarget.style.display = 'none')}
            />
            <input
              ref={standingInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              style={{ display: 'none' }}
              onChange={e => e.target.files?.[0] && uploadImage('standing', e.target.files[0])}
            />
            <button className="char-btn" onClick={() => standingInputRef.current?.click()}>
              {t('char.uploadBtn')}
            </button>
            <button
              className="char-btn"
              onClick={() => generateImage('standing')}
              disabled={generatingStanding}
            >
              {generatingStanding ? t('char.generateBtn.loading') : t('char.generateBtn')}
            </button>
          </div>
          <div className="char-img-edit-col voice-col">
            <p className="char-img-label">{t('char.voice.label')}</p>
            {!vvRunning && !iroRunning && (
              <p className="char-section-note">{t('char.voice.ttsNotRunning')}</p>
            )}
            {showVv && (
              <div className="voice-settings-block">
                <label className="voice-label">{t('char.voice.vvSpeaker.label')}</label>
                <select
                  value={selectedVvSpeaker}
                  onChange={e => setSelectedVvSpeaker(Number(e.target.value))}
                >
                  {vvSpeakers.map(s => (
                    <option key={s.id} value={s.id}>{s.label}</option>
                  ))}
                </select>
                <div className="voice-btn-row">
                  <button
                    className="char-btn"
                    onClick={() => saveVoiceSettings('voicevox', selectedVvSpeaker)}
                    disabled={savingVoice}
                  >
                    {t('char.voice.saveBtn')}
                  </button>
                  <button
                    className="char-btn"
                    onClick={() => testVoice('voicevox', selectedVvSpeaker)}
                    disabled={testingVoice}
                  >
                    {t('char.voice.testBtn')}
                  </button>
                </div>
              </div>
            )}
            {showIro && (
              <div className="voice-settings-block">
                <label className="voice-label">{t('char.voice.iroVoice.label')}</label>
                <select
                  value={selectedIroVoice}
                  onChange={e => setSelectedIroVoice(e.target.value)}
                >
                  {iroVoices.map(v => <option key={v} value={v}>{v}</option>)}
                </select>
                <div className="voice-btn-row">
                  <button
                    className="char-btn"
                    onClick={() => saveVoiceSettings('irodori', selectedIroVoice)}
                    disabled={savingVoice}
                  >
                    {t('char.voice.saveBtn')}
                  </button>
                  <button
                    className="char-btn"
                    onClick={() => testVoice('irodori', selectedIroVoice)}
                    disabled={testingVoice}
                  >
                    {t('char.voice.testBtn')}
                  </button>
                </div>
              </div>
            )}
            {voiceSaveMsg && <p className="char-msg">{voiceSaveMsg}</p>}
            {testAudioUrl && (
              <audio controls autoPlay src={testAudioUrl} className="test-audio" />
            )}
          </div>
        </div>
        {imgMsg && <p className="char-msg">{imgMsg}</p>}
      </div>

      {/* ===== 3. プロファイルJSON編集 ===== */}
      <div className="char-section">
        <h3 className="char-section-title">{t('char.profile.editTitle')}</h3>
        <textarea
          className="profile-json-editor"
          value={rawProfile}
          onChange={e => setRawProfile(e.target.value)}
          spellCheck={false}
        />
        <button
          className="char-btn"
          onClick={saveRawProfile}
          disabled={savingProfile}
        >
          {savingProfile ? t('char.profile.saveBtn.loading') : t('char.profile.saveBtn')}
        </button>
        {profileMsg && <p className="char-msg">{profileMsg}</p>}
      </div>
      </>}

      <div className="char-danger-zone">
        <button className="danger-btn" onClick={clearHistory} disabled={clearing || !selectedChar}>
          {clearing ? t('char.history.deleteBtn.loading') : t('char.history.deleteBtn')}
        </button>
      </div>
    </div>
  )
}
