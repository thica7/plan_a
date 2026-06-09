import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import type { RunDetail as RunDetailRecord } from "../../api/types";

interface RunDetailHeaderProps {
  detail: RunDetailRecord;
  recommendedDimensions: string[];
}

export function RunDetailHeader({ detail, recommendedDimensions }: RunDetailHeaderProps) {
  return (
    <header className="page-header page-header-split">
      <div>
        <h1>{detail.topic}</h1>
        <p>
          {detail.plan.competitors.join(" vs ")} / {detail.plan.dimensions.join(", ")} /{" "}
          {detail.execution_mode}
        </p>
        <div className="run-meta-row">
          <span>Layer {detail.plan.competitor_layer}</span>
          <span>Scenario {detail.plan.scenario_id ?? "auto"}</span>
          <span>QA rules {detail.plan.qa_rule_ids.length}</span>
          <span>Tasks {detail.plan.task_decomposition.length}</span>
          {detail.plan.qa_rule_ids.slice(0, 4).map((ruleId) => (
            <span key={ruleId}>{ruleId}</span>
          ))}
          {recommendedDimensions.length > 0 ? (
            <span>Recommended {recommendedDimensions.join(", ")}</span>
          ) : null}
        </div>
      </div>
      <div className={`status-chip ${detail.status}`}>
        {detail.status === "completed" ? (
          <CheckCircle2 size={16} aria-hidden />
        ) : detail.status === "completed_with_blockers" ? (
          <AlertTriangle size={16} aria-hidden />
        ) : (
          <Loader2 size={16} aria-hidden />
        )}
        {detail.status === "completed_with_blockers" ? "completed, blocked" : detail.status}
      </div>
    </header>
  );
}
