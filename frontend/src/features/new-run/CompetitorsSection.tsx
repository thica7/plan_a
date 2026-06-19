import { Users } from "lucide-react";
import { useTranslation } from "../../stores/i18n";
import { SectionHeading } from "./SectionHeading";
import type { CompetitorMode } from "./types";

interface CompetitorsSectionProps {
  competitorMode: CompetitorMode;
  competitors: string;
  setCompetitorMode: (mode: CompetitorMode) => void;
  setCompetitors: (competitors: string) => void;
  updateManualMode: () => void;
}

export function CompetitorsSection({
  competitorMode,
  competitors,
  setCompetitorMode,
  setCompetitors,
  updateManualMode,
}: CompetitorsSectionProps) {
  const { t } = useTranslation();
  return (
    <section className="form-section">
      <SectionHeading
        icon={<Users size={17} aria-hidden />}
        index="03"
        meta={competitorMode === "auto" ? t('newRun.competitorsDesc') : t('newRun.manual')}
        title={t('newRun.competitors')}
      />
      <div className="segmented-control" role="radiogroup" aria-label={t('newRun.competitorsDesc')}>
        <button
          className={competitorMode === "auto" ? "active" : ""}
          type="button"
          onClick={() => setCompetitorMode("auto")}
        >
          {t('newRun.autoDiscover')}
        </button>
        <button
          className={competitorMode === "manual" ? "active" : ""}
          type="button"
          onClick={updateManualMode}
        >
          {t('newRun.manual')}
        </button>
      </div>
      {competitorMode === "manual" ? (
        <textarea
          aria-label={t('newRun.competitors')}
          value={competitors}
          onChange={(event) => setCompetitors(event.target.value)}
          rows={3}
        />
      ) : (
        <p className="scope-note">
          {t('newRun.competitorsPlanner')}
        </p>
      )}
    </section>
  );
}
