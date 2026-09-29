import { create } from "zustand";
import type { RunEvent } from "../api/sse_types";
import type { RunDetail } from "../api/types";

function detailFromEventRun(current: RunDetail | undefined, incoming: RunEvent["payload"]["run"]): RunDetail | undefined {
  if (!incoming) return current;
  if ("plan" in incoming && incoming.plan) return incoming as RunDetail;
  if (!current || incoming.id !== current.id) return current;
  return {
    ...current,
    status: incoming.status,
    ...("current_node" in incoming ? { current_node: incoming.current_node } : {}),
  };
}

function timestampMicroseconds(value: string): number {
  const milliseconds = Date.parse(value);
  if (!Number.isFinite(milliseconds)) return Number.NaN;
  const fraction = /\.(\d+)/.exec(value)?.[1] ?? "";
  return milliseconds * 1000 + Number(fraction.padEnd(6, "0").slice(3, 6));
}

function isNotNewerThanLoadedDetail(event: RunEvent, detail: RunDetail | undefined): boolean {
  if (!detail?.updated_at) return false;
  const eventTime = timestampMicroseconds(event.created_at);
  const detailTime = timestampMicroseconds(detail.updated_at);
  return Number.isFinite(eventTime) && Number.isFinite(detailTime) && eventTime <= detailTime;
}

interface RunState {
  detail?: RunDetail;
  events: RunEvent[];
  setDetail: (detail: RunDetail) => void;
  addEvent: (event: RunEvent) => void;
  reset: () => void;
}

function createRunStore() {
  return create<RunState>((set) => ({
  events: [],
  setDetail: (detail) => set({ detail }),
  addEvent: (event) =>
    set((state) => state.events.some((item) => item.id === event.id) ? state : ({
      events: [...state.events, event],
      detail:
        event.payload.run && !isNotNewerThanLoadedDetail(event, state.detail)
          ? detailFromEventRun(state.detail, event.payload.run)
          : event.type === "report_updated" && state.detail && !isNotNewerThanLoadedDetail(event, state.detail)
          ? {
              ...state.detail,
              report_md: Object.prototype.hasOwnProperty.call(event.payload, "report_md")
                ? String(event.payload.report_md ?? "")
                : state.detail.report_md ?? "",
              report_artifact: Object.prototype.hasOwnProperty.call(event.payload, "report_artifact")
                ? event.payload.report_artifact ?? null
                : state.detail.report_artifact ?? null,
            }
          : state.detail,
    })),
  reset: () => set({ detail: undefined, events: [] }),
}));
}

const sessions = new Map<string, ReturnType<typeof createRunStore>>();
export function getRunStore(runId: string) {
  let store = sessions.get(runId);
  if (!store) {
    store = createRunStore();
    sessions.set(runId, store);
  }
  return store;
}
