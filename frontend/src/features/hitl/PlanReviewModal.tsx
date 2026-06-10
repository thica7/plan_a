import { CheckCircle2, Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { useTranslation } from '../../stores/i18n';
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
  const { t } = useTranslation();

  return (
    <section className="hitl-panel">
      <div>
        <h2>{t('hitl.planReview')}</h2>
        <p>{message}</p>
      </div>
      <label>
        Dimensions
        <input value={dimensions} onChange={(event) => onDimensionsChange(event.target.value)} />
        <span className="hitl-field-note">
          {canApplyChanges ? "Edited plan will replace the planner scope." : "No plan changes detected."}
        </span>
      </label>
      <div className="competitor-review-panel">
        <div className="competitor-review-heading">
          <div>
            <strong>Competitors</strong>
            <span>Review discovered competitors before collection starts.</span>
          </div>
          <button className="icon-text-button" onClick={onAddCompetitor} type="button">
            <Plus size={15} aria-hidden />
            Add
          </button>
        </div>
        <div className="competitor-review-table-wrap">
          <table className="competitor-review-table">
            <thead>
              <tr>
                <th>Competitor</th>
                <th>Decision</th>
                <th>Confidence</th>
                <th>Why / evidence</th>
                <th>Reviewer note</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {competitorRows.map((row, index) => (
                <tr key={row.id} className={row.decision !== "keep" ? "muted-row" : undefined}>
                  <td>
                    <input
                      aria-label={`Competitor ${index + 1} name`}
                      value={row.name}
                      onChange={(event) => onCompetitorNameChange(row.id, event.target.value)}
                      placeholder="Name"
                    />
                    {row.manual ? <span className="manual-chip">Manual</span> : null}
                  </td>
                  <td>
                    <select
                      aria-label={`Competitor ${index + 1} decision`}
                      value={row.decision}
                      onChange={(event) =>
                        onCompetitorDecisionChange(
                          row.id,
                          event.target.value as CompetitorReviewDecision,
                        )
                      }
                    >
                      <option value="keep">Keep</option>
                      <option value="remove">Remove</option>
                      <option value="mark_unrelated">Unrelated</option>
                    </select>
                  </td>
                  <td>
                    <span className="confidence-pill">{row.confidenceLabel || "Manual"}</span>
                  </td>
                  <td>
                    <div className="competitor-evidence-cell">
                      {row.rationale ? <span>{row.rationale}</span> : <span>No system rationale</span>}
                      {row.evidenceUrls.length ? (
                        <div>
                          {row.evidenceUrls.slice(0, 2).map((url, evidenceIndex) => (
                            <a href={url} key={url} rel="noreferrer" target="_blank">
                              {row.evidenceTitles[evidenceIndex] || `Source ${evidenceIndex + 1}`}
                            </a>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </td>
                  <td>
                    <input
                      aria-label={`Competitor ${index + 1} note`}
                      value={row.note}
                      onChange={(event) => onCompetitorNoteChange(row.id, event.target.value)}
                      placeholder="Reason or source"
                    />
                  </td>
                  <td>
                    <button
                      aria-label={`Remove ${row.name || "competitor"}`}
                      className="icon-button"
                      onClick={() => onDeleteCompetitor(row.id)}
                      title="Remove from review"
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
          title={canApplyChanges ? "Apply edited plan and resume" : "Edit the plan to enable this action"}
          type="button"
        >
          <SlidersHorizontal size={15} aria-hidden />
          {t('hitl.applyEdited')}
        </button>
      </div>
    </section>
  );
}

