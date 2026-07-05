import { useState, useEffect, useMemo, useRef } from 'react'
import { useT } from '../i18n'

type NovelItem = { title: string; file: string }
type Novel = { title: string; body: string; plot?: string; [key: string]: unknown }
type MediaItem =
  | { type: 'image'; prompt: string; url: string }
  | { type: 'audio'; text: string; url: string }

type BackendInfo = { backends: string[]; labels: Record<string, string>; default: string }

type Props = {
  backend: string
  t2iBackend: string
  candidateCount: number
  ttsBackend: string
  selectedChar: string
  llmBackends: BackendInfo | null
}


function splitScenes(body: string): { label: string; text: string }[] {
  const segments = body.split(/(--- (?:Chapter|Scene) \d+ ---)/)
  const scenes: { label: string; text: string }[] = []
  let chapter = ''
  let scene = ''
  for (const seg of segments) {
    const chMatch = seg.match(/^--- (Chapter \d+) ---$/)
    const scMatch = seg.match(/^--- (Scene \d+) ---$/)
    if (chMatch) { chapter = chMatch[1]; scene = '' }
    else if (scMatch) { scene = scMatch[1] }
    else if (seg.trim()) {
      const clean = seg.trim()
      if (clean) {
        const label = chapter && scene ? `${chapter} + ${scene}` : scene || chapter || 'Scene'
        scenes.push({ label, text: clean })
      }
    }
  }
  return scenes
}

function chunkText(text: string, maxLen = 400): string[] {
  const cleaned = text.replace(/--- (?:Chapter|Scene) \d+ ---/g, '').trim()
  const sentences: string[] = []
  cleaned.split('\n').forEach(line => {
    line = line.trim()
    if (!line) return
    line.split(/(?<=。)/).forEach(s => { if (s.trim()) sentences.push(s.trim()) })
  })
  if (sentences.length === 0 && cleaned) return [cleaned]
  const chunks: string[] = []
  let buf = ''
  for (const sent of sentences) {
    if (buf && buf.length + sent.length > maxLen) { chunks.push(buf); buf = sent }
    else { buf = buf ? buf + sent : sent }
  }
  if (buf) chunks.push(buf)
  return chunks
}

