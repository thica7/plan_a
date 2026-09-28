import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { useTranslation } from '../../stores/i18n';
import type { RunDetail as RunDetailRecord } from "../../api/types";

interface RunDetailHeaderProps {
  detail: RunDetailRecord;
  recommendedDimensions: string[];
}

export function RunDetailHeader({ detail, recommendedDimensions }: RunDetailHeaderProps) {
  const { t } = useTranslation();
  return (
    <header className="page-header page-header-split">
      <div>
        <h1>{detail.topic}</h1>
        {detail.plan.target_product ? (
          <div className="target-product-context">
            <strong>{detail.plan.target_product.name}</strong>
            {detail.plan.target_product.category ? <span>{detail.plan.target_product.category}</span> : null}
            {detail.plan.target_product_evidence ? (
              <a href={detail.plan.target_product_evidence.source_url} rel="noreferrer" target="_blank">
                {detail.plan.target_product_evidence.status === "verified" ? "官网已核验" : "官网待核验"}
              </a>
            ) : <span>官网资料待核验</span>}
          </div>
        ) : null}
        <p>
          {detail.plan.competitors.join(" vs ")} / {detail.plan.dimensions.join(", ")} /{" "}
          {detail.execution_mode}
        </p>
        <div className="run-meta-row">
          <span>{t('runHeader.layer')} {detail.plan.competitor_layer}</span>
          <span>{t('runHeader.scenario')} {detail.plan.scenario_id ?? "auto"}</span>
          <span>QA rules {detail.plan.qa_rule_ids.length}</span>
          <span>{t('runHeader.tasks')} {detail.plan.task_decomposition.length}</span>
          {detail.plan.qa_rule_ids.slice(0, 4).map((ruleId) => (
            <span key={ruleId}>{ruleId}</span>
          ))}
          {recommendedDimensions.length > 0 ? (
            <span>{t('runHeader.recommended')} {recommendedDimensions.join(", ")}</span>
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
