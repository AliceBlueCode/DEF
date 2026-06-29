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

  const loadList = () => {
    fetch('/api/episode/')
      .then(r => r.json())
      .then(data => setEpisodes(data.episodes || []))
  }

  useEffect(() => { loadList() }, [])

  useEffect(() => {
    if (!selectedTitle) { setEpisode(null); setBody(''); return }
    fetch(`/api/episode/${encodeURIComponent(selectedTitle)}`)
      .then(r => r.json())
      .then(data => {
        if (data.episode) {
          setEpisode(data.episode)
          setBody(data.episode.body || '')
        }
      })
  }, [selectedTitle])

  const saveEpisode = async () => {
    const ep = { ...(episode || {}), title: selectedTitle || newTitle, body }
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
    const lines = body.split('\n')
    if (type === 'chapter') {
      const chCount = (body.match(/--- Chapter \d+ ---/g) || []).length
      const marker = `\n--- Chapter ${chCount + 1} ---\n--- Scene 1 ---\n`
      setBody(body + marker)
    } else {
      const scCount = (body.match(/--- Scene \d+ ---/g) || []).length
      setBody(body + `\n--- Scene ${scCount + 1} ---\n`)
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
                <button onClick={() => insertMarker('chapter')}>新章</button>
                <button onClick={() => insertMarker('scene')}>新場面</button>
                <button className="delete-btn" onClick={deleteEpisode}>🗑 削除</button>
              </div>
            </div>
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
    </div>
  )
}
