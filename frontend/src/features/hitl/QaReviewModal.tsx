import { CheckCircle2, ShieldCheck, RotateCcw } from "lucide-react";
import { useTranslation } from '../../stores/i18n';

interface Props {
  message: string;
  isRedoing: boolean;
  redoDisabled: boolean;
  onAccept: () => void;
  onForcePass: () => void;
  onRedo: () => void;
}

export function QaReviewModal({ message, isRedoing, redoDisabled, onAccept, onForcePass, onRedo }: Props) {
  const { t } = useTranslation();
  return (
    <section className="hitl-panel">
      <div>
        <h2>{t('hitl.qaReview')}</h2>
        <p>{message}</p>
      </div>
      <div className="hitl-actions">
        <button className="icon-text-button" onClick={onAccept} type="button">
          <CheckCircle2 size={15} aria-hidden />
          {t('hitl.accept')}
        </button>
        <button className="icon-text-button" onClick={onForcePass} type="button">
          <ShieldCheck size={15} aria-hidden />
          {t('hitl.forcePass')}
        </button>
        <button className="icon-text-button" disabled={isRedoing || redoDisabled} onClick={onRedo} type="button">
          <RotateCcw size={15} aria-hidden />
          {t('hitl.redo')}
        </button>
      </div>
    </section>
  );
}
