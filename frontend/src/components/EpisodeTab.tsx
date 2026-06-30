import { useState, useEffect } from 'react'

type EpisodeItem = { title: string; file: string }
type Episode = {
  title: string
  body: string
  plot?: string
  [key: string]: unknown
}

type Props = {
  backend: string
}

export default function EpisodeTab({ backend }: Props) {
  const [episodes, setEpisodes] = useState<EpisodeItem[]>([])
  const [selectedTitle, setSelectedTitle] = useState('')
  const [episode, setEpisode] = useState<Episode | null>(null)
  const [body, setBody] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [plot, setPlot] = useState('')
  const [candidates, setCandidates] = useState<string[]>([])
  const [activeCandidate, setActiveCandidate] = useState(0)
  const [generating, setGenerating] = useState(false)

  const loadList = () => {
    fetch('/api/episode/')
      .then(r => r.json())
      .then(data => setEpisodes(data.episodes || []))
  }

  useEffect(() => { loadList() }, [])

  useEffect(() => {
    setCandidates([])
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
