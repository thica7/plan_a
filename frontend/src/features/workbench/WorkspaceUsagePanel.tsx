import { Gauge } from "lucide-react";
import type {
  DataRetentionReport,
  WorkspaceQuotaDecision,
  WorkspaceUsageSummary,
} from "../../api/types";
import { MetricCard, Panel, StatusPill } from "../../components/ui";
import { useTranslation } from "../../stores/i18n";
import { formatPercent } from "./format";

interface WorkspaceUsagePanelProps {
  quota: WorkspaceQuotaDecision | null;
  retention: DataRetentionReport | null;
  usage: WorkspaceUsageSummary | null;
}

export function WorkspaceUsagePanel({ quota, retention, usage }: WorkspaceUsagePanelProps) {
  const { t } = useTranslation();
  return (
    <Panel className="workspace-usage-panel" title={t('workbench.workspaceUsage')} icon={<Gauge size={16} aria-hidden />}>
      <div className="governance-status-row">
        <StatusPill tone={quota?.allowed === false || usage?.status === "exceeded" ? "bad" : usage?.status === "warn" ? "warn" : "good"}>
          {usage?.status ?? quota?.status ?? "n/a"}
        </StatusPill>
        <strong>{usage ? `${usage.run_count}/${usage.monthly_run_quota} ${t('workbench.runUsage')}` : t('workbench.usageUnavailable')}</strong>
      </div>

      <div className="metric-grid compact">
        <MetricCard label={t('workbench.runUsage')} value={usage ? formatPercent(usage.run_usage_ratio) : "n/a"} tone={(usage?.run_usage_ratio ?? 0) > 1 ? "warn" : "neutral"} />
        <MetricCard label={t('workbench.tokenUsage')} value={formatPercent(usage?.token_usage_ratio ?? 0)} tone={(usage?.token_usage_ratio ?? 0) > 1 ? "warn" : "neutral"} />
        <MetricCard label={t('workbench.costUsage')} value={`$${(usage?.cost_estimate_usd ?? 0).toFixed(2)}`} tone={(usage?.cost_usage_ratio ?? 0) > 1 ? "warn" : "neutral"} />
        <MetricCard label={t('workbench.retention')} value={retention?.status ?? "n/a"} tone={retention?.status === "fail" ? "warn" : "good"} />
      </div>

      <div className="usage-bars">
        <UsageBar label={t('workbench.runUsage')} value={usage?.run_usage_ratio ?? 0} />
        <UsageBar label={t('workbench.tokenUsage')} value={usage?.token_usage_ratio ?? 0} />
        <UsageBar label={t('workbench.costUsage')} value={usage?.cost_usage_ratio ?? 0} />
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
