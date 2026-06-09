import type { ReactNode } from "react";
import { Activity, AlertTriangle, CheckCircle2, Clock3, RadioTower } from "lucide-react";
import { MetricCard, Panel, StatusPill } from "../../components/ui";
import { formatDate } from "./format";

export interface RunHistoryCounts {
  blocked: number;
  completed: number;
  demo: number;
  failed: number;
  interrupted: number;
  queued: number;
  real: number;
  running: number;
  total: number;
}

export function RunHistorySummary({
  counts,
  latestUpdatedAt,
}: {
  counts: RunHistoryCounts;
  latestUpdatedAt: string | null;
}) {
  const activeRuns = counts.queued + counts.running + counts.interrupted;
  const attentionRuns = counts.blocked + counts.failed;
  const healthyRate = counts.total ? Math.round((counts.completed / counts.total) * 100) : 0;
  const realRate = counts.total ? Math.round((counts.real / counts.total) * 100) : 0;

  return (
    <section className="history-summary-grid" aria-label="Run status and quality summary">
      <Panel className="history-quality-panel" title="Run quality">
        <div className="history-quality-score">
          <span>
            <CheckCircle2 size={18} aria-hidden />
          </span>
          <div>
            <strong>{healthyRate}%</strong>
            <em>Completed without blockers</em>
          </div>
          <StatusPill tone={attentionRuns ? "warn" : "good"}>{attentionRuns ? "review" : "clean"}</StatusPill>
        </div>
        <div className="history-quality-breakdown">
          <QualityLine icon={<CheckCircle2 size={15} aria-hidden />} label="Completed" value={counts.completed} />
          <QualityLine icon={<AlertTriangle size={15} aria-hidden />} label="Blocked / failed" value={attentionRuns} />
          <QualityLine icon={<Activity size={15} aria-hidden />} label="Active" value={activeRuns} />
          <QualityLine icon={<RadioTower size={15} aria-hidden />} label="Real API" value={`${realRate}%`} />
        </div>
      </Panel>

      <div className="history-metric-grid">
        <MetricCard label="Runs" value={counts.total} />
        <MetricCard label="Completed" value={counts.completed} tone="good" />
        <MetricCard label="Need review" value={attentionRuns} tone={attentionRuns ? "warn" : "neutral"} />
        <MetricCard label="Real / demo" value={`${counts.real}/${counts.demo}`} />
      </div>
      <Panel className="history-freshness-panel" title="Freshness">
        <div className="history-freshness-body">
          <Clock3 size={18} aria-hidden />
          <div>
            <strong>{latestUpdatedAt ? formatDate(latestUpdatedAt) : "No runs yet"}</strong>
            <span>Latest run update</span>
          </div>
        </div>
      </Panel>
    </section>
  );
}

function QualityLine({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: number | string;
}) {
  return (
    <span className="history-quality-line">
      {icon}
      <em>{label}</em>
      <strong>{value}</strong>
    </span>
  );
}
