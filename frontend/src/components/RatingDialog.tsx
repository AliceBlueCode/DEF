import { useT } from '../i18n'

type Props = {
  sexualKey: string
  violenceKey: string
  onChangeSexual: (key: string) => void
  onChangeViolence: (key: string) => void
  onClose: () => void
}

const SEXUAL_OPTIONS = ['general', 'sfw', 'nsfw', 'hentai']
const VIOLENCE_OPTIONS = ['general', 'violence', 'gore', 'extreme']

export default function RatingDialog({
  sexualKey, violenceKey,
  onChangeSexual, onChangeViolence,
  onClose,
}: Props) {
  const t = useT()

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog rating-dialog" onClick={e => e.stopPropagation()}>
        <div className="dialog-header">
          <span>{t('rating.heading')}</span>
          <button className="dialog-close" onClick={onClose}>✕</button>
        </div>

        <div className="rating-section">
          <h4>{t('rating.sexual.heading')}</h4>
          <div className="rating-options">
            {SEXUAL_OPTIONS.map(value => (
              <label key={value} className={`rating-option ${sexualKey === value ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name="sexual"
                  value={value}
                  checked={sexualKey === value}
                  onChange={() => onChangeSexual(value)}
                />
                <span className="rating-label">{t(`rating.sexual.${value}`)}</span>
                <span className="rating-desc">{t(`rating.sexual.${value}.desc`)}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="rating-section">
          <h4>{t('rating.violence.heading')}</h4>
          <div className="rating-options">
            {VIOLENCE_OPTIONS.map(value => (
              <label key={value} className={`rating-option ${violenceKey === value ? 'selected' : ''}`}>
                <input
                  type="radio"
                  name="violence"
                  value={value}
                  checked={violenceKey === value}
                  onChange={() => onChangeViolence(value)}
                />
                <span className="rating-label">{t(`rating.violence.${value}`)}</span>
                <span className="rating-desc">{t(`rating.violence.${value}.desc`)}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="dialog-footer">
          <button className="btn-primary" onClick={onClose}>{t('dialog.closeBtn')}</button>
        </div>
      </div>
    </div>
  )
}
