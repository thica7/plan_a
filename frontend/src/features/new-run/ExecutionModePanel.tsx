import { CalendarClock, KeyRound, Zap } from "lucide-react";
import { SectionHeading } from "./SectionHeading";
import type { ExecutionMode } from "./types";

interface ExecutionModePanelProps {
  executionMode: ExecutionMode;
  setExecutionMode: (mode: ExecutionMode) => void;
}

export function ExecutionModePanel({
  executionMode,
  setExecutionMode,
}: ExecutionModePanelProps) {
  return (
    <section className="form-section execution-section">
      <SectionHeading
        icon={<Zap size={17} aria-hidden />}
        index="06"
        meta="how this run will execute"
        title="Execution Mode"
      />
      <div className="execution-mode-grid" role="radiogroup" aria-label="Execution mode">
        <button
          className={executionMode === "real" ? "execution-mode-card active" : "execution-mode-card"}
          onClick={() => setExecutionMode("real")}
          type="button"
        >
          <KeyRound size={18} aria-hidden />
          <span>
            <strong>Real-time API</strong>
            <em>Execute now with live data collection</em>
          </span>
          <i aria-hidden />
        </button>
        <button
          className={executionMode === "demo" ? "execution-mode-card active" : "execution-mode-card"}
          onClick={() => setExecutionMode("demo")}
          type="button"
        >
          <CalendarClock size={18} aria-hidden />
          <span>
            <strong>Demo mode</strong>
            <em>Use deterministic fixtures for interface review</em>
          </span>
          <i aria-hidden />
        </button>
      </div>
    </section>
  );
}
