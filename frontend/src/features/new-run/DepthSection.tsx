import { Layers3 } from "lucide-react";
import { SectionHeading } from "./SectionHeading";
import type { LayerSelection } from "./types";

interface DepthOption {
  layer: LayerSelection;
  label: string;
  detail: string;
}

const depthOptions: DepthOption[] = [
  {
    layer: "L1",
    label: "L1",
    detail: "Overview",
  },
  {
    layer: "L2",
    label: "L2",
    detail: "Deep Dive",
  },
  {
    layer: "L3",
    label: "L3",
    detail: "Comprehensive",
  },
];

export function DepthSection({
  selectedLayer,
  updateSelectedLayer,
}: {
  selectedLayer: LayerSelection;
  updateSelectedLayer: (layer: LayerSelection) => void;
}) {
  return (
    <section className="form-section depth-section">
      <SectionHeading
        icon={<Layers3 size={17} aria-hidden />}
        index="05"
        meta="how deep each competitor should be analyzed"
        title="Depth"
      />
      <div className="depth-option-grid" role="radiogroup" aria-label="Competitive depth">
        <button
          className={selectedLayer === "auto" ? "depth-option-card active" : "depth-option-card"}
          onClick={() => updateSelectedLayer("auto")}
          type="button"
        >
          <strong>Auto</strong>
          <span>Planner selects</span>
        </button>
        {depthOptions.map((option) => (
          <button
            className={selectedLayer === option.layer ? "depth-option-card active" : "depth-option-card"}
            key={option.layer}
            onClick={() => updateSelectedLayer(option.layer)}
            type="button"
          >
            <strong>{option.label}</strong>
            <span>{option.detail}</span>
          </button>
        ))}
      </div>
      <p className="depth-helper">
        Higher depth increases collection breadth, source validation, and report detail.
      </p>
    </section>
  );
}
