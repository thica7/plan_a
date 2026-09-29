import { Layers } from "lucide-react";
import type { ScenarioPack } from "../../api/types";
import { useTranslation } from '../../stores/i18n';
import { displayLabel, runtimeDiagnostic } from "../../i18n/display";
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
  const { locale, t } = useTranslation();
  return (
    <section className="form-section">
      <SectionHeading
        icon={<Layers size={17} aria-hidden />}
        index="02"
        meta={t('newRun.scenarioDesc')}
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
                {displayLabel(pack.competitor_layer, locale)} / {displayLabel(pack.name, locale)}
              </option>
            ))}
        </select>
      </label>
      {selectedScenario ? (
        <div className="scenario-preview">
          <strong>{displayLabel(selectedScenario.name, locale)}</strong>
          <span>{runtimeDiagnostic(selectedScenario.description, locale)}</span>
          <div>
            {[...selectedScenario.required_dimensions, ...selectedScenario.optional_dimensions].map((dimension) => (
              <em key={dimension}>{displayLabel(dimension, locale)}</em>
            ))}
          </div>
          {selectedScenario.seed_competitors.length > 0 ? (
            <small>{selectedScenario.seed_competitors.join(", ")}</small>
          ) : null}
        </div>
      ) : dynamicScenarioSelected ? (
        <div className="scenario-preview">
          <strong>{t('newRun.dynamicScenario')}</strong>
          <span>{t('newRun.scenarioHint')}</span>
          <div>
            {selected.map((dimension) => (
              <em key={dimension}>{displayLabel(dimension, locale)}</em>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
