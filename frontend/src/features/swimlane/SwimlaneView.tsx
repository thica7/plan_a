import type { RunEvent } from "../../api/sse_types";
import type { RunStatus, TraceSpan } from "../../api/types";
import { useTranslation } from "../../stores/i18n";

interface Props {
  events: RunEvent[];
  currentNode?: string | null;
  spans?: TraceSpan[];
  status?: RunStatus;
}

const lanes = ["planner", "collector", "analyst", "comparator", "reflector", "writer", "qa"];

export function SwimlaneView({ events, currentNode, spans = [], status }: Props) {
  const { t } = useTranslation();
  const useLiveEvents = isLiveStatus(status) || events.length > 0;
  const latestActive =
    [...events].reverse().find((event) => event.type === "node_started" && event.agent)?.agent || currentNode;
  return (
    <section className="panel swimlane-panel">
      <div className="panel-heading-row">
        <h2>{t('swimlane.title')}</h2>
        <span className="panel-kicker">{useLiveEvents ? `${events.length} events` : `${spans.length} trace spans`}</span>
      </div>
      <div className="swimlane-grid">
        {lanes.map((lane) => {
          const laneEvents = events.filter((event) => event.agent === lane);
          const laneSpans = spans.filter((span) => span.agent === lane || span.subagent === lane);
          const items = useLiveEvents
            ? laneEvents.map((event) => ({
                id: `event-${event.id}`,
                className: event.type,
                label: event.message,
              }))
            : laneSpans.map((span) => ({
                id: `span-${span.id}`,
                className: `span-${span.kind} ${span.status}`,
                label: `${span.name} / ${span.status}`,
              }));
          const visibleItems = items.slice(0, 36);
          const hiddenCount = Math.max(items.length - visibleItems.length, 0);
          return (
            <div className={latestActive === lane ? "lane active" : "lane"} key={lane}>
              <span className="lane-title">{lane}</span>
              <div className="bubble-row">
                {visibleItems.map((item) => (
                  <span className={`event-bubble ${item.className}`} key={item.id} title={item.label} />
                ))}
                {hiddenCount > 0 ? <span className="lane-overflow">+{hiddenCount}</span> : null}
                {items.length === 0 ? <span className="lane-empty">0</span> : null}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function isLiveStatus(status?: RunStatus) {
  return status === "queued" || status === "running" || status === "interrupted";
}
