import { useState, useEffect } from 'react'

type Props = {
  selectedChar: string
}

type CharDetail = {
  name: string
  base_profile: Record<string, unknown>
  appearance_tags?: string
  [key: string]: unknown
}

export default function CharacterTab({ selectedChar }: Props) {
  const [char, setChar] = useState<CharDetail | null>(null)

  useEffect(() => {
    if (!selectedChar) return
    fetch(`/api/characters/${selectedChar}`)
      .then(r => r.json())
      .then(data => setChar(data.character || null))
  }, [selectedChar])

  if (!char) return <div className="tab-content">キャラクターを選択してください</div>

  const bp = (char.base_profile || {}) as Record<string, unknown>
  const name = (bp.name as string) || char.name || selectedChar
  const personality = bp.personality as string || ''
  const background = bp.background as string || ''
  const speakingStyle = bp.speaking_style as string || ''
  const appearanceTags = char.appearance_tags as string || ''

  return (
    <div className="tab-content character-tab">
      <div className="char-header">
        <div className="char-images">
          <div className="char-icon-large">
            <img src={`/api/characters/${selectedChar}/icon`} alt={name} />
          </div>
          <div className="char-standing">
            <img
              src={`/api/characters/${selectedChar}/standing`}
              alt={name}
              onError={e => (e.currentTarget.style.display = 'none')}
            />
          </div>
        </div>
        <h2>{name}</h2>
      </div>

      <div className="char-profile">
        {personality && (
          <div className="profile-section">
            <h3>性格</h3>
            <p>{personality}</p>
          </div>
        )}
        {background && (
          <div className="profile-section">
            <h3>背景</h3>
            <p>{background}</p>
          </div>
        )}
        {speakingStyle && (
          <div className="profile-section">
            <h3>話し方</h3>
            <p>{speakingStyle}</p>
          </div>
        )}
        {appearanceTags && (
          <div className="profile-section">
            <h3>外見タグ</h3>
            <p className="appearance-tags">{appearanceTags}</p>
          </div>
        )}
      </div>
    </div>
  )
}
