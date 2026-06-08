import { Layers } from "lucide-react";
import type { ScenarioPack } from "../../api/types";
import { SectionHeading } from "./SectionHeading";
import { dynamicScenarioId, type LayerSelection } from "./types";

interface LensSectionProps {
  applyScenario: (pack: ScenarioPack | null) => void;
  dynamicScenarioSelected: boolean;
  scenarioId: string;
  scenarioPacks: ScenarioPack[];
  selected: string[];
  selectedLayer: LayerSelection;
  selectedScenario: ScenarioPack | null;
  setScenarioId: (scenarioId: string) => void;
  updateSelectedLayer: (layer: LayerSelection) => void;
}

export function LensSection({
  applyScenario,
  dynamicScenarioSelected,
  scenarioId,
  scenarioPacks,
  selected,
  selectedLayer,
  selectedScenario,
  setScenarioId,
  updateSelectedLayer,
}: LensSectionProps) {
  return (
    <section className="form-section">
      <SectionHeading
        icon={<Layers size={17} aria-hidden />}
        index="03"
        meta="L1 battlecard, L2 workflow, or L3 landscape"
        title="Lens"
      />
      <div className="field-grid">
        <fieldset>
          <legend>Competitive layer</legend>
          <div className="segmented-control" role="radiogroup" aria-label="Competitive layer">
            {(["auto", "L1", "L2", "L3"] as LayerSelection[]).map((layer) => (
              <button
                className={selectedLayer === layer ? "active" : ""}
                key={layer}
                type="button"
                onClick={() => updateSelectedLayer(layer)}
              >
                {layer === "auto" ? "Auto" : layer}
              </button>
            ))}
          </div>
        </fieldset>
        <label>
          Scenario pack
          <select
            value={scenarioId}
            onChange={(event) => {
              if (event.target.value === dynamicScenarioId) {
                setScenarioId(dynamicScenarioId);
                return;
              }
              const next = scenarioPacks.find((pack) => pack.id === event.target.value) ?? null;
              applyScenario(next);
            }}
          >
            <option value="">Auto scenario</option>
            <option value={dynamicScenarioId}>Dynamic scenario</option>
            {scenarioPacks
              .filter((pack) => selectedLayer === "auto" || pack.competitor_layer === selectedLayer)
              .map((pack) => (
                <option key={pack.id} value={pack.id}>
                  {pack.competitor_layer} / {pack.name}
                </option>
              ))}
          </select>
        </label>
      </div>
      {selectedScenario ? (
        <div className="scenario-preview">
          <strong>{selectedScenario.name}</strong>
          <span>{selectedScenario.description}</span>
          <div>
            {[...selectedScenario.required_dimensions, ...selectedScenario.optional_dimensions].map((dimension) => (
              <em key={dimension}>{dimension}</em>
            ))}
          </div>
          {selectedScenario.seed_competitors.length > 0 ? (
            <small>{selectedScenario.seed_competitors.join(", ")}</small>
          ) : null}
        </div>
      ) : dynamicScenarioSelected ? (
        <div className="scenario-preview">
          <strong>Dynamic scenario</strong>
          <span>Generated from the selected scope and dimensions.</span>
          <div>
            {selected.map((dimension) => (
              <em key={dimension}>{dimension}</em>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
