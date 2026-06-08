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
          return summary;
        },
        { blocked: 0, completed: 0, failed: 0, total: 0 },
      ),
    [runs],
  );

  return { counts, isLoading, runs };
}
