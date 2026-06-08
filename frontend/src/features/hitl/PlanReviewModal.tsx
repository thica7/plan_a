import { CheckCircle2, SlidersHorizontal } from "lucide-react";

interface Props {
  message: string;
  dimensions: string;
  onDimensionsChange: (value: string) => void;
  onAccept: () => void;
  onApply: () => void;
}

export function PlanReviewModal({ message, dimensions, onDimensionsChange, onAccept, onApply }: Props) {
  return (
    <section className="hitl-panel">
      <div>
        <h2>Plan review</h2>
        <p>{message}</p>
      </div>
      <label>
        Dimensions
        <input value={dimensions} onChange={(event) => onDimensionsChange(event.target.value)} />
      </label>
      <div className="hitl-actions">
        <button className="icon-text-button" onClick={onAccept} type="button">
          <CheckCircle2 size={15} aria-hidden />
          Continue
        </button>
        <button className="icon-text-button" onClick={onApply} type="button">
          <SlidersHorizontal size={15} aria-hidden />
          Apply dimensions
        </button>
      </div>
    </section>
  );
}
