import { RotateCcw } from "lucide-react";
import type { RunDetail as RunDetailRecord } from "../../api/types";
import type { ReflectionItem } from "./types";
import { useTranslation } from '../../stores/i18n';
import { displayLabel } from "../../i18n/display";
import { SystemMessage } from "../../i18n/SystemMessage";

interface RunQaPanelProps {
  detail: RunDetailRecord;
  isRedoing: boolean;
  onRedo: () => void;
  redoLimitReached: boolean;
  reflectionItems: ReflectionItem[];
}

export function RunQaPanel({
  detail,
  isRedoing,
  onRedo,
  redoLimitReached,
  reflectionItems,
}: RunQaPanelProps) {
  const { locale, t } = useTranslation();
  return (
    <aside className="qa-panel">
      <div className="panel-heading-row">
        <h2>{t('runQa.title')}</h2>
        {detail.qa_findings.length > 0 ? (
          <button
            className="icon-text-button"
            disabled={isRedoing || redoLimitReached}
            onClick={onRedo}
            title={redoLimitReached ? t('runQa.maxRedoReached') : t('runQa.redoScoped')}
            type="button"
          >
            <RotateCcw size={15} aria-hidden />
            {redoLimitReached ? t('runQa.limitReached') : t('runQa.redo')}
          </button>
        ) : null}
      </div>
      {detail.qa_findings.length > 0 ? (
        <p className="muted-text">
          {t('runQa.redoRounds')} {detail.revisions.length}/{detail.max_iterations}
        </p>
      ) : null}
      {detail.qa_findings.length === 0 ? (
        <p>{t('runQa.noFindings')}</p>
      ) : (
        detail.qa_findings.map((issue) => (
          <article key={issue.id} className="issue-row">
            <strong>{displayLabel(issue.severity, locale)}</strong>
            <SystemMessage message={issue.problem} />
            <code>
              {displayLabel(issue.redo_scope.kind, locale)}:
              {issue.redo_scope.target_competitors?.length
                ? `${issue.redo_scope.target_competitors.join(", ")}/`
                : issue.redo_scope.target_competitor
                  ? `${issue.redo_scope.target_competitor}/`
                  : ""}
              {issue.redo_scope.target_subagent ? displayLabel(issue.redo_scope.target_subagent, locale) : t('common.all')}
            </code>
          </article>
        ))
      )}
      {reflectionItems.length > 0 ? (
        <div className="reflection-review">
          <h3>{t('runQa.reflectorReview')}</h3>
          {reflectionItems.map((item) => (
            <article key={`${item.kind}-${item.index}`} className="issue-row reflection-row">
              <strong>{displayLabel(item.kind, locale)}</strong>
              <span>{item.text}</span>
            </article>
          ))}
        </div>
      ) : null}
    </aside>
  );
}
