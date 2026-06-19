import { Layers } from "lucide-react";
import type { ScenarioPack } from "../../api/types";
import { useTranslation } from '../../stores/i18n';
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
}: LensSectionProps) {
  const { t } = useTranslation();
  return (
    <section className="form-section">
      <SectionHeading
        icon={<Layers size={17} aria-hidden />}
        index="02"
        meta="predefined research scenario and scope"
        title={t('newRun.scenario')}
      />
      <label>
        {t('newRun.scenarioPack')}
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
           <option value="">{t('newRun.autoScenario')}</option>
          <option value={dynamicScenarioId}>{t('newRun.dynamicScenario')}</option>
          {scenarioPacks
            .filter((pack) => selectedLayer === "auto" || pack.competitor_layer === selectedLayer)
            .map((pack) => (
              <option key={pack.id} value={pack.id}>
                {pack.competitor_layer} / {pack.name}
              </option>
            ))}
        </select>
      </label>
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
          <strong>{t('newRun.dynamicScenario')}</strong>
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
