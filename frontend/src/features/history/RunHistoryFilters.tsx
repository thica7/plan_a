import { Filter, Search } from "lucide-react";
import type { RunStatus } from "../../api/types";
import { useTranslation } from "../../stores/i18n";

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
  const { t } = useTranslation();
  function update(next: Partial<RunHistoryFilterState>) {
    setFilters({ ...filters, ...next });
  }

  return (
    <section className="history-filter-panel" aria-label={t('history.filters')}>
      <label className="history-search-control">
        <Search size={16} aria-hidden />
        <input
          onChange={(event) => update({ query: event.target.value })}
          placeholder={t('history.search')}
          type="search"
          value={filters.query}
        />
      </label>
      <label>
        <Filter size={15} aria-hidden />
        <span>{t('history.status')}</span>
        <select onChange={(event) => update({ status: event.target.value as RunHistoryStatusFilter })} value={filters.status}>
          <option value="all">{t('history.allStatus')}</option>
          <option value="completed">{t('common.completed')}</option>
          <option value="completed_with_blockers">{t('common.blocked')}</option>
          <option value="failed">{t('common.failed')}</option>
          <option value="running">{t('common.running')}</option>
          <option value="queued">{t('history.queued')}</option>
          <option value="interrupted">{t('history.interrupted')}</option>
        </select>
      </label>
      <label>
        <span>{t('history.mode')}</span>
        <select onChange={(event) => update({ mode: event.target.value as RunHistoryModeFilter })} value={filters.mode}>
          <option value="all">{t('history.allModes')}</option>
          <option value="real">{t('history.realApi')}</option>
          <option value="demo">{t('history.demo')}</option>
        </select>
      </label>
      <label>
        <span>{t('history.sort')}</span>
        <select onChange={(event) => update({ sort: event.target.value as RunHistorySort })} value={filters.sort}>
          <option value="updated_desc">{t('history.latestUpdate')}</option>
          <option value="created_desc">{t('history.newestRun')}</option>
          <option value="topic_asc">{t('history.topicAZ')}</option>
        </select>
      </label>
      <strong>{resultCount.toLocaleString()} {t('common.shown')}</strong>
    </section>
  );
}
