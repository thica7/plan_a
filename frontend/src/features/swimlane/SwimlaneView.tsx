import type { RunEvent } from "../../api/sse_types";

interface Props {
  events: RunEvent[];
  currentNode?: string | null;
}

const lanes = ["planner", "collector", "analyst", "comparator", "reflector", "writer", "qa"];

export function SwimlaneView({ events, currentNode }: Props) {
  const latestActive =
    [...events].reverse().find((event) => event.type === "node_started" && event.agent)?.agent || currentNode;
  return (
    <section className="panel swimlane-panel">
      <h2>Live swimlane</h2>
      <div className="swimlane-grid">
        {lanes.map((lane) => {
          const laneEvents = events.filter((event) => event.agent === lane);
          return (
            <div className={latestActive === lane ? "lane active" : "lane"} key={lane}>
              <span className="lane-title">{lane}</span>
              <div className="bubble-row">
                {laneEvents.map((event) => (
                  <span className={`event-bubble ${event.type}`} key={event.id} title={event.message} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
