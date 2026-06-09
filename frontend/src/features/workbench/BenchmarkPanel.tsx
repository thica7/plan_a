import { Gauge } from "lucide-react";
import type { EvalOpsReport } from "../../api/types";
import { MetricCard, Panel } from "../../components/ui";
import { formatPercent } from "./format";

interface BenchmarkPanelProps {
  evalOps: EvalOpsReport | null;
}

export function BenchmarkPanel({ evalOps }: BenchmarkPanelProps) {
  return (
    <Panel className="benchmark-panel" title="Benchmark panel" icon={<Gauge size={16} aria-hidden />}>
      <div className="benchmark-score">
        <strong>{evalOps?.report_quality_score ?? "n/a"}</strong>
        <span>report quality</span>
      </div>
      <div className="metric-grid compact">
        <MetricCard label="Runs evaluated" value={evalOps?.run_count ?? "n/a"} />
        <MetricCard label="Golden pass" value={evalOps ? formatPercent(evalOps.golden_set_pass_rate) : "n/a"} />
        <MetricCard label="Time saved" value={evalOps ? `${evalOps.manual_time_saved_hours.toFixed(1)}h` : "n/a"} />
        <MetricCard
          label="Gate"
          value={evalOps?.regression_gate_status ?? "n/a"}
          tone={evalOps?.regression_gate_status === "fail" ? "warn" : "good"}
        />
      </div>
      <div className="recommendation-list compact">
        {(evalOps?.recommendations ?? []).slice(0, 4).map((item) => (
          <article className="recommendation-card medium" key={item}>
            <strong>Next</strong>
            <p>{item}</p>
          </article>
        ))}
      </div>
    </Panel>
  );
}
