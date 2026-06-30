import { useState, useEffect, useMemo } from 'react'

type EpisodeItem = { title: string; file: string }
type Episode = {
  title: string
  body: string
  plot?: string
  [key: string]: unknown
}
type MediaItem = { type: 'image'; prompt: string; url: string }

type Props = {
  backend: string
  t2iBackend: string
}

function splitScenes(body: string): { label: string; text: string }[] {
  const segments = body.split(/(--- Scene \d+ ---)/)
  const scenes: { label: string; text: string }[] = []
  let label = ''
  for (const seg of segments) {
    if (/^--- Scene \d+ ---$/.test(seg)) {
      label = seg.trim()
    } else if (seg.trim()) {
      const clean = seg.replace(/--- Chapter \d+ ---/g, '').trim()
      if (clean) scenes.push({ label: label || 'Scene', text: clean })
    }
  }
  return scenes
}

export default function EpisodeTab({ backend, t2iBackend }: Props) {
  const [episodes, setEpisodes] = useState<EpisodeItem[]>([])
  const [selectedTitle, setSelectedTitle] = useState('')
  const [episode, setEpisode] = useState<Episode | null>(null)
  const [body, setBody] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [plot, setPlot] = useState('')
  const [candidates, setCandidates] = useState<string[]>([])
  const [activeCandidate, setActiveCandidate] = useState(0)
  const [generating, setGenerating] = useState(false)
  const [selectedSceneIdx, setSelectedSceneIdx] = useState(0)
  const [generatingImage, setGeneratingImage] = useState(false)
  const [media, setMedia] = useState<MediaItem[]>([])
  const [imageError, setImageError] = useState('')

  const scenes = useMemo(() => splitScenes(body), [body])
  const currentSceneText = scenes.length > 0
    ? scenes[scenes.length - 1].text
    : body.replace(/--- (?:Chapter|Scene) \d+ ---/g, '').trim()

  const loadList = () => {
    fetch('/api/episode/')
      .then(r => r.json())
      .then(data => setEpisodes(data.episodes || []))
  }

  useEffect(() => { loadList() }, [])

  useEffect(() => {
    setCandidates([])
    setMedia([])
    if (!selectedTitle) { setEpisode(null); setBody(''); setPlot(''); return }
    fetch(`/api/episode/${encodeURIComponent(selectedTitle)}`)
      .then(r => r.json())
      .then(data => {
        if (data.episode) {
          setEpisode(data.episode)
          setBody(data.episode.body || '')
          setPlot(data.episode.plot || '')
        }
      })
  }, [selectedTitle])

  const saveEpisode = async () => {
    const ep = { ...(episode || {}), title: selectedTitle || newTitle, body, plot }
    await fetch('/api/episode/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ episode: ep }),
    })
    loadList()
    if (!selectedTitle) setSelectedTitle(ep.title)
  }

  const createNew = () => {
    if (!newTitle.trim()) return
    setSelectedTitle('')
    setEpisode(null)
    setBody('')
    saveEpisodeAs(newTitle)
  }

  const saveEpisodeAs = async (title: string) => {
    await fetch('/api/episode/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ episode: { title, body: '' } }),
    })
    loadList()
    setSelectedTitle(title)
    setNewTitle('')
  }

  const deleteEpisode = async () => {
    if (!selectedTitle) return
    if (!confirm(`"${selectedTitle}" を削除しますか？`)) return
    await fetch(`/api/episode/${encodeURIComponent(selectedTitle)}`, { method: 'DELETE' })
    setSelectedTitle('')
    setEpisode(null)
    setBody('')
    loadList()
  }

  const insertMarker = (type: 'chapter' | 'scene') => {
    if (type === 'chapter') {
      const chCount = (body.match(/--- Chapter \d+ ---/g) || []).length
      const marker = `\n--- Chapter ${chCount + 1} ---\n--- Scene 1 ---\n`
      setBody(body + marker)
    } else {
      const scCount = (body.match(/--- Scene \d+ ---/g) || []).length
      setBody(body + `\n--- Scene ${scCount + 1} ---\n`)
    }
  }

  const generateCandidates = async () => {
    setGenerating(true)
    setCandidates([])
    try {
      const res = await fetch('/api/episode/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          body,
          plot,
          backend,
          candidate_count: 3,
        }),
      })
      const data = await res.json()
      setCandidates(data.candidates || [])
      setActiveCandidate(0)
    } catch (e) {
      console.error(e)
    } finally {
      setGenerating(false)
    }
  }

  const appendCandidate = (text: string) => {
    setBody(prev => (prev ? `${prev}\n${text}` : text))
    setCandidates([])
  }

  const generateImage = async (sceneText: string) => {
    if (!sceneText) return
    setGeneratingImage(true)
    setImageError('')
    try {
      const res = await fetch('/api/episode/t2i', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scene_text: sceneText,
          plot,
          llm_backend: backend,
          t2i_backend: t2iBackend,
        }),
      })
      const data = await res.json()
      if (data.error) {
        setImageError(data.error)
        return
      }
      setMedia(prev => [...prev, { type: 'image', prompt: data.prompt, url: data.image_url }])
    } catch (e) {
      setImageError(String(e))
    } finally {
      setGeneratingImage(false)
    }
  }

  return (
    <div className="tab-content episode-tab">
      <div className="episode-sidebar">
        <h3>作品一覧</h3>
        <div className="episode-list">
          {episodes.map(ep => (
            <button
              key={ep.title}
              className={`episode-item ${selectedTitle === ep.title ? 'active' : ''}`}
              onClick={() => setSelectedTitle(ep.title)}
            >
              {ep.title}
            </button>
          ))}
        </div>
        <div className="episode-new">
          <input
            type="text"
            value={newTitle}
            onChange={e => setNewTitle(e.target.value)}
            placeholder="新しい作品名..."
          />
          <button onClick={createNew} disabled={!newTitle.trim()}>作成</button>
        </div>
      </div>

      <div className="episode-main">
        {selectedTitle ? (
          <>
            <div className="episode-toolbar">
              <h2>{selectedTitle}</h2>
              <div className="episode-actions">
                <button onClick={saveEpisode}>💾 保存</button>
                <button onClick={generateCandidates} disabled={generating}>
                  {generating ? '✍ 生成中...' : '✍ 生成'}
                </button>
                <button onClick={() => insertMarker('chapter')}>新章</button>
                <button onClick={() => insertMarker('scene')}>新場面</button>
                <button className="delete-btn" onClick={deleteEpisode}>🗑 削除</button>
              </div>
            </div>
            <textarea
              className="plot-editor"
              value={plot}
              onChange={e => setPlot(e.target.value)}
              placeholder="プロット設定（任意）..."
              rows={2}
            />
            <textarea
              className="episode-editor"
              value={body}
              onChange={e => setBody(e.target.value)}
              placeholder="ここに物語を書きましょう..."
            />

            <div className="episode-illustration-bar">
              <button
                onClick={() => generateImage(currentSceneText)}
                disabled={generatingImage || !currentSceneText}
              >
                🎨 現挿絵
              </button>
              {scenes.length > 0 && (
                <>
                  <select
                    value={selectedSceneIdx}
                    onChange={e => setSelectedSceneIdx(Number(e.target.value))}
                  >
                    {scenes.map((s, i) => (
                      <option key={i} value={i}>{s.label}</option>
                    ))}
                  </select>
                  <button
                    onClick={() => generateImage(scenes[selectedSceneIdx]?.text || '')}
                    disabled={generatingImage}
                  >
                    🎨 選択挿絵
                  </button>
                </>
              )}
              {generatingImage && <span className="generating-label">生成中...</span>}
            </div>

            {imageError && <p className="image-error">⚠ {imageError}</p>}

            {media.length > 0 && (
              <div className="episode-media">
                {media.map((m, i) => (
                  <div key={i} className="media-item">
                    <p className="media-prompt">Prompt: {m.prompt.slice(0, 200)}</p>
                    <img src={m.url} alt="" />
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          <div className="episode-empty">
            <p>作品を選択するか、新しく作成してください</p>
          </div>
        )}
      </div>

      {selectedTitle && (
        <div className="episode-candidates">
          <h3>AI候補</h3>
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
                  const next = [...candidates]
                  next[activeCandidate] = e.target.value
                  setCandidates(next)
                }}
              />
              <div className="candidate-actions">
                <button onClick={() => appendCandidate(candidates[activeCandidate])}>⬇ 本文に追加</button>
                <button onClick={() => setCandidates([])}>🗑 クリア</button>
              </div>
            </>
          ) : (
            <p className="candidate-empty">「生成」で候補が表示されます。</p>
          )}
        </div>
      )}
    </div>
  )
}
