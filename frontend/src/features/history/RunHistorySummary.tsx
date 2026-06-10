import type { ReactNode } from "react";
import { Activity, AlertTriangle, CheckCircle2, Clock3, RadioTower } from "lucide-react";
import { MetricCard, Panel, StatusPill } from "../../components/ui";
import { useTranslation } from "../../stores/i18n";
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
  const { t } = useTranslation();
  const activeRuns = counts.queued + counts.running + counts.interrupted;
  const attentionRuns = counts.blocked + counts.failed;
  const healthyRate = counts.total ? Math.round((counts.completed / counts.total) * 100) : 0;
  const realRate = counts.total ? Math.round((counts.real / counts.total) * 100) : 0;

  return (
    <section className="history-summary-grid" aria-label={t('history.runQuality')}>
      <Panel className="history-quality-panel" title={t('history.runQuality')}>
        <div className="history-quality-score">
          <span>
            <CheckCircle2 size={18} aria-hidden />
          </span>
          <div>
            <strong>{healthyRate}%</strong>
            <em>{t('history.completedNoBlocks')}</em>
          </div>
          <StatusPill tone={attentionRuns ? "warn" : "good"}>{attentionRuns ? t('history.needReview') : t('history.clean')}</StatusPill>
        </div>
        <div className="history-quality-breakdown">
          <QualityLine icon={<CheckCircle2 size={15} aria-hidden />} label={t('common.completed')} value={counts.completed} />
          <QualityLine icon={<AlertTriangle size={15} aria-hidden />} label={`${t('common.blocked')} / ${t('common.failed')}`} value={attentionRuns} />
          <QualityLine icon={<Activity size={15} aria-hidden />} label={t('common.active')} value={activeRuns} />
          <QualityLine icon={<RadioTower size={15} aria-hidden />} label={t('history.realApi')} value={`${realRate}%`} />
        </div>
      </Panel>

      <div className="history-metric-grid">
        <MetricCard label={t('history.runs')} value={counts.total} />
        <MetricCard label={t('common.completed')} value={counts.completed} tone="good" />
        <MetricCard label={t('history.needReview')} value={attentionRuns} tone={attentionRuns ? "warn" : "neutral"} />
        <MetricCard label={t('history.realDemo')} value={`${counts.real}/${counts.demo}`} />
      </div>
      <Panel className="history-freshness-panel" title={t('history.freshness')}>
        <div className="history-freshness-body">
          <Clock3 size={18} aria-hidden />
          <div>
            <strong>{latestUpdatedAt ? formatDate(latestUpdatedAt) : t('history.noRuns')}</strong>
            <span>{t('history.latestRunUpdate')}</span>
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
