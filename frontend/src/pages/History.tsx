import { RunHistorySummary } from "../features/history/RunHistorySummary";
import { RunHistoryTable } from "../features/history/RunHistoryTable";
import { useRunHistory } from "../features/history/useRunHistory";

export function HistoryPage() {
  const { counts, isLoading, runs } = useRunHistory();

  return (
    <section className="work-surface history-page">
      <header className="page-header page-header-split">
        <div>
          <h1>Run history</h1>
          <p>Recent intelligence runs from the active orchestration and storage backend.</p>
        </div>
        <div className="header-stat">
          <strong>{counts.total}</strong>
          <span>runs</span>
        </div>
      </header>

      <RunHistorySummary counts={counts} />
      <RunHistoryTable isLoading={isLoading} runs={runs} />
    </section>
  );
}
