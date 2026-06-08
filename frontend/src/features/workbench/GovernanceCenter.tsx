import { CalendarClock, Database, Gauge, ShieldCheck } from "lucide-react";
import type {
  AuditLogRecord,
  DataRetentionReport,
  ModelPolicyReport,
  ModelRouteDecision,
  QualityAgentMatrix,
  SourceRegistryRecord,
  WorkspaceQuotaDecision,
  WorkspaceUsageSummary,
} from "../../api/types";
import { MetricCard, Panel } from "../../components/ui";
import { AuditTrail } from "./AuditTrail";
import { formatPercent } from "./format";

interface GovernanceCenterProps {
  auditLogs: AuditLogRecord[];
  matrix: QualityAgentMatrix | null;
  modelPolicy: ModelPolicyReport | null;
  modelRoute: ModelRouteDecision | null;
  quota: WorkspaceQuotaDecision | null;
  registry: SourceRegistryRecord[];
  retention: DataRetentionReport | null;
  usage: WorkspaceUsageSummary | null;
}

export function GovernanceCenter({
  auditLogs,
  matrix,
  modelPolicy,
  modelRoute,
  quota,
  registry,
  retention,
  usage,
}: GovernanceCenterProps) {
  return (
    <div className="dashboard-grid">
      <Panel title="Runtime policy" icon={<ShieldCheck size={16} aria-hidden />}>
        <div className="metric-grid compact">
          <MetricCard label="Model policy" value={modelPolicy?.status ?? "n/a"} tone={modelPolicy?.status === "pass" ? "good" : "warn"} />
          <MetricCard label="Route" value={modelRoute?.status ?? "n/a"} />
          <MetricCard label="Agent matrix" value={matrix?.status ?? "n/a"} tone={matrix?.status === "blocker" ? "warn" : "good"} />
          <MetricCard label="Quota" value={quota?.status ?? "n/a"} tone={quota?.allowed === false ? "warn" : "good"} />
        </div>
        <div className="recommendation-list compact">
          {(modelPolicy?.findings ?? []).slice(0, 4).map((finding) => (
            <article className={`recommendation-card ${finding.severity}`} key={finding.id}>
              <strong>{finding.category}</strong>
              <p>{finding.message}</p>
            </article>
          ))}
        </div>
      </Panel>

      <Panel title="Workspace usage" icon={<Gauge size={16} aria-hidden />}>
        <div className="metric-grid compact">
          <MetricCard label="Runs" value={`${usage?.run_count ?? 0}/${usage?.monthly_run_quota ?? 0}`} />
          <MetricCard label="Tokens" value={formatPercent(usage?.token_usage_ratio ?? 0)} tone={(usage?.token_usage_ratio ?? 0) > 1 ? "warn" : "neutral"} />
          <MetricCard label="Cost" value={`$${(usage?.cost_estimate_usd ?? 0).toFixed(2)}`} />
          <MetricCard label="Retention" value={retention?.status ?? "n/a"} tone={retention?.status === "fail" ? "warn" : "good"} />
        </div>
      </Panel>

      <Panel title="Source registry" icon={<Database size={16} aria-hidden />}>
        <div className="data-table source-registry-table">
          <div className="data-table-head">
            <span>Domain</span>
            <span>Trust</span>
            <span>Robots</span>
            <span>Review</span>
          </div>
          {registry.slice(0, 40).map((source) => (
            <article className="data-row" key={source.id}>
              <span>
                <strong>{source.display_name}</strong>
                <em>{source.domain}</em>
              </span>
              <span>{source.trust_level}</span>
              <span>{source.robots_status}</span>
              <span>{source.policy_review_status}</span>
            </article>
          ))}
        </div>
      </Panel>

      <Panel title="Audit trail" icon={<CalendarClock size={16} aria-hidden />}>
        <AuditTrail logs={auditLogs} />
      </Panel>
    </div>
  );
}
