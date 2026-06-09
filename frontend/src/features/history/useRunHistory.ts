import { useEffect, useMemo, useState } from "react";
import { listRuns } from "../../api/client";
import type { RunSummary } from "../../api/types";

export function useRunHistory() {
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
          if (run.status === "queued") summary.queued += 1;
          if (run.status === "running") summary.running += 1;
          if (run.status === "interrupted") summary.interrupted += 1;
          if (run.execution_mode === "real") summary.real += 1;
          if (run.execution_mode === "demo") summary.demo += 1;
          return summary;
        },
        { blocked: 0, completed: 0, demo: 0, failed: 0, interrupted: 0, queued: 0, real: 0, running: 0, total: 0 },
      ),
    [runs],
  );

  return { counts, isLoading, runs };
}
