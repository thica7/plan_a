import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import { useTranslation } from '../../stores/i18n';
import { displayLabel } from "../../i18n/display";
import type { RunDetail as RunDetailRecord } from "../../api/types";

interface RunDetailHeaderProps {
  detail: RunDetailRecord;
  recommendedDimensions: string[];
}

export function RunDetailHeader({ detail, recommendedDimensions }: RunDetailHeaderProps) {
  const { locale, t } = useTranslation();
  const targetName = detail.plan.target_product?.name;
  const verifiedHomepage = targetName && detail.plan.homepage_verified?.[targetName]
    ? detail.plan.homepage_hints?.[targetName]
    : null;
  return (
    <header className="page-header page-header-split">
      <div>
        <h1>{detail.topic}</h1>
        {detail.plan.target_product ? (
          <div className="target-product-context">
            <strong>{detail.plan.target_product.name}</strong>
            {detail.plan.target_product.category ? <span>{detail.plan.target_product.category}</span> : null}
            {detail.plan.target_product_evidence ? (
              <a href={verifiedHomepage || detail.plan.target_product_evidence.source_url} rel="noreferrer" target="_blank">
                {verifiedHomepage
                  ? t('runHeader.homepageVerified')
                  : detail.plan.target_product_evidence.status === "verified"
                    ? t('runHeader.productMentioned')
                    : t('runHeader.homepageUnverified')}
              </a>
            ) : <span>{t('runHeader.homepagePending')}</span>}
          </div>
        ) : null}
        <p>
          {detail.plan.competitors.join(` ${t('runHeader.versus')} `)} / {detail.plan.dimensions.map((dimension) => displayLabel(dimension, locale)).join(", ")} /{" "}
          {displayLabel(detail.execution_mode, locale)}
        </p>
        <div className="run-meta-row">
          <span>{t('runHeader.layer')} {displayLabel(detail.plan.competitor_layer, locale)}</span>
          <span>{t('runHeader.scenario')} {displayLabel(detail.plan.scenario_id ?? "auto", locale)}</span>
          <span>{t('runHeader.qaRules')} {detail.plan.qa_rule_ids.length}</span>
          <span>{t('runHeader.tasks')} {detail.plan.task_decomposition.length}</span>
          {detail.plan.qa_rule_ids.slice(0, 4).map((ruleId) => (
            <span key={ruleId} title={ruleId}>{displayLabel(ruleId, locale)}</span>
          ))}
          {recommendedDimensions.length > 0 ? (
            <span>{t('runHeader.recommended')} {recommendedDimensions.map((dimension) => displayLabel(dimension, locale)).join(", ")}</span>
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
        {displayLabel(detail.status, locale)}
      </div>
    </header>
  );
}
