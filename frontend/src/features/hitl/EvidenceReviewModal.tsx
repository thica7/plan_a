import { useState } from "react";
import type { EvidenceReviewPayload } from "../../api/types";
import { ActionButton } from "../../components/interaction/ActionButton";
import { useTranslation } from "../../stores/i18n";

type EvidenceDecision = "accept" | "redo";

interface Props {
  message: string;
  payload: EvidenceReviewPayload;
  activeDecision: EvidenceDecision | null;
  isSubmitting: boolean;
  onDecision: (decision: EvidenceDecision, note: string) => void;
}

function safeSourceUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

export function EvidenceReviewModal({ message, payload, activeDecision, isSubmitting, onDecision }: Props) {
  const { t } = useTranslation();
  const [note, setNote] = useState("");
  const sources = Array.isArray(payload.sources) ? payload.sources : [];
  const findings = Array.isArray(payload.qa_findings) ? payload.qa_findings : [];
  const remaining = typeof payload.redo_remaining === "number" ? Math.max(0, payload.redo_remaining) : null;
  const reviewReady = Array.isArray(payload.sources) && Array.isArray(payload.qa_findings) && remaining !== null;
  const redoDisabledReason = !reviewReady
    ? t("hitl.evidenceUnavailableAction")
    : remaining === 0
      ? t("hitl.evidenceRedoExhausted")
      : t("hitl.submitting");

  return (
    <section className="hitl-panel evidence-review-panel" aria-label={t("hitl.evidenceReview")}>
      <div>
        <h2>{t("hitl.evidenceReview")}</h2>
        <p>{message}</p>
        <p>{t("hitl.evidenceRemaining").replace("{count}", remaining === null ? "—" : String(remaining))}</p>
        {!reviewReady ? <p role="status">{t("hitl.evidenceNotLoaded")}</p> : null}
      </div>
      <div>
        <h3>{t("hitl.evidenceSources")} ({payload.source_count ?? sources.length})</h3>
        {payload.sources_truncated ? <p className="hitl-field-note">{t("hitl.evidenceSourcesTruncated")
          .replace("{shown}", String(sources.length))
          .replace("{total}", String(payload.source_count ?? sources.length))}</p> : null}
        {sources.length === 0 ? <p>{t("hitl.evidenceEmpty")}</p> : (
          <div className="evidence-review-list">
            {sources.map((source) => {
              const safeUrl = safeSourceUrl(source.url);
              return (
                <article className="evidence-review-source" key={source.id}>
                  <h4>{safeUrl ? (
                    <a data-action-audit="external" data-action-id={`evidence-review.source.${source.id}`} href={safeUrl} rel="noopener noreferrer" target="_blank">{source.title || source.id}</a>
                  ) : (source.title || source.id)}</h4>
                  <dl>
                    <div><dt>{t("hitl.evidenceId")}</dt><dd>{source.id}</dd></div>
                    <div><dt>{t("hitl.evidenceCompetitor")}</dt><dd>{source.competitor}</dd></div>
                    <div><dt>{t("hitl.evidenceDimension")}</dt><dd>{source.dimension}</dd></div>
                    <div><dt>{t("hitl.evidenceUrl")}</dt><dd>{source.url || "—"}</dd></div>
                    <div><dt>{t("hitl.evidenceType")}</dt><dd>{source.source_type}</dd></div>
                    <div><dt>{t("hitl.evidenceConfidence")}</dt><dd>{Math.round(source.confidence * 100)}%</dd></div>
                    <div><dt>{t("hitl.evidenceFetchedAt")}</dt><dd>{source.fetched_at || "—"}</dd></div>
                    <div><dt>{t("hitl.evidencePublishedAt")}</dt><dd>{source.source_published_at || "—"}</dd></div>
                    <div><dt>{t("hitl.evidenceUpdatedAt")}</dt><dd>{source.source_updated_at || "—"}</dd></div>
                    <div><dt>{t("hitl.evidenceExtractedAt")}</dt><dd>{source.extracted_at || "—"}</dd></div>
                  </dl>
                </article>
              );
            })}
          </div>
        )}
      </div>
      <div>
        <h3>{t("hitl.evidenceFindings")} ({payload.qa_issue_count ?? findings.length})</h3>
        {payload.qa_findings_truncated ? <p className="hitl-field-note">{t("hitl.evidenceFindingsTruncated")
          .replace("{shown}", String(findings.length))
          .replace("{total}", String(payload.qa_issue_count ?? findings.length))}</p> : null}
        {findings.length === 0 ? <p>{t("hitl.evidenceNoFindings")}</p> : (
          <ul className="evidence-review-findings">
            {findings.map((finding) => (
              <li key={finding.id}>
                <strong>{finding.severity} · {finding.id}</strong>
                <span>{finding.problem}</span>
                <small>{[finding.target_agent, finding.target_subagent, finding.target_competitor, finding.field_path].filter(Boolean).join(" · ")}</small>
              </li>
            ))}
          </ul>
        )}
      </div>
      <label className="field-block">
        {t("hitl.evidenceNote")}
        <textarea maxLength={1000} rows={3} value={note} onChange={(event) => setNote(event.target.value)} />
      </label>
      <div className="hitl-actions">
        <ActionButton
          authenticity={{ actionId: "evidence-review.accept", kind: "mutation", description: "accepts collected evidence and resumes the run" }}
          className="icon-text-button"
          disabled={isSubmitting || !reviewReady}
          disabledReason={!reviewReady ? t("hitl.evidenceUnavailableAction") : isSubmitting ? t("hitl.submitting") : undefined}
          isLoading={activeDecision === "accept"}
          loadingLabel={t("hitl.submitting")}
          onClick={() => onDecision("accept", note.trim())}
        >{t("hitl.evidenceAccept")}</ActionButton>
        <ActionButton
          authenticity={{ actionId: "evidence-review.redo", kind: "mutation", description: "requests another evidence collection round" }}
          className="icon-text-button"
          disabled={isSubmitting || !reviewReady || remaining === 0}
          disabledReason={isSubmitting || !reviewReady || remaining === 0 ? redoDisabledReason : undefined}
          isLoading={activeDecision === "redo"}
          loadingLabel={t("hitl.submitting")}
          onClick={() => onDecision("redo", note.trim())}
        >{t("hitl.evidenceRedo")}</ActionButton>
      </div>
    </section>
  );
}
