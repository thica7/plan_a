interface RunHistoryCounts {
  blocked: number;
  completed: number;
  failed: number;
  total: number;
}

export function RunHistorySummary({ counts }: { counts: RunHistoryCounts }) {
  return (
    <section className="run-command-grid">
      <article className="panel">
        <div className="metric-grid compact">
          <Metric label="Completed" value={counts.completed} />
          <Metric label="Blocked" value={counts.blocked} />
          <Metric label="Failed" value={counts.failed} />
        </div>
      </article>
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
