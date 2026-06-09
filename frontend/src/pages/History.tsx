import { useMemo, useState } from "react";
import type { RunSummary } from "../api/types";
import { RunHistoryFilters, type RunHistoryFilterState } from "../features/history/RunHistoryFilters";
import { RunHistorySummary } from "../features/history/RunHistorySummary";
import { RunHistoryTable } from "../features/history/RunHistoryTable";
import { useRunHistory } from "../features/history/useRunHistory";

export function HistoryPage() {
  const { counts, isLoading, runs } = useRunHistory();
  const [filters, setFilters] = useState<RunHistoryFilterState>({
    mode: "all",
    query: "",
    sort: "updated_desc",
    status: "all",
  });
  const filteredRuns = useMemo(() => filterRuns(runs, filters), [filters, runs]);
  const latestUpdatedAt = useMemo(() => {
    const latest = runs
      .map((run) => run.updated_at)
      .filter(Boolean)
      .sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0];
    return latest ?? null;
  }, [runs]);

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

      <RunHistorySummary counts={counts} latestUpdatedAt={latestUpdatedAt} />
      <RunHistoryFilters filters={filters} resultCount={filteredRuns.length} setFilters={setFilters} />
      <RunHistoryTable isFiltered={filteredRuns.length !== runs.length} isLoading={isLoading} runs={filteredRuns} />
    </section>
  );
}

function filterRuns(runs: RunSummary[], filters: RunHistoryFilterState) {
  const query = filters.query.trim().toLowerCase();
  return runs
    .filter((run) => (filters.status === "all" ? true : run.status === filters.status))
    .filter((run) => (filters.mode === "all" ? true : run.execution_mode === filters.mode))
    .filter((run) => {
      if (!query) return true;
      return `${run.topic} ${run.id} ${run.project_id ?? ""}`.toLowerCase().includes(query);
    })
    .slice()
    .sort((a, b) => {
      if (filters.sort === "topic_asc") return a.topic.localeCompare(b.topic);
      if (filters.sort === "created_desc") return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
    });
}
