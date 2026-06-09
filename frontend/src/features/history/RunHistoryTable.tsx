import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Clock3, Loader2 } from "lucide-react";
import type { RunSummary } from "../../api/types";
import { useTranslation } from "../../stores/i18n";
import { formatDate, statusClass } from "./format";

export function RunHistoryTable({
  isFiltered,
  isLoading,
  runs,
}: {
  isFiltered: boolean;
  isLoading: boolean;
  runs: RunSummary[];
}) {
  const { t } = useTranslation();
  return (
    <section className="panel history-panel">
      <div className="panel-heading-row">
        <h2>{t('history.ledger')}</h2>
        {isLoading ? <Loader2 className="spin" size={16} aria-hidden /> : null}
      </div>
      {runs.length === 0 && !isLoading ? (
        <div className="empty-state compact">
          <Clock3 size={18} aria-hidden />
          <p>{isFiltered ? t('history.noMatch') : t('history.noRunsBackend')}</p>
        </div>
      ) : (
        <div className="history-table">
          <div className="history-row history-row-header" role="row">
            <span aria-hidden />
            <span>{t('history.run')}</span>
            <span>{t('history.gate')}</span>
            <span>{t('history.mode')}</span>
            <span>{t('history.updated')}</span>
          </div>
          {runs.map((run) => (
            <Link className="history-row" to={`/runs/${run.id}`} key={run.id}>
              <span className={`status-dot ${statusClass(run.status)}`}>
                {run.status === "completed" ? (
                  <CheckCircle2 size={15} aria-hidden />
                ) : run.status === "failed" || run.status === "completed_with_blockers" ? (
                  <AlertTriangle size={15} aria-hidden />
                ) : (
                  <Clock3 size={15} aria-hidden />
                )}
              </span>
              <span>
                <strong>{run.topic}</strong>
                <em>{run.id}</em>
              </span>
              <span className={`flow-status ${run.status}`}>
                {run.status === "completed_with_blockers" ? "blocked" : run.status}
              </span>
              <span>{run.execution_mode}</span>
              <time dateTime={run.updated_at}>{formatDate(run.updated_at)}</time>
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
