type Props = {
  sexualKey: string
  violenceKey: string
  onChangeSexual: (key: string) => void
  onChangeViolence: (key: string) => void
  onClose: () => void
}

const SEXUAL_OPTIONS = [
  { value: 'general', label: '全年齢',     desc: '性的表現なし' },
  { value: 'sfw',     label: 'R-15相当',   desc: '水着・下着等、示唆あり' },
  { value: 'nsfw',    label: 'R-18相当',   desc: '性的表現あり（露骨でない）' },
  { value: 'hentai',  label: '変態 R-20+', desc: '露骨な性的表現' },
]

const VIOLENCE_OPTIONS = [
  { value: 'general',  label: '全年齢',     desc: '暴力表現なし' },
  { value: 'violence', label: 'アクション', desc: '一般的な暴力表現' },
  { value: 'gore',     label: 'ホラー',     desc: '流血・グロ表現あり' },
  { value: 'extreme',  label: '無制限',     desc: '過激な暴力表現' },
]

export default function RatingDialog({
  sexualKey, violenceKey,
  onChangeSexual, onChangeViolence,
  onClose,
}: Props) {
  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog rating-dialog" onClick={e => e.stopPropagation()}>
        <div className="dialog-header">
          <span>🚫 レーティング設定</span>
          <button className="dialog-close" onClick={onClose}>✕</button>
        </div>

        <div className="rating-section">
          <h4>性的コンテンツ</h4>
          <div className="rating-options">
            {SEXUAL_OPTIONS.map(opt => (
              <label key={opt.value} className={`rating-option ${sexualKey === opt.value ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name="sexual"
                  value={opt.value}
                  checked={sexualKey === opt.value}
                  onChange={() => onChangeSexual(opt.value)}
                />
                <span className="rating-label">{opt.label}</span>
                <span className="rating-desc">{opt.desc}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="rating-section">
          <h4>暴力コンテンツ</h4>
          <div className="rating-options">
            {VIOLENCE_OPTIONS.map(opt => (
              <label key={opt.value} className={`rating-option ${violenceKey === opt.value ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name="violence"
                  value={opt.value}
                  checked={violenceKey === opt.value}
                  onChange={() => onChangeViolence(opt.value)}
                />
                <span className="rating-label">{opt.label}</span>
                <span className="rating-desc">{opt.desc}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="dialog-footer">
          <button className="btn-primary" onClick={onClose}>閉じる</button>
        </div>
      </div>
    </div>
  )
}
