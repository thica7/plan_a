import type { RunEvent } from "../../api/sse_types";
import type { DecisionReplayReport, RunMetrics, TraceSpan } from "../../api/types";
import { ContextRows, DecisionReplaySection, EventList, SpanList, TraceMetricsBar } from "./TraceSections";
import { buildContextRows, formatDecisionPayload } from "./traceModel";
import { useTranslation } from "../../stores/i18n";

export { formatDecisionPayload };

interface Props {
  events: RunEvent[];
  metrics: RunMetrics;
  spans: TraceSpan[];
  replay?: DecisionReplayReport | null;
}

export function TraceList({ events, metrics, spans, replay }: Props) {
  const { t } = useTranslation();
  const contextRows = buildContextRows(spans);
  const toolSpanCount = spans.filter((span) => span.kind === "tool").length;

  return (
    <section className="panel trace-panel">
      <h2>{t('trace.title')}</h2>
      <TraceMetricsBar metrics={metrics} toolSpanCount={toolSpanCount} />
      <DecisionReplaySection replay={replay} />
      <ContextRows rows={contextRows} />
      <SpanList spans={spans} />
      <EventList events={events} />
    </section>
  );
}
