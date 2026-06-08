import type { RunDetailView } from "./types";

const runDetailViews: RunDetailView[] = ["overview", "report", "agents", "quality"];

export function RunDetailTabs({
  activeView,
  onChange,
}: {
  activeView: RunDetailView;
  onChange: (view: RunDetailView) => void;
}) {
  return (
    <nav className="module-tabs run-detail-tabs" aria-label="Run detail sections">
      {runDetailViews.map((view) => (
        <button
          className={activeView === view ? "active" : ""}
          key={view}
          type="button"
          onClick={() => onChange(view)}
        >
          {view}
        </button>
      ))}
    </nav>
  );
}
