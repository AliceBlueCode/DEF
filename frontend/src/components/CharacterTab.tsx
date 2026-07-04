import { useState, useEffect } from 'react'

type Props = {
  selectedChar: string
}

type CharDetail = {
  name: string
  persona_description?: string
  speech_style?: string
  appearance_tags?: string
  image_name_tags?: string
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

  const name = char.name || selectedChar
  const persona = char.persona_description as string || ''
  const speakingStyle = char.speech_style as string || ''
  const appearanceTags = char.appearance_tags as string || ''
  const imageNameTags = char.image_name_tags as string || ''

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
        {persona && (
          <div className="profile-section">
            <h3>性格・背景</h3>
            <p>{persona}</p>
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
        {imageNameTags && (
          <div className="profile-section">
            <h3>キャラ名タグ</h3>
            <p className="appearance-tags">{imageNameTags}</p>
          </div>
        )}
      </div>
    </div>
  )
}
