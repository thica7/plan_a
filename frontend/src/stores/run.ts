import { create } from "zustand";
import type { RunEvent } from "../api/sse_types";
import type { RunDetail } from "../api/types";

interface RunState {
  detail?: RunDetail;
  events: RunEvent[];
  setDetail: (detail: RunDetail) => void;
  addEvent: (event: RunEvent) => void;
  reset: () => void;
}

export const useRunStore = create<RunState>((set) => ({
  events: [],
  setDetail: (detail) => set({ detail }),
  addEvent: (event) =>
    set((state) => ({
      events: state.events.some((item) => item.id === event.id)
        ? state.events
        : [...state.events, event],
      detail:
        event.payload.run
          ? (event.payload.run as RunDetail)
          : event.type === "report_updated" && state.detail
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
