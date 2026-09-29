import { Gauge } from "lucide-react";
import { useTranslation } from "../../stores/i18n";
import { SectionHeading } from "./SectionHeading";
import { depthBudgets, type ResearchDepth } from "./types";

const depths: ResearchDepth[] = ["quick", "standard", "deep"];

export function ResearchDepthSection({
  researchDepth,
  setResearchDepth,
}: {
  researchDepth: ResearchDepth;
  setResearchDepth: (depth: ResearchDepth) => void;
}) {
  const { t } = useTranslation();
  return (
    <section className="form-section research-depth-section">
      <SectionHeading
        icon={<Gauge size={17} aria-hidden />}
        index="06"
        meta={t("newRun.researchDepthDesc")}
        title={t("newRun.researchDepth")}
      />
      <div className="research-depth-grid" role="group" aria-label={t("newRun.researchDepth")}>
        {depths.map((depth) => {
          const budget = depthBudgets[depth];
          const summary = t("newRun.depthBudget")
            .replace("{competitors}", String(budget.competitors))
            .replace("{slices}", String(budget.slices))
            .replace("{sources}", String(budget.sources))
            .replace("{calls}", String(budget.llmCalls));
          return (
            <button
              aria-pressed={researchDepth === depth}
              className={researchDepth === depth ? "research-depth-card active" : "research-depth-card"}
              data-action-audit="local"
              data-action-id={`new-run.research-depth.${depth}`}
              key={depth}
              onClick={() => setResearchDepth(depth)}
              type="button"
            >
              <strong>{t(`newRun.researchDepth.${depth}`)}</strong>
              <span>{summary}</span>
            </button>
          );
        })}
      </div>
      <p className="depth-helper">{t("newRun.researchDepthHint")}</p>
    </section>
  );
}
