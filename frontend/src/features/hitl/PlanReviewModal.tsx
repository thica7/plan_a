import { CheckCircle2, Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { useTranslation } from '../../stores/i18n';
import { displayLabel } from "../../i18n/display";
import { SystemMessage } from "../../i18n/SystemMessage";
import type {
  CompetitorReviewDecision,
  CompetitorReviewRow,
} from "../run-detail/planReview";

interface Props {
  message: string;
  canApplyChanges: boolean;
  competitorRows: CompetitorReviewRow[];
  dimensions: string;
  onAddCompetitor: () => void;
  onCompetitorDecisionChange: (id: string, decision: CompetitorReviewDecision) => void;
  onCompetitorNameChange: (id: string, name: string) => void;
  onCompetitorNoteChange: (id: string, note: string) => void;
  onDeleteCompetitor: (id: string) => void;
  onDimensionsChange: (value: string) => void;
  onAccept: () => void;
  onApply: () => void;
}

export function PlanReviewModal({
  message,
  canApplyChanges,
  competitorRows,
  dimensions,
  onAddCompetitor,
  onCompetitorDecisionChange,
  onCompetitorNameChange,
  onCompetitorNoteChange,
  onDeleteCompetitor,
  onDimensionsChange,
  onAccept,
  onApply,
}: Props) {
  const { locale, t } = useTranslation();

  return (
    <section className="hitl-panel">
      <div>
        <h2>{t('hitl.planReview')}</h2>
        <p><SystemMessage message={message} /></p>
      </div>
      <label>
        {t('hitl.dimensionIdentifiers')}
        <input aria-label={t('hitl.dimensionIdentifiers')} value={dimensions} onChange={(event) => onDimensionsChange(event.target.value)} />
        <span className="hitl-field-note">
          {canApplyChanges ? t('hitl.editedPlanReplace') : t('hitl.noPlanChanges')}
        </span>
        <span className="hitl-field-note">{t('hitl.dimensionsHint')}</span>
        <span>{dimensions.split(',').map((dimension) => displayLabel(dimension.trim(), locale)).join('、')}</span>
      </label>
      <div className="competitor-review-panel">
        <div className="competitor-review-heading">
          <div>
            <strong>{t('newRun.competitors')}</strong>
            <span>{t('hitl.reviewCompetitors')}</span>
          </div>
          <button className="icon-text-button" onClick={onAddCompetitor} type="button">
            <Plus size={15} aria-hidden />
            {t('common.add')}
          </button>
        </div>
        <div className="competitor-review-table-wrap">
          <table className="competitor-review-table">
            <thead>
              <tr>
                <th>{t('knowledge.competitor')}</th>
                <th>{t('hitl.decision')}</th>
                <th>{t('hitl.confidence')}</th>
                <th>{t('hitl.evidenceReason')}</th>
                <th>{t('hitl.reviewerNote')}</th>
                <th aria-label={t('common.actions')} />
              </tr>
            </thead>
            <tbody>
              {competitorRows.map((row, index) => (
                <tr key={row.id} className={row.decision !== "keep" ? "muted-row" : undefined}>
                  <td>
                    <input
                      aria-label={t('hitl.competitorName').replace('{index}', String(index + 1))}
                      value={row.name}
                      onChange={(event) => onCompetitorNameChange(row.id, event.target.value)}
                      placeholder={t('common.name')}
                    />
                    {row.manual ? <span className="manual-chip">{t('newRun.manual')}</span> : null}
                  </td>
                  <td>
                    <select
                      aria-label={t('hitl.competitorDecision').replace('{index}', String(index + 1))}
                      value={row.decision}
                      onChange={(event) =>
                        onCompetitorDecisionChange(
                          row.id,
                          event.target.value as CompetitorReviewDecision,
                        )
                      }
                    >
                      <option value="keep">{displayLabel('keep', locale)}</option>
                      <option value="remove">{displayLabel('remove', locale)}</option>
                      <option value="mark_unrelated">{displayLabel('mark_unrelated', locale)}</option>
                    </select>
                  </td>
                  <td>
                    <span className="confidence-pill">{row.confidenceLabel ? displayLabel(row.confidenceLabel, locale) : t('newRun.manual')}</span>
                  </td>
                  <td>
                    <div className="competitor-evidence-cell">
                      {row.rationale ? <span>{row.rationale}</span> : <span>{t('hitl.noRationale')}</span>}
                      {row.evidenceUrls.length ? (
                        <div>
                          {row.evidenceUrls.slice(0, 2).map((url, evidenceIndex) => (
                            <a href={url} key={url} rel="noreferrer" target="_blank">
                              {row.evidenceTitles[evidenceIndex] || `${t('common.source')} ${evidenceIndex + 1}`}
                            </a>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </td>
                  <td>
                    <input
                      aria-label={t('hitl.competitorNote').replace('{index}', String(index + 1))}
                      value={row.note}
                      onChange={(event) => onCompetitorNoteChange(row.id, event.target.value)}
                      placeholder={t('hitl.reasonOrSource')}
                    />
                  </td>
                  <td>
                    <button
                      aria-label={t('hitl.removeCompetitor').replace('{name}', row.name || t('knowledge.competitor'))}
                      className="icon-button"
                      onClick={() => onDeleteCompetitor(row.id)}
                      title={t('hitl.removeFromReview')}
                      type="button"
                    >
                      <Trash2 size={15} aria-hidden />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      <div className="hitl-actions">
        <button className="icon-text-button" onClick={onAccept} type="button">
          <CheckCircle2 size={15} aria-hidden />
          {t('hitl.continuePlan')}
        </button>
        <button
          className="icon-text-button"
          disabled={!canApplyChanges}
          onClick={onApply}
          title={canApplyChanges ? t('hitl.applyAndResume') : t('hitl.editToEnable')}
          type="button"
        >
          <SlidersHorizontal size={15} aria-hidden />
          {t('hitl.applyEdited')}
        </button>
      </div>
    </section>
  );
}
