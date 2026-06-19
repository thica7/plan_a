import { RotateCcw } from "lucide-react";
import type { RunDetail as RunDetailRecord } from "../../api/types";
import type { ReflectionItem } from "./types";
import { useTranslation } from '../../stores/i18n';

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
  const { t } = useTranslation();
  return (
    <aside className="qa-panel">
      <div className="panel-heading-row">
        <h2>{t('runQa.title')}</h2>
        {detail.qa_findings.length > 0 ? (
          <button
            className="icon-text-button"
            disabled={isRedoing || redoLimitReached}
            onClick={onRedo}
            title={redoLimitReached ? "Maximum redo iterations reached" : "Redo scoped issue"}
            type="button"
          >
            <RotateCcw size={15} aria-hidden />
            {redoLimitReached ? t('runQa.limitReached') : t('runQa.redo')}
          </button>
        ) : null}
      </div>
      {detail.qa_findings.length > 0 ? (
        <p className="muted-text">
          Redo rounds {detail.revisions.length}/{detail.max_iterations}
        </p>
      ) : null}
      {detail.qa_findings.length === 0 ? (
        <p>{t('runQa.noFindings')}</p>
      ) : (
        detail.qa_findings.map((issue) => (
          <article key={issue.id} className="issue-row">
            <strong>{issue.severity}</strong>
            <span>{issue.problem}</span>
            <code>
              {issue.redo_scope.kind}:
              {issue.redo_scope.target_competitors?.length
                ? `${issue.redo_scope.target_competitors.join(", ")}/`
                : issue.redo_scope.target_competitor
                  ? `${issue.redo_scope.target_competitor}/`
                  : ""}
              {issue.redo_scope.target_subagent || "all"}
            </code>
          </article>
        ))
      )}
      {reflectionItems.length > 0 ? (
        <div className="reflection-review">
          <h3>Reflector review</h3>
          {reflectionItems.map((item) => (
            <article key={`${item.kind}-${item.index}`} className="issue-row reflection-row">
              <strong>{item.kind}</strong>
              <span>{item.text}</span>
            </article>
          ))}
        </div>
      ) : null}
    </aside>
  );
}
