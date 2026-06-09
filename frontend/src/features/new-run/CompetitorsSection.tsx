import { Users } from "lucide-react";
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
  return (
    <section className="form-section">
      <SectionHeading
        icon={<Users size={17} aria-hidden />}
        index="03"
        meta={competitorMode === "auto" ? "planner discovery" : "manual list"}
        title="Competitors"
      />
      <div className="segmented-control" role="radiogroup" aria-label="Competitor mode">
        <button
          className={competitorMode === "auto" ? "active" : ""}
          type="button"
          onClick={() => setCompetitorMode("auto")}
        >
          Auto-discover
        </button>
        <button
          className={competitorMode === "manual" ? "active" : ""}
          type="button"
          onClick={updateManualMode}
        >
          Manual
        </button>
      </div>
      {competitorMode === "manual" ? (
        <textarea
          aria-label="Competitors"
          value={competitors}
          onChange={(event) => setCompetitors(event.target.value)}
          rows={3}
        />
      ) : (
        <p className="scope-note">
          Planner selects direct competitors before evidence collection.
        </p>
      )}
    </section>
  );
}
