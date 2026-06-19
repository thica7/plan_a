import { CheckCircle2, ShieldCheck, Loader2, RotateCcw } from "lucide-react";
import { useTranslation } from '../../stores/i18n';

type QaDecision = "accept" | "force_pass" | "redo";

interface Props {
  message: string;
  activeDecision: QaDecision | null;
  isSubmitting: boolean;
  isRedoing: boolean;
  redoDisabled: boolean;
  onAccept: () => void;
  onForcePass: () => void;
  onRedo: () => void;
}

export function QaReviewModal({
  message,
  activeDecision,
  isSubmitting,
  isRedoing,
  redoDisabled,
  onAccept,
  onForcePass,
  onRedo,
}: Props) {
  const { t } = useTranslation();
  const labelFor = (decision: QaDecision, label: string) =>
    activeDecision === decision ? t('hitl.submitting') : label;

  return (
    <section className="hitl-panel">
      <div>
        <h2>{t('hitl.qaReview')}</h2>
        <p>{message}</p>
      </div>
      <div className="hitl-actions">
        <button
          className="icon-text-button"
          disabled={isSubmitting}
          onClick={onAccept}
          type="button"
        >
          {activeDecision === "accept" ? (
            <Loader2 className="spin" size={15} aria-hidden />
          ) : (
            <CheckCircle2 size={15} aria-hidden />
          )}
          {labelFor("accept", t('hitl.accept'))}
        </button>
        <button
          className="icon-text-button"
          disabled={isSubmitting}
          onClick={onForcePass}
          type="button"
        >
          {activeDecision === "force_pass" ? (
            <Loader2 className="spin" size={15} aria-hidden />
          ) : (
            <ShieldCheck size={15} aria-hidden />
          )}
          {labelFor("force_pass", t('hitl.forcePass'))}
        </button>
        <button
          className="icon-text-button"
          disabled={isSubmitting || isRedoing || redoDisabled}
          onClick={onRedo}
          type="button"
        >
          {activeDecision === "redo" ? (
            <Loader2 className="spin" size={15} aria-hidden />
          ) : (
            <RotateCcw size={15} aria-hidden />
          )}
          {labelFor("redo", t('hitl.redo'))}
        </button>
      </div>
    </section>
  );
}
