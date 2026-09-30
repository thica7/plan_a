import { Gauge } from "lucide-react";
import type { EvalOpsReport } from "../../api/types";
import { MetricCard, Panel } from "../../components/ui";
import { formatPercent } from "./format";
import { useTranslation } from '../../stores/i18n';
import { displayLabel } from '../../i18n/display';
import { SystemMessage } from '../../i18n/SystemMessage';

interface BenchmarkPanelProps {
  evalOps: EvalOpsReport | null;
}

export function BenchmarkPanel({ evalOps }: BenchmarkPanelProps) {
  const { t, locale } = useTranslation();
  return (
    <Panel className="benchmark-panel" title={t('workbench.benchmark')} icon={<Gauge size={16} aria-hidden />}>
      <div className="benchmark-score">
        <strong>{evalOps?.report_quality_score ?? displayLabel('n/a', locale)}</strong>
        <span>{t('runQuality.reportQuality')}</span>
      </div>
      <div className="metric-grid compact">
        <MetricCard label={t('workbench.runsEvaluated')} value={evalOps?.run_count ?? displayLabel('n/a', locale)} />
        <MetricCard label={t('workbench.goldenPass')} value={evalOps ? formatPercent(evalOps.golden_set_pass_rate) : displayLabel('n/a', locale)} />
        <MetricCard label={t('workbench.timeSaved')} value={evalOps ? `${evalOps.manual_time_saved_hours.toFixed(1)} ${t('common.hours')}` : displayLabel('n/a', locale)} />
        <MetricCard
          label={t('runQuality.gate')}
          value={displayLabel(evalOps?.regression_gate_status ?? "n/a", locale)}
          tone={evalOps?.regression_gate_status === "fail" ? "warn" : "good"}
        />
      </div>
      <div className="recommendation-list compact">
        {(evalOps?.recommendations ?? []).slice(0, 4).map((item) => (
          <article className="recommendation-card medium" key={item}>
            <strong>{t('workbench.next')}</strong>
            <p><SystemMessage message={item} /></p>
          </article>
        ))}
      </div>
    </Panel>
  );
}
