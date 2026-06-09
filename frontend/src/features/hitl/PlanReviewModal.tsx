import { CheckCircle2, SlidersHorizontal } from "lucide-react";

interface Props {
  message: string;
  canApplyDimensions: boolean;
  dimensions: string;
  onDimensionsChange: (value: string) => void;
  onAccept: () => void;
  onApply: () => void;
}

export function PlanReviewModal({
  message,
  canApplyDimensions,
  dimensions,
  onDimensionsChange,
  onAccept,
  onApply,
}: Props) {
  return (
    <section className="hitl-panel">
      <div>
        <h2>Plan review</h2>
        <p>{message}</p>
      </div>
      <label>
        Dimensions
        <input value={dimensions} onChange={(event) => onDimensionsChange(event.target.value)} />
        <span className="hitl-field-note">
          {canApplyDimensions ? "Edited dimensions will replace the planner scope." : "No dimension changes detected."}
        </span>
      </label>
      <div className="hitl-actions">
        <button className="icon-text-button" onClick={onAccept} type="button">
          <CheckCircle2 size={15} aria-hidden />
          Continue current plan
        </button>
        <button
          className="icon-text-button"
          disabled={!canApplyDimensions}
          onClick={onApply}
          title={canApplyDimensions ? "Apply edited dimensions and resume" : "Edit dimensions to enable this action"}
          type="button"
        >
          <SlidersHorizontal size={15} aria-hidden />
          Apply edited dimensions
        </button>
      </div>
    </section>
  );
}
