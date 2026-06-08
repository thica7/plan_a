import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Clock3, Loader2 } from "lucide-react";
import { listRuns } from "../api/client";
import type { RunStatus, RunSummary } from "../api/types";

export function HistoryPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [isLoading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    listRuns()
      .then((items) => {
        if (active) setRuns(items);
      })
      .catch(() => {
        if (active) setRuns([]);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const counts = useMemo(
    () =>
      runs.reduce(
        (summary, run) => {
          summary.total += 1;
          if (run.status === "completed") summary.completed += 1;
          if (run.status === "completed_with_blockers") summary.blocked += 1;
          if (run.status === "failed") summary.failed += 1;
          return summary;
        },
        { blocked: 0, completed: 0, failed: 0, total: 0 },
      ),
    [runs],
  );

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

      <section className="run-command-grid">
        <article className="panel">
          <div className="metric-grid compact">
            <Metric label="Completed" value={counts.completed} />
            <Metric label="Blocked" value={counts.blocked} />
            <Metric label="Failed" value={counts.failed} />
          </div>
        </article>
      </section>

      <section className="panel history-panel">
        <div className="panel-heading-row">
          <h2>Runs</h2>
          {isLoading ? <Loader2 className="spin" size={16} aria-hidden /> : null}
        </div>
        {runs.length === 0 && !isLoading ? (
          <div className="empty-state compact">
            <Clock3 size={18} aria-hidden />
            <p>No runs returned by the backend.</p>
          </div>
        ) : (
          <div className="history-table">
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
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <span>
      <i aria-hidden />
      <strong>{value}</strong>
      <em>{label}</em>
    </span>
  );
}

function statusClass(status: RunStatus) {
  if (status === "completed") return "good";
  if (status === "failed" || status === "completed_with_blockers") return "warn";
  return "neutral";
}

function formatDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
