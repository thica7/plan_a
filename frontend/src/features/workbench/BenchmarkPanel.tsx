import { Gauge } from "lucide-react";
import type { EvalOpsReport } from "../../api/types";
import { MetricCard, Panel } from "../../components/ui";
import { formatPercent } from "./format";
import { useTranslation } from '../../stores/i18n';

interface BenchmarkPanelProps {
  evalOps: EvalOpsReport | null;
}

export function BenchmarkPanel({ evalOps }: BenchmarkPanelProps) {
  const { t } = useTranslation();
  return (
    <Panel className="benchmark-panel" title={t('workbench.benchmark')} icon={<Gauge size={16} aria-hidden />}>
      <div className="benchmark-score">
        <strong>{evalOps?.report_quality_score ?? "n/a"}</strong>
        <span>report quality</span>
      </div>
      <div className="metric-grid compact">
        <MetricCard label={t('workbench.runsEvaluated')} value={evalOps?.run_count ?? "n/a"} />
        <MetricCard label={t('workbench.goldenPass')} value={evalOps ? formatPercent(evalOps.golden_set_pass_rate) : "n/a"} />
        <MetricCard label={t('workbench.timeSaved')} value={evalOps ? `${evalOps.manual_time_saved_hours.toFixed(1)}h` : "n/a"} />
        <MetricCard
          label="Gate"
          value={evalOps?.regression_gate_status ?? "n/a"}
          tone={evalOps?.regression_gate_status === "fail" ? "warn" : "good"}
        />
      </div>
      <div className="recommendation-list compact">
        {(evalOps?.recommendations ?? []).slice(0, 4).map((item) => (
          <article className="recommendation-card medium" key={item}>
            <strong>{t('workbench.next')}</strong>
            <p>{item}</p>
          </article>
        ))}
      </div>
    </Panel>
  );
}
