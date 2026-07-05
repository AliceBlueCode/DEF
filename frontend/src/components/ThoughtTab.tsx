import { useState, useEffect, useCallback } from 'react'
import { useT } from '../i18n'

type ThoughtEntry = {
  id: string
  input: string
  output: string
  model: string
}

interface Props {
  backend: string
}

export default function ThoughtTab({ backend }: Props) {
  const t = useT()
  const [entries, setEntries] = useState<ThoughtEntry[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)

  const loadEntries = useCallback(() => {
    fetch('/api/thought/')
      .then(r => r.json())
      .then(data => setEntries(data.entries || []))
      .catch(() => {})
  }, [])

  useEffect(() => { loadEntries() }, [loadEntries])

  const handleSubmit = async () => {
    if (!input.trim() || loading) return
    setLoading(true)
    try {
      const res = await fetch('/api/thought/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input, backend }),
      })
      if (!res.ok) throw new Error(await res.text())
      const entry: ThoughtEntry = await res.json()
      setEntries(prev => [entry, ...prev])
      setInput('')
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await fetch(`/api/thought/${id}`, { method: 'DELETE' })
      setEntries(prev => prev.filter(e => e.id !== id))
    } catch (e) {
      console.error(e)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="tab-content thought-tab">
      <div className="thought-input-area">
        <h2 className="thought-heading">{t('thought.heading')}</h2>
        <textarea
          className="thought-textarea"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t('thought.input.placeholder')}
          rows={5}
          disabled={loading}
        />
        <div className="thought-toolbar">
          <button
            className="thought-submit-btn"
            onClick={handleSubmit}
            disabled={loading || !input.trim()}
          >
            {loading ? t('thought.submitBtn.loading') : t('thought.submitBtn')}
          </button>
          <span className="thought-hint">Ctrl+Enter</span>
        </div>
      </div>

      <div className="thought-history">
        {entries.length === 0 ? (
          <p className="thought-empty">{t('thought.history.empty')}</p>
        ) : (
          entries.map(entry => (
            <div key={entry.id} className="thought-entry">
              <div className="thought-entry-header">
                <span className="thought-entry-model">{t('thought.entry.model', { model: entry.model || '—' })}</span>
                <button
                  className="thought-delete-btn"
                  title={t('thought.entry.deleteBtn.title')}
                  onClick={() => handleDelete(entry.id)}
                >✕</button>
              </div>
              <div className="thought-entry-section">
                <div className="thought-entry-label">{t('thought.entry.inputLabel')}</div>
                <div className="thought-entry-text thought-entry-input">{entry.input}</div>
              </div>
              <div className="thought-entry-section">
                <div className="thought-entry-label">{t('thought.entry.outputLabel')}</div>
                <div className="thought-entry-text thought-entry-output">{entry.output}</div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
