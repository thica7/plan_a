import { ShieldCheck } from "lucide-react";
import { useTranslation } from '../../stores/i18n';
import type {
  ModelPolicyReport,
  ModelRouteDecision,
  QualityAgentMatrix,
  WorkspaceQuotaDecision,
} from "../../api/types";
import { MetricCard, Panel, StatusPill } from "../../components/ui";

interface RuntimePolicyPanelProps {
  matrix: QualityAgentMatrix | null;
  modelPolicy: ModelPolicyReport | null;
  modelRoute: ModelRouteDecision | null;
  quota: WorkspaceQuotaDecision | null;
}

export function RuntimePolicyPanel({
  matrix,
  modelPolicy,
  modelRoute,
  quota,
}: RuntimePolicyPanelProps) {
  const { t } = useTranslation();
  return (
    <Panel className="runtime-policy-panel" title={t('workbench.runtimePolicy')} icon={<ShieldCheck size={16} aria-hidden />}>
      <div className="governance-status-row">
        <StatusPill tone={modelPolicy?.status === "pass" ? "good" : modelPolicy?.status === "fail" ? "bad" : "warn"}>
          {modelPolicy?.status ?? "n/a"}
        </StatusPill>
        <strong>{modelRoute?.selected?.model_name ?? modelRoute?.fallback?.model_name ?? t('workbench.noModelRoute')}</strong>
        <span>{modelPolicy?.policy_version ?? modelRoute?.routing_policy_version ?? "policy unavailable"}</span>
      </div>

      <div className="metric-grid compact">
        <MetricCard label={t('workbench.route')} value={modelRoute?.status ?? "n/a"} tone={modelRoute?.status === "blocked" ? "warn" : "neutral"} />
        <MetricCard label={t('workbench.agentMatrix')} value={matrix?.status ?? "n/a"} tone={matrix?.status === "blocker" ? "warn" : "good"} />
        <MetricCard label={t('workbench.quota')} value={quota?.status ?? "n/a"} tone={quota?.allowed === false ? "warn" : "good"} />
        <MetricCard label={t('compliance.findings')} value={modelPolicy?.finding_count ?? 0} tone={(modelPolicy?.blocker_count ?? 0) > 0 ? "warn" : "neutral"} />
      </div>

      <div className="policy-finding-list">
        {(modelPolicy?.findings ?? []).slice(0, 4).map((finding) => (
          <article className={`recommendation-card ${finding.severity}`} key={finding.id}>
            <strong>{finding.category}</strong>
            <p>{finding.message}</p>
          </article>
        ))}
        {modelRoute?.blocked_reasons.slice(0, 2).map((reason) => (
          <article className="recommendation-card blocker" key={reason}>
            <strong>route</strong>
            <p>{reason}</p>
          </article>
        ))}
      </div>
    </Panel>
  );
}
