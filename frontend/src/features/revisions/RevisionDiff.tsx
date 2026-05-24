import { GitCompareArrows } from "lucide-react";
import type { RevisionRecord } from "../../api/types";

interface RevisionDiffProps {
  revisions: RevisionRecord[];
}

export function RevisionDiff({ revisions }: RevisionDiffProps) {
  const latest = revisions.length > 0 ? revisions[revisions.length - 1] : undefined;

  return (
    <section className="panel revision-panel">
      <div className="panel-heading-row">
        <h2>Revision loop</h2>
        <GitCompareArrows size={17} aria-hidden />
      </div>

      {!latest ? (
        <p>No revisions yet.</p>
      ) : (
        <>
          <div className="revision-metrics">
            <span>
              <strong>{latest.iteration}</strong>
              iteration
            </span>
            <span>
              <strong>{latest.stage}</strong>
              scope
            </span>
            <span>
              <strong>{`${latest.issue_count_before} -> ${latest.issue_count_after}`}</strong>
              QA issues
            </span>
            <span>
              <strong>{latest.convergence_ratio.toFixed(2)}</strong>
              convergence
            </span>
          </div>

          <div className="revision-diff-grid">
            <article>
              <strong>Before</strong>
              <pre>{latest.before_md || "No prior report body."}</pre>
            </article>
            <article>
              <strong>After</strong>
              <pre>{latest.after_md || "No updated report body."}</pre>
            </article>
          </div>
        </>
      )}
    </section>
  );
}
