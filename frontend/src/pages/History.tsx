import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listRuns } from "../api/client";
import type { RunSummary } from "../api/types";

export function HistoryPage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);

  useEffect(() => {
    listRuns().then(setRuns).catch(() => setRuns([]));
  }, []);

  return (
    <section className="work-surface">
      <header className="page-header">
        <div>
          <h1>Run history</h1>
          <p>Local in-memory runs for the current backend process.</p>
        </div>
      </header>
      <div className="history-list">
        {runs.map((run) => (
          <Link to={`/runs/${run.id}`} key={run.id}>
            <strong>{run.topic}</strong>
            <span>{run.status}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}
