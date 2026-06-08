import { CheckCircle2, ShieldCheck, RotateCcw } from "lucide-react";

interface Props {
  message: string;
  isRedoing: boolean;
  redoDisabled: boolean;
  onAccept: () => void;
  onForcePass: () => void;
  onRedo: () => void;
}

export function QaReviewModal({ message, isRedoing, redoDisabled, onAccept, onForcePass, onRedo }: Props) {
  return (
    <section className="hitl-panel">
      <div>
        <h2>QA review</h2>
        <p>{message}</p>
      </div>
      <div className="hitl-actions">
        <button className="icon-text-button" onClick={onAccept} type="button">
          <CheckCircle2 size={15} aria-hidden />
          Accept
        </button>
        <button className="icon-text-button" onClick={onForcePass} type="button">
          <ShieldCheck size={15} aria-hidden />
          Force pass
        </button>
        <button className="icon-text-button" disabled={isRedoing || redoDisabled} onClick={onRedo} type="button">
          <RotateCcw size={15} aria-hidden />
          Redo
        </button>
      </div>
    </section>
  );
}
