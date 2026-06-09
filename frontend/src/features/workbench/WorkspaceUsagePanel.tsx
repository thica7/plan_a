import { Gauge } from "lucide-react";
import type {
  DataRetentionReport,
  WorkspaceQuotaDecision,
  WorkspaceUsageSummary,
} from "../../api/types";
import { MetricCard, Panel, StatusPill } from "../../components/ui";
import { formatPercent } from "./format";

interface WorkspaceUsagePanelProps {
  quota: WorkspaceQuotaDecision | null;
  retention: DataRetentionReport | null;
  usage: WorkspaceUsageSummary | null;
}

export function WorkspaceUsagePanel({ quota, retention, usage }: WorkspaceUsagePanelProps) {
  return (
    <Panel className="workspace-usage-panel" title="Workspace usage" icon={<Gauge size={16} aria-hidden />}>
      <div className="governance-status-row">
        <StatusPill tone={quota?.allowed === false || usage?.status === "exceeded" ? "bad" : usage?.status === "warn" ? "warn" : "good"}>
          {usage?.status ?? quota?.status ?? "n/a"}
        </StatusPill>
        <strong>{usage ? `${usage.run_count}/${usage.monthly_run_quota} runs` : "Usage unavailable"}</strong>
        <span>{quota?.enforcement ? `${quota.enforcement} enforcement` : quota?.reason ?? "quota policy"}</span>
      </div>

      <div className="metric-grid compact">
        <MetricCard label="Runs" value={usage ? formatPercent(usage.run_usage_ratio) : "n/a"} tone={(usage?.run_usage_ratio ?? 0) > 1 ? "warn" : "neutral"} />
        <MetricCard label="Tokens" value={formatPercent(usage?.token_usage_ratio ?? 0)} tone={(usage?.token_usage_ratio ?? 0) > 1 ? "warn" : "neutral"} />
        <MetricCard label="Cost" value={`$${(usage?.cost_estimate_usd ?? 0).toFixed(2)}`} tone={(usage?.cost_usage_ratio ?? 0) > 1 ? "warn" : "neutral"} />
        <MetricCard label="Retention" value={retention?.status ?? "n/a"} tone={retention?.status === "fail" ? "warn" : "good"} />
      </div>

      <div className="usage-bars">
        <UsageBar label="Run usage" value={usage?.run_usage_ratio ?? 0} />
        <UsageBar label="Token usage" value={usage?.token_usage_ratio ?? 0} />
        <UsageBar label="Cost usage" value={usage?.cost_usage_ratio ?? 0} />
      </div>
    </Panel>
  );
}

function UsageBar({ label, value }: { label: string; value: number }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div className="usage-bar">
      <span>
        {label}
        <strong>{pct}%</strong>
      </span>
      <i aria-hidden>
        <b style={{ width: `${pct}%` }} />
      </i>
    </div>
  );
}
