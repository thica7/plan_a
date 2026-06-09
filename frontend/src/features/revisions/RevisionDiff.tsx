import { GitCompareArrows } from "lucide-react";
import type { RevisionRecord } from "../../api/types";

interface RevisionDiffProps {
  compact?: boolean;
  revisions: RevisionRecord[];
}

export function RevisionDiff({ compact = false, revisions }: RevisionDiffProps) {
  const latest = revisions.length > 0 ? revisions[revisions.length - 1] : undefined;
  const targetCompetitors = latest?.target_competitors?.length
    ? latest.target_competitors.join(", ")
    : latest?.target_competitor || "all";
  const scopeLabel = latest
    ? `${latest.stage}:${targetCompetitors}/${latest.target_subagent || "all"}`
    : "";

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
              <strong>{scopeLabel}</strong>
              scope
            </span>
            <span>
              <strong>{latest.issue_ids.length}</strong>
              selected issues
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

          {compact ? (
            <div className="revision-compact-grid">
              <article>
                <strong>Before preview</strong>
                <p>{compactText(latest.before_md) || "No prior report body."}</p>
              </article>
              <article>
                <strong>After preview</strong>
                <p>{compactText(latest.after_md) || "No updated report body."}</p>
              </article>
            </div>
          ) : (
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
          )}
        </>
      )}
    </section>
  );
}

function compactText(markdown: string) {
  return markdown.replace(/\s+/g, " ").trim().slice(0, 520);
}
