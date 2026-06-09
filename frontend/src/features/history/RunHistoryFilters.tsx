import { Filter, Search } from "lucide-react";
import type { RunStatus } from "../../api/types";

export type RunHistoryStatusFilter = RunStatus | "all";
export type RunHistoryModeFilter = "all" | "real" | "demo";
export type RunHistorySort = "updated_desc" | "created_desc" | "topic_asc";

export interface RunHistoryFilterState {
  mode: RunHistoryModeFilter;
  query: string;
  sort: RunHistorySort;
  status: RunHistoryStatusFilter;
}

export function RunHistoryFilters({
  filters,
  resultCount,
  setFilters,
}: {
  filters: RunHistoryFilterState;
  resultCount: number;
  setFilters: (filters: RunHistoryFilterState) => void;
}) {
  function update(next: Partial<RunHistoryFilterState>) {
    setFilters({ ...filters, ...next });
  }

  return (
    <section className="history-filter-panel" aria-label="Run history filters">
      <label className="history-search-control">
        <Search size={16} aria-hidden />
        <input
          onChange={(event) => update({ query: event.target.value })}
          placeholder="Search topic or run id"
          type="search"
          value={filters.query}
        />
      </label>
      <label>
        <Filter size={15} aria-hidden />
        <span>Status</span>
        <select onChange={(event) => update({ status: event.target.value as RunHistoryStatusFilter })} value={filters.status}>
          <option value="all">All status</option>
          <option value="completed">Completed</option>
          <option value="completed_with_blockers">Blocked</option>
          <option value="failed">Failed</option>
          <option value="running">Running</option>
          <option value="queued">Queued</option>
          <option value="interrupted">Interrupted</option>
        </select>
      </label>
      <label>
        <span>Mode</span>
        <select onChange={(event) => update({ mode: event.target.value as RunHistoryModeFilter })} value={filters.mode}>
          <option value="all">All modes</option>
          <option value="real">Real API</option>
          <option value="demo">Demo</option>
        </select>
      </label>
      <label>
        <span>Sort</span>
        <select onChange={(event) => update({ sort: event.target.value as RunHistorySort })} value={filters.sort}>
          <option value="updated_desc">Latest update</option>
          <option value="created_desc">Newest run</option>
          <option value="topic_asc">Topic A-Z</option>
        </select>
      </label>
      <strong>{resultCount.toLocaleString()} shown</strong>
    </section>
  );
}
