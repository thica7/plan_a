import { GitCompareArrows } from "lucide-react";
import type { RevisionRecord } from "../../api/types";
import { useTranslation } from '../../stores/i18n';
import { displayLabel } from "../../i18n/display";

interface RevisionDiffProps {
  compact?: boolean;
  revisions: RevisionRecord[];
}

export function RevisionDiff({ compact = false, revisions }: RevisionDiffProps) {
  const { locale, t } = useTranslation();
  const latest = revisions.length > 0 ? revisions[revisions.length - 1] : undefined;
  const targetCompetitors = latest?.target_competitors?.length
    ? latest.target_competitors.join(", ")
    : latest?.target_competitor || t('common.all');
  const scopeLabel = latest
    ? `${displayLabel(latest.stage, locale)}:${targetCompetitors}/${latest.target_subagent ? displayLabel(latest.target_subagent, locale) : t('common.all')}`
    : "";

  return (
    <section className="panel revision-panel">
      <div className="panel-heading-row">
        <h2>{t('revisions.title')}</h2>
        <GitCompareArrows size={17} aria-hidden />
      </div>

      {!latest ? (
        <p>{t('revisions.noRevisions')}</p>
      ) : (
        <>
          <div className="revision-metrics">
            <span>
              <strong>{latest.iteration}</strong>
              {t('revisions.iteration')}
            </span>
            <span>
              <strong>{scopeLabel}</strong>
              {t('newRun.scope')}
            </span>
            <span>
              <strong>{latest.issue_ids.length}</strong>
              {t('revisions.selectedIssues')}
            </span>
            <span>
              <strong>{`${latest.issue_count_before} -> ${latest.issue_count_after}`}</strong>
              {t('summary.qaIssues')}
            </span>
            <span>
              <strong>{latest.convergence_ratio.toFixed(2)}</strong>
              {t('revisions.convergence')}
            </span>
          </div>

          {compact ? (
            <div className="revision-compact-grid">
              <article>
                <strong>{t('revisions.beforePreview')}</strong>
                <p>{compactText(latest.before_md) || t('revisions.noPriorReport')}</p>
              </article>
              <article>
                <strong>{t('revisions.afterPreview')}</strong>
                <p>{compactText(latest.after_md) || t('revisions.noUpdatedReport')}</p>
              </article>
            </div>
          ) : (
            <div className="revision-diff-grid">
              <article>
                <strong>{t('revisions.before')}</strong>
                <pre>{latest.before_md || t('revisions.noPriorReport')}</pre>
              </article>
              <article>
                <strong>{t('revisions.after')}</strong>
                <pre>{latest.after_md || t('revisions.noUpdatedReport')}</pre>
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
