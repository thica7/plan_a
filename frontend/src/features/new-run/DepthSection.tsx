import { Layers3 } from "lucide-react";
import { useTranslation } from "../../stores/i18n";
import { SectionHeading } from "./SectionHeading";
import type { LayerSelection } from "./types";

interface DepthOption {
  layer: LayerSelection;
  label: string;
  detailKey: string;
}

const depthOptions: DepthOption[] = [
  { layer: "L1", label: "L1", detailKey: "newRun.overview" },
  { layer: "L2", label: "L2", detailKey: "newRun.deepDive" },
  { layer: "L3", label: "L3", detailKey: "newRun.comprehensive" },
];

export function DepthSection({
  selectedLayer,
  updateSelectedLayer,
}: {
  selectedLayer: LayerSelection;
  updateSelectedLayer: (layer: LayerSelection) => void;
}) {
  const { t } = useTranslation();
  return (
    <section className="form-section depth-section">
      <SectionHeading
        icon={<Layers3 size={17} aria-hidden />}
        index="05"
        meta={t('newRun.depthDesc')}
        title={t('newRun.depth')}
      />
      <div className="depth-option-grid" role="radiogroup" aria-label={t('newRun.depth')}>
        <button
          className={selectedLayer === "auto" ? "depth-option-card active" : "depth-option-card"}
          onClick={() => updateSelectedLayer("auto")}
          type="button"
        >
          <strong>{t('newRun.auto')}</strong>
          <span>{t('newRun.plannerSelects')}</span>
        </button>
        {depthOptions.map((option) => (
          <button
            className={selectedLayer === option.layer ? "depth-option-card active" : "depth-option-card"}
            key={option.layer}
            onClick={() => updateSelectedLayer(option.layer)}
            type="button"
          >
            <strong>{option.label}</strong>
            <span>{t(option.detailKey)}</span>
          </button>
        ))}
      </div>
      <p className="depth-helper">
        {t('newRun.depthHint')}
      </p>
    </section>
  );
}
