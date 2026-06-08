interface RunHistoryCounts {
  blocked: number;
  completed: number;
  failed: number;
  total: number;
}

export function RunHistorySummary({ counts }: { counts: RunHistoryCounts }) {
  return (
    <section className="panel history-summary-panel">
      <div className="metric-grid compact">
        <Metric label="Completed" value={counts.completed} />
        <Metric label="Blocked" value={counts.blocked} />
        <Metric label="Failed" value={counts.failed} />
      </div>
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