export default function NovelTab({ backend, t2iBackend, candidateCount, ttsBackend, selectedChar, llmBackends }: Props) {
  const t = useT()
  const [novels, setNovels] = useState<NovelItem[]>([])
  const [selectedTitle, setSelectedTitle] = useState('')
  const [novel, setNovel] = useState<Novel | null>(null)
  const [body, setBody] = useState('')
  const [titleInput, setTitleInput] = useState('')
  const [plot, setPlot] = useState('')
  const [showPlotDialog, setShowPlotDialog] = useState(false)
  const [plotDraft, setPlotDraft] = useState('')
  const [plotFile, setPlotFile] = useState('')
  const [plotServerFiles, setPlotServerFiles] = useState<{ name: string }[]>([])

  const [candidates, setCandidates] = useState<string[]>([])
  const [activeCandidate, setActiveCandidate] = useState(0)
  const [generating, setGenerating] = useState(false)
  const [selectedSceneIdx, setSelectedSceneIdx] = useState(0)
  const [generatingImage, setGeneratingImage] = useState(false)
  const [media, setMedia] = useState<MediaItem[]>([])
  const [imageError, setImageError] = useState('')
  const [novelBackend, setNovelBackend] = useState('')
  const [novelT2iBackend, setNovelT2iBackend] = useState('')
  const [novelT2iModel, setNovelT2iModel] = useState('')
  const [showT2iDialog, setShowT2iDialog] = useState(false)
  const [t2iDlgBackend, setT2iDlgBackend] = useState('')
  const [t2iDlgModel, setT2iDlgModel] = useState('')
  const [t2iDlgModels, setT2iDlgModels] = useState<string[]>([])
  const [t2iDlgWorkflows, setT2iDlgWorkflows] = useState<string[]>([])
  const [t2iDlgWorkflow, setT2iDlgWorkflow] = useState('')
  const [t2iDlgCustom, setT2iDlgCustom] = useState('')
  const [t2iBackendInfo, setT2iBackendInfo] = useState<{ backends: string[]; labels: Record<string, string> } | null>(null)
  const [t2iCivitaiModels, setT2iCivitaiModels] = useState<{ label: string; model_air: string }[]>([])
  const [ttsPlaying, setTtsPlaying] = useState(false)
  const [mediaHeight, setMediaHeight] = useState(() => Number(localStorage.getItem('novel_media_height')) || 200)
  const [candidatesWidth, setCandidatesWidth] = useState(() => Number(localStorage.getItem('novel_candidates_width')) || 420)
  const ttsAbortRef = useRef(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const resizingRef = useRef(false)
  const resizeStartY = useRef(0)
  const resizeStartH = useRef(0)
  const colResizingRef = useRef(false)
  const colResizeStartX = useRef(0)
  const colResizeStartW = useRef(0)

  const onResizeStart = (e: React.MouseEvent) => {
    resizingRef.current = true
    resizeStartY.current = e.clientY
    resizeStartH.current = mediaHeight
    const onMove = (ev: MouseEvent) => {
      if (!resizingRef.current) return
      const delta = resizeStartY.current - ev.clientY
      setMediaHeight(Math.max(80, Math.min(600, resizeStartH.current + delta)))
    }
    const onUp = () => {
      resizingRef.current = false
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  const onColResizeStart = (e: React.MouseEvent) => {
    colResizingRef.current = true
    colResizeStartX.current = e.clientX
    colResizeStartW.current = candidatesWidth
    const onMove = (ev: MouseEvent) => {
      if (!colResizingRef.current) return
      const delta = colResizeStartX.current - ev.clientX
      setCandidatesWidth(Math.max(160, Math.min(700, colResizeStartW.current + delta)))
    }
    const onUp = () => {
      colResizingRef.current = false
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  useEffect(() => { if (!novelBackend && backend) setNovelBackend(backend) }, [backend])
  useEffect(() => { if (t2iBackend) setNovelT2iBackend(t2iBackend) }, [t2iBackend])
  useEffect(() => { localStorage.setItem('novel_media_height', String(mediaHeight)) }, [mediaHeight])
  useEffect(() => { localStorage.setItem('novel_candidates_width', String(candidatesWidth)) }, [candidatesWidth])

  const scenes = useMemo(() => splitScenes(body), [body])
  const currentSceneText = scenes.length > 0
    ? scenes[scenes.length - 1].text
    : body.replace(/--- (?:Chapter|Scene) \d+ ---/g, '').trim()

  const loadList = () =>
    fetch('/api/novel/').then(r => r.json()).then(data => setNovels(data.novels || []))

  useEffect(() => { loadList() }, [])
  useEffect(() => {
    fetch('/api/novel/plots')
      .then(r => r.json())
      .then(data => setPlotServerFiles(data.files || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    setCandidates([])
    setMedia([])
    if (!selectedTitle) {
      setNovel(null); setBody(''); setPlot(''); setTitleInput('')
      return
    }
    fetch(`/api/novel/${encodeURIComponent(selectedTitle)}`)
      .then(r => r.json())
      .then(data => {
        if (data.novel) {
          setNovel(data.novel)
          setBody(data.novel.body || '')
          setPlot(data.novel.plot || '')
          setTitleInput(data.novel.title || selectedTitle)
        }
      })
  }, [selectedTitle])

  const doSave = async (newBody: string, newPlot?: string, newTitle?: string) => {
    const title = (newTitle ?? titleInput).trim() || 'Untitled'
    const ep = { ...(novel || {}), title, body: newBody, plot: newPlot ?? plot }
    await fetch('/api/novel/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ novel: ep }),
    })
    // タイトルが変わった場合は旧ファイルを削除
    if (selectedTitle && selectedTitle !== title) {
      await fetch(`/api/novel/${encodeURIComponent(selectedTitle)}`, { method: 'DELETE' })
    }
    setSelectedTitle(title)
    setTitleInput(title)
    loadList()
  }

  const saveNovel = () => doSave(body)

  const deleteNovel = async () => {
    if (!selectedTitle) return
    if (!confirm(t('novel.deleteConfirm', { title: selectedTitle }))) return
    await fetch(`/api/novel/${encodeURIComponent(selectedTitle)}`, { method: 'DELETE' })
    setSelectedTitle(''); setNovel(null); setBody(''); setTitleInput('')
    loadList()
  }

  const insertMarker = (type: 'chapter' | 'scene') => {
    if (type === 'chapter') {
      const n = (body.match(/--- Chapter \d+ ---/g) || []).length
      setBody(body + `\n--- Chapter ${n + 1} ---\n--- Scene 1 ---\n`)
    } else {
      const n = (body.match(/--- Scene \d+ ---/g) || []).length
      setBody(body + `\n--- Scene ${n + 1} ---\n`)
    }
  }

  const generateCandidates = async () => {
    setGenerating(true); setCandidates([])
    try {
      const res = await fetch('/api/novel/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body, plot, backend: novelBackend || backend, candidate_count: candidateCount }),
      })
      const data = await res.json()
      setCandidates(data.candidates || []); setActiveCandidate(0)
    } catch (e) { console.error(e) }
    finally { setGenerating(false) }
  }

  const appendCandidate = async (text: string) => {
    const newBody = body ? `${body}\n${text}` : text
    setBody(newBody); setCandidates([])
    await doSave(newBody)
  }

  const loadT2iModelsForBackend = async (backend: string) => {
    setT2iDlgModels([])
    setT2iDlgWorkflows([])
    if (!backend) return
    try {
      if (backend === 'civitai') {
        const res = await fetch('/api/settings/civitai-models')
        const data = await res.json()
        setT2iCivitaiModels(data.models || [])
      } else {
        const res = await fetch(`/api/settings/t2i-models?backend=${encodeURIComponent(backend)}`)
        const data = await res.json()
        setT2iDlgModels(data.models || [])
        setT2iDlgWorkflows(data.workflows || [])
      }
    } catch { /* ignore */ }
  }

  const openT2iDialog = async () => {
    const dlgBackend = novelT2iBackend || t2iBackend || ''
    setT2iDlgBackend(dlgBackend)
    setT2iDlgModel(novelT2iModel)
    setT2iDlgCustom('')
    setT2iDlgModels([])
    setT2iDlgWorkflows([])
    setT2iDlgWorkflow('')
    setShowT2iDialog(true)
    if (!t2iBackendInfo) {
      try {
        const res = await fetch('/api/settings/backends')
        const data = await res.json()
        if (data.t2i) setT2iBackendInfo(data.t2i)
      } catch { /* ignore */ }
    }
    await loadT2iModelsForBackend(dlgBackend)
  }

  const onT2iDlgBackendChange = async (backend: string) => {
    setT2iDlgBackend(backend)
    setT2iDlgModel('')
    setT2iDlgCustom('')
    await loadT2iModelsForBackend(backend)
  }

  const applyT2iSettings = () => {
    setNovelT2iBackend(t2iDlgBackend)
    setNovelT2iModel(t2iDlgCustom.trim() || t2iDlgModel)
    setShowT2iDialog(false)
  }

  const generateImage = async (sceneText: string) => {
    if (!sceneText) return
    setGeneratingImage(true); setImageError('')
    try {
      const res = await fetch('/api/novel/t2i', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scene_text: sceneText, plot, llm_backend: novelBackend || backend, t2i_backend: novelT2iBackend || t2iBackend, t2i_model: novelT2iModel }),
      })
      const data = await res.json()
      if (data.error) { setImageError(data.error); return }
      setMedia(prev => [...prev, { type: 'image', prompt: data.prompt, url: data.image_url }])
    } catch (e) { setImageError(String(e)) }
    finally { setGeneratingImage(false) }
  }

  const playNovelTTS = async (text: string) => {
    if (!selectedChar || !ttsBackend || ttsPlaying) return
    ttsAbortRef.current = false; setTtsPlaying(true)
    for (const chunk of chunkText(text)) {
      if (ttsAbortRef.current) break
      try {
        const res = await fetch('/api/tts/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: chunk, character_id: selectedChar, backend: ttsBackend }),
        })
        if (!res.ok) continue
        const blob = await res.blob()
        const url = URL.createObjectURL(blob)
        setMedia(prev => [...prev, { type: 'audio', text: chunk, url }])
        await new Promise<void>(resolve => {
          const audio = new Audio(url)
          audio.onended = () => resolve()
          audio.onerror = () => resolve()
          audio.play().catch(() => resolve())
        })
      } catch (e) { console.error('Novel TTS error:', e) }
    }
    setTtsPlaying(false)
  }

  const stopTTS = () => { ttsAbortRef.current = true; setTtsPlaying(false) }

  const openPlotDialog = () => {
    setPlotDraft(plot)
    setShowPlotDialog(true)
  }

  const loadServerPlot = async (name: string, applyImmediately = false) => {
    try {
      const res = await fetch(`/api/novel/plots/${encodeURIComponent(name)}`)
      const data = await res.json()
      if (data.content !== undefined) {
        setPlotDraft(data.content)
        setPlotFile(name)
        if (applyImmediately) setPlot(data.content)
      }
    } catch (e) { console.error('plot load error:', e) }
  }

  const handleFileLoad = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setPlotFile(file.name)
    const reader = new FileReader()
    reader.onload = ev => setPlotDraft((ev.target?.result as string) || '')
    reader.readAsText(file, 'utf-8')
    e.target.value = ''
  }

  const writePlotFile = async (content: string) => {
    if (!plotFile) return
    await fetch(`/api/novel/plots/${encodeURIComponent(plotFile)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
  }

  const savePlot = async () => {
    setPlot(plotDraft)
    await writePlotFile(plotDraft)
    if (selectedTitle) await doSave(body, plotDraft)
  }

  const applyPlot = async () => {
    setPlot(plotDraft)
    await writePlotFile(plotDraft)
    if (selectedTitle) await doSave(body, plotDraft)
    setShowPlotDialog(false)
  }

  const backendList = llmBackends?.backends || []
  const backendLabels = llmBackends?.labels || {}
  const isNew = !selectedTitle

  return (
    <div className="tab-content novel-tab">

      {/* ヘッダー: 作品選択・タイトル・プロット設定 */}
      <div className="novel-header">
        <div className="novel-select-row">
          <select
            className="novel-select"
            value={selectedTitle}
            onChange={e => setSelectedTitle(e.target.value)}
          >
            <option value="">{t('novel.select.newWork')}</option>
            {novels.map(n => <option key={n.title} value={n.title}>{n.title}</option>)}
          </select>
        </div>

        <div className="novel-title-row">
          <label className="novel-field-label">{t('novel.field.titleLabel')}</label>
          <input
            className="novel-title-input"
            value={titleInput}
            onChange={e => setTitleInput(e.target.value)}
            placeholder={t('novel.field.titlePlaceholder')}
          />
        </div>

        <div className="novel-plot-row">
          <select
            className="novel-backend-sel"
            value={plotFile}
            onChange={e => {
              const name = e.target.value
              if (name) loadServerPlot(name, true)
              else { setPlotFile(''); setPlot('') }
            }}
          >
            <option value="">{t('novel.plot.noPlot')}</option>
            {plotServerFiles.map(f => (
              <option key={f.name} value={f.name}>{f.name}</option>
            ))}
          </select>
          <button className="novel-hdr-btn" onClick={openPlotDialog} title={t('novel.plot.editBtn.title')}>✏️</button>
          {backendList.length > 0 && (
            <select
              className="novel-backend-sel"
              value={novelBackend || backend}
              onChange={e => setNovelBackend(e.target.value)}
            >
              {backendList.map(b => (
                <option key={b} value={b}>{backendLabels[b] || b}</option>
              ))}
            </select>
          )}
        </div>
      </div>

      {/* 本文 + 候補 2カラム */}
      <div className="novel-body-area">
        <div className="novel-body-col">
          <textarea
            className="novel-editor"
            value={body}
            onChange={e => setBody(e.target.value)}
            placeholder={t('novel.editor.placeholder')}
          />
        </div>

        <div className="novel-col-resize-handle" onMouseDown={onColResizeStart} />

        <div className="novel-candidates" style={{ width: `${candidatesWidth}px`, flexShrink: 0 }}>
          <h3>{t('novel.candidates.heading')}</h3>
          {candidates.length > 0 ? (
            <>
              <div className="candidate-tabs">
                {candidates.map((_, i) => (
                  <button
                    key={i}
                    className={`candidate-tab ${activeCandidate === i ? 'active' : ''}`}
                    onClick={() => setActiveCandidate(i)}
                  >
                    #{i + 1}
                  </button>
                ))}
              </div>
              <textarea
                className="candidate-text"
                value={candidates[activeCandidate] || ''}
                onChange={e => {
                  const next = [...candidates]; next[activeCandidate] = e.target.value; setCandidates(next)
                }}
              />
              <div className="candidate-actions">
                <button onClick={() => appendCandidate(candidates[activeCandidate])}>{t('novel.candidates.addBtn')}</button>
                <button onClick={() => setCandidates([])}>{t('novel.candidates.clearBtn')}</button>
              </div>
            </>
          ) : (
            <p className="candidate-empty">{t('novel.candidates.empty')}</p>
          )}
        </div>
      </div>

      {/* 下部バー: 編集操作（左） / TTS・T2I（右） */}
      <div className="novel-action-bar">
        <div className="novel-action-left">
          <button onClick={saveNovel}>{t('novel.actionBar.saveBtn')}</button>
          <button onClick={generateCandidates} disabled={generating}>
            {generating ? t('novel.actionBar.generateBtn.loading') : t('novel.actionBar.generateBtn')}
          </button>
          <button onClick={() => insertMarker('chapter')}>{t('novel.actionBar.newChapterBtn')}</button>
          <button onClick={() => insertMarker('scene')}>{t('novel.actionBar.newSceneBtn')}</button>
          {!isNew && (
            <button className="delete-btn" onClick={deleteNovel}>{t('novel.actionBar.deleteBtn')}</button>
          )}
        </div>
        <div className="novel-action-right">
          {ttsPlaying ? (
            <button onClick={stopTTS}>{t('novel.actionBar.stopTtsBtn')}</button>
          ) : (
            <button onClick={() => playNovelTTS(currentSceneText)} disabled={!currentSceneText || !selectedChar}>
              {t('novel.actionBar.currentSceneTtsBtn')}
            </button>
          )}
          <button onClick={() => generateImage(currentSceneText)} disabled={generatingImage || !currentSceneText}>
            {t('novel.actionBar.currentIllustBtn')}
          </button>
          {scenes.length > 0 && (
            <>
              <select value={selectedSceneIdx} onChange={e => setSelectedSceneIdx(Number(e.target.value))}>
                {scenes.map((s, i) => <option key={i} value={i}>{s.label}</option>)}
              </select>
              <button onClick={() => playNovelTTS(scenes[selectedSceneIdx]?.text || '')} disabled={ttsPlaying || !selectedChar}>
                {t('novel.actionBar.selectedTtsBtn')}
              </button>
              <button onClick={() => generateImage(scenes[selectedSceneIdx]?.text || '')} disabled={generatingImage}>
                {t('novel.actionBar.selectedIllustBtn')}
              </button>
            </>
          )}
          {(generatingImage || ttsPlaying) && (
            <span className="generating-label">{generatingImage ? t('novel.actionBar.generatingLabel') : t('novel.actionBar.ttsLabel')}</span>
          )}
          <button className="novel-hdr-btn" onClick={openT2iDialog} title={t('novel.actionBar.t2iSettingsBtn.title')}>⚙ T2I</button>
        </div>
      </div>

      {imageError && <p className="image-error">⚠ {imageError}</p>}

      {media.length > 0 && (
        <>
        <div className="novel-resize-handle" onMouseDown={onResizeStart} />
        <div className="novel-media" style={{ height: `${mediaHeight}px`, maxHeight: 'none' }}>
          {media.map((m, i) => (
            <div key={i} className="media-item">
              {m.type === 'image' ? (
                <><p className="media-prompt">Prompt: {m.prompt.slice(0, 200)}</p><img src={m.url} alt="" /></>
              ) : (
                <><p className="media-prompt">{m.text.slice(0, 80)}</p><audio controls src={m.url} className="audio-player" /></>
              )}
            </div>
          ))}
        </div>
        </>
      )}

      {/* プロット設定モーダル */}
      {showPlotDialog && (
        <div className="plot-dialog-overlay" onClick={e => { if (e.target === e.currentTarget) setShowPlotDialog(false) }}>
          <div className="plot-dialog">
            <div className="plot-dialog-header">
              <span>{t('novel.plotDialog.header')}{plotFile ? ` — ${plotFile}` : ''}</span>
              <button className="plot-dialog-close" onClick={() => setShowPlotDialog(false)}>×</button>
            </div>
            <div className="plot-dialog-body">
              <textarea
                className="plot-dialog-textarea"
                value={plotDraft}
                onChange={e => setPlotDraft(e.target.value)}
                placeholder={t('novel.plotDialog.placeholder')}
                rows={12}
              />
            </div>
            <div className="plot-dialog-footer">
              <button className="novel-hdr-btn" onClick={savePlot}>{t('novel.plotDialog.saveBtn')}</button>
              <button className="novel-hdr-btn apply-btn" onClick={applyPlot}>{t('novel.plotDialog.applyBtn')}</button>
            </div>
          </div>
        </div>
      )}
      {/* T2I設定モーダル */}
      {showT2iDialog && (
        <div className="plot-dialog-overlay" onClick={e => { if (e.target === e.currentTarget) setShowT2iDialog(false) }}>
          <div className="plot-dialog" style={{ maxWidth: 440 }}>
            <div className="plot-dialog-header">
              <span>{t('novel.t2iDialog.header')}</span>
              <button onClick={() => setShowT2iDialog(false)}>✕</button>
            </div>
            <div className="plot-dialog-body" style={{ gap: 14 }}>

              {/* バックエンド */}
              <div className="t2i-dlg-row">
                <label>{t('novel.t2iDialog.backendLabel')}</label>
                <select
                  className="novel-backend-sel"
                  value={t2iDlgBackend}
                  onChange={e => onT2iDlgBackendChange(e.target.value)}
                >
                  {(t2iBackendInfo?.backends ?? [t2iDlgBackend]).map(b => (
                    <option key={b} value={b}>{t2iBackendInfo?.labels[b] || b}</option>
                  ))}
                </select>
              </div>

              {/* モデル (a1111 / comfyui / HF — リストあり) */}
              {t2iDlgModels.length > 0 && t2iDlgBackend !== 'civitai' && (
                <div className="t2i-dlg-row">
                  <label>{t('novel.t2iDialog.modelLabel')}</label>
                  <select
                    className="novel-backend-sel"
                    value={t2iDlgModel}
                    onChange={e => { setT2iDlgModel(e.target.value); setT2iDlgCustom('') }}
                  >
                    {t2iDlgBackend !== 'huggingface' && <option value="">{t('novel.t2iDialog.modelCurrentOption')}</option>}
                    {t2iDlgModels.map(m => <option key={m} value={m}>{m}</option>)}
                  </select>
                </div>
              )}

              {/* ワークフロー (comfyui のみ) */}
              {t2iDlgWorkflows.length > 0 && (
                <div className="t2i-dlg-row">
                  <label>{t('novel.t2iDialog.workflowLabel')}</label>
                  <select
                    className="novel-backend-sel"
                    value={t2iDlgWorkflow}
                    onChange={e => setT2iDlgWorkflow(e.target.value)}
                  >
                    {t2iDlgWorkflows.map(w => <option key={w} value={w}>{w}</option>)}
                  </select>
                </div>
              )}

              {/* HuggingFace カスタム入力 */}
              {t2iDlgBackend === 'huggingface' && (
                <div className="t2i-dlg-row">
                  <label>{t('novel.t2iDialog.customLabel')}</label>
                  <input
                    className="novel-title-input"
                    value={t2iDlgCustom}
                    onChange={e => setT2iDlgCustom(e.target.value)}
                    placeholder="user/model-name"
                  />
                </div>
              )}

              {/* Civitai モデル */}
              {t2iDlgBackend === 'civitai' && (
                <>
                  {t2iCivitaiModels.length > 0 && (
                    <div className="t2i-dlg-row">
                      <label>{t('novel.t2iDialog.modelLabel')}</label>
                      <select
                        className="novel-backend-sel"
                        value={t2iDlgModel}
                        onChange={e => { setT2iDlgModel(e.target.value); setT2iDlgCustom('') }}
                      >
                        <option value="">{t('novel.t2iDialog.civitaiSelect.empty')}</option>
                        {t2iCivitaiModels.map(m => (
                          <option key={m.model_air} value={m.model_air}>{m.label || m.model_air}</option>
                        ))}
                      </select>
                    </div>
                  )}
                  <div className="t2i-dlg-row">
                    <label>{t('novel.t2iDialog.newAirLabel')}</label>
                    <input
                      className="novel-title-input"
                      value={t2iDlgCustom}
                      onChange={e => setT2iDlgCustom(e.target.value)}
                      placeholder="AIR / URL"
                    />
                  </div>
                </>
              )}

              {/* モデルなしバックエンド用テキスト入力 */}
              {t2iDlgModels.length === 0 && t2iDlgBackend !== 'civitai' && t2iDlgBackend !== 'huggingface' && (
                <div className="t2i-dlg-row">
                  <label>{t('novel.t2iDialog.modelNameLabel')}</label>
                  <input
                    className="novel-title-input"
                    value={t2iDlgModel}
                    onChange={e => setT2iDlgModel(e.target.value)}
                    placeholder={t('novel.t2iDialog.modelNamePlaceholder')}
                  />
                </div>
              )}

              {/* 現在の設定表示 */}
              {novelT2iBackend && (
                <p style={{ fontSize: '0.8em', color: '#888', margin: 0 }}>
                  {t('novel.t2iDialog.currentLabel', { backend: t2iBackendInfo?.labels[novelT2iBackend] || novelT2iBackend, model: novelT2iModel ? ` / ${novelT2iModel}` : '' })}
                </p>
              )}
            </div>
            <div className="plot-dialog-footer">
              <button className="novel-hdr-btn apply-btn" onClick={applyT2iSettings}>{t('novel.t2iDialog.applyBtn')}</button>
            </div>
          </div>
        </div>
      )}

      <input ref={fileInputRef} type="file" accept=".txt,.md" style={{ display: 'none' }} onChange={handleFileLoad} />
    </div>
  )
}
