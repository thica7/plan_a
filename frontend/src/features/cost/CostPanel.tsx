import type { RunMetrics, TraceSpan } from "../../api/types";
import { useTranslation } from "../../stores/i18n";

interface Props {
  metrics: RunMetrics;
  spans: TraceSpan[];
}

export function CostPanel({ metrics, spans }: Props) {
  const { t } = useTranslation();
  const rows = buildCostRows(spans);
  const maxCost = Math.max(...rows.map((row) => row.cost), 0.000001);

  return (
    <section className="panel cost-panel">
      <div className="panel-heading-row">
        <h2>{t('cost.title')}</h2>
        <strong>${metrics.cost_estimate_usd.toFixed(6)}</strong>
      </div>
      <div className="cost-summary">
        <span>
          {t('cost.input')}
          <strong>{metrics.input_tokens_estimate}</strong>
        </span>
        <span>
          {t('cost.output')}
          <strong>{metrics.output_tokens_estimate}</strong>
        </span>
        <span>
          {t('cost.llm')}
          <strong>{metrics.llm_calls}</strong>
        </span>
      </div>
      <div className="cost-bars">
        {rows.length === 0 ? (
          <p>{t('cost.noTraces')}</p>
        ) : (
          rows.map((row) => (
            <article key={row.agent}>
              <div>
                <strong>{row.agent}</strong>
                <span>
                  ${row.cost.toFixed(6)} / {row.tokens} {t('cost.tokens')}
                </span>
              </div>
              <meter max={maxCost} min={0} value={row.cost} />
            </article>
          ))
        )}
      </div>
    </section>
  );
}


interface CostRow {
  agent: string;
  cost: number;
  tokens: number;
}

function buildCostRows(spans: TraceSpan[]): CostRow[] {
  const rows = new Map<string, CostRow>();
  for (const span of spans) {
    const agent = span.subagent ? `${span.agent}/${span.subagent}` : span.agent;
    const row = rows.get(agent) ?? { agent, cost: 0, tokens: 0 };
    row.cost += span.cost_estimate_usd;
    row.tokens += span.input_tokens_estimate + span.output_tokens_estimate;
    rows.set(agent, row);
  }
  return [...rows.values()]
    .filter((row) => row.cost > 0 || row.tokens > 0)
    .sort((left, right) => right.cost - left.cost)
    .slice(0, 8);
}
