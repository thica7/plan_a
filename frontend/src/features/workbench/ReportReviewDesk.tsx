import { Database, GitCompareArrows, MessageSquareWarning } from "lucide-react";
import type {
  BusinessQAFinding,
  ClaimRecord,
  EvidenceQualityLabel,
  EvidenceRecord,
  ReportReleaseGate,
  ReportVersionDiff,
  ReportVersionRecord,
} from "../../api/types";
import { EmptyState, LoadingState, MetricCard, Panel, StatusPill } from "../../components/ui";
import { useTranslation } from "../../stores/i18n";


interface ReportReviewDeskProps {
  diff: ReportVersionDiff | null;
  evidenceById: Map<string, EvidenceRecord>;
  isDiffLoading: boolean;
  onEvidenceQuality: (evidenceId: string, qualityLabel: EvidenceQualityLabel) => void;
  onSelectClaim: (claim: ClaimRecord) => void;
  onSelectEvidence: (evidence: EvidenceRecord) => void;
  previousVersion: ReportVersionRecord | null;
  releaseGate: ReportReleaseGate | null;
  scopedClaims: ClaimRecord[];
  selectedVersion: ReportVersionRecord | null;
}

export function ReportReviewDesk({
  diff,
  evidenceById,
  isDiffLoading,
  onEvidenceQuality,
  onSelectClaim,
  onSelectEvidence,
  previousVersion,
  releaseGate,
  scopedClaims,
  selectedVersion,
}: ReportReviewDeskProps) {
  return (
    <aside className="report-review-desk">
      <DiffPanel diff={diff} isLoading={isDiffLoading} previousVersion={previousVersion} />
      <ReleaseIssuesPanel releaseGate={releaseGate} />
      <ClaimReviewPanel onSelectClaim={onSelectClaim} scopedClaims={scopedClaims} />
      <EvidenceScopePanel
        evidenceById={evidenceById}
        onEvidenceQuality={onEvidenceQuality}
        onSelectEvidence={onSelectEvidence}
        selectedVersion={selectedVersion}
      />
    </aside>
  );
}

function DiffPanel({
  diff,
  isLoading,
  previousVersion,
}: {
  diff: ReportVersionDiff | null;
  isLoading: boolean;
  previousVersion: ReportVersionRecord | null;
}) {
  const { t } = useTranslation();
  return (
    <Panel title={t("workbench.versionDiff")} icon={<GitCompareArrows size={16} aria-hidden />}>
      {isLoading ? <LoadingState label="Loading diff" /> : null}
      {!isLoading && diff ? (
        <div className="report-diff-panel">
          <div className="metric-grid compact">
            <MetricCard label="added" value={diff.added_lines} tone="good" />
            <MetricCard label="removed" value={diff.removed_lines} tone="warn" />
            <MetricCard label="same" value={diff.unchanged_lines} />
          </div>
          <p className="muted-line">
            {previousVersion ? `Compared with v${previousVersion.version_number}` : "No previous version available."}
          </p>
          <div className="report-diff-lines">
            {diff.lines
              .filter((line) => line.kind !== "unchanged")
              .slice(0, 8)
              .map((line, index) => (
                <code className={line.kind} key={`${line.kind}-${index}`}>
                  {line.kind === "added" ? "+ " : "- "}
                  {line.text}
                </code>
              ))}
          </div>
        </div>
      ) : null}
      {!isLoading && !diff ? <EmptyState title="No diff available" /> : null}
    </Panel>
  );
}

function ReleaseIssuesPanel({ releaseGate }: { releaseGate: ReportReleaseGate | null }) {
  const { t } = useTranslation();
  return (
    <Panel title={t("workbench.gateIssues")} icon={<MessageSquareWarning size={16} aria-hidden />}>
      {releaseGate ? (
        <div className="recommendation-list compact">
          {releaseGate.issues.slice(0, 5).map((issue) => {
            const auditRows = buildReleaseIssueAuditRows(issue);
            return (
              <article className={`recommendation-card ${issue.severity}`} key={issue.id}>
                <strong>{issue.rule_name}</strong>
                <p>{issue.message}</p>
                {auditRows.length > 0 ? (
                  <dl className="release-issue-audit-grid" aria-label={`Audit trail for ${issue.id}`}>
                    {auditRows.map((row) => (
                      <div key={`${row.label}-${row.value}`}>
                        <dt>{row.label}</dt>
                        <dd>{row.value}</dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
              </article>
            );
          })}
          {releaseGate.issues.length === 0 ? <p className="muted-line">No active release gate issues.</p> : null}
        </div>
      ) : (
        <LoadingState label="Loading gate issues" />
      )}
    </Panel>
  );
}

export interface ReleaseIssueAuditRow {
  label: string;
  value: string;
}

export function buildReleaseIssueAuditRows(issue: BusinessQAFinding): ReleaseIssueAuditRow[] {
  const metadata = issue.metadata ?? {};
  const rows: ReleaseIssueAuditRow[] = [];
  const issueTypes = metadataStringList(metadata["claim_validation_issue_types"]);
  const conflictIds = metadataStringList(metadata["conflicting_evidence_ids"]);
  if (issueTypes.length > 0) {
    rows.push({ label: "Claim issue", value: issueTypes.join(", ") });
  }
  if (conflictIds.length > 0) {
    rows.push({ label: "Conflict evidence", value: conflictIds.join(", ") });
  }

  const trail = metadataObjectList(metadata["evidence_audit_trail"]);
  for (const item of trail.slice(0, 2)) {
    const evidenceId = metadataText(item, "evidence_id");
    const rawSourceId = metadataText(item, "raw_source_id");
    const kbDocumentId = metadataText(item, "kb_document_id");
    const kbVersion = metadataText(item, "kb_document_version");
    const kbStatus = metadataText(item, "kb_document_status");
    const kbRawSourceId = metadataText(item, "kb_raw_source_id");
    const collectorRunId = metadataText(item, "kb_collector_run_id");
    const freshnessScore = metadataNumber(item, "kb_freshness_score");

    if (evidenceId || rawSourceId) {
      rows.push({ label: "Evidence", value: [evidenceId, rawSourceId].filter(Boolean).join(" / ") });
    }
    if (kbDocumentId) {
      rows.push({
        label: "KB document",
        value: [kbDocumentId, kbVersion ? `v${kbVersion}` : "", kbStatus].filter(Boolean).join(" / "),
      });
    }
    if (kbRawSourceId) {
      rows.push({ label: "KB raw source", value: kbRawSourceId });
    }
    if (collectorRunId) {
      rows.push({ label: "Collector run", value: collectorRunId });
    }
    if (freshnessScore !== null) {
      rows.push({ label: "Freshness", value: `${Math.round(freshnessScore * 100)}%` });
    }
  }

  return rows.slice(0, 10);
}

function metadataObjectList(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item));
}

function metadataStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || "").trim()).filter(Boolean);
}

function metadataText(metadata: Record<string, unknown>, key: string): string | null {
  const value = metadata[key];
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

function metadataNumber(metadata: Record<string, unknown>, key: string): number | null {
  const value = metadata[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function ClaimReviewPanel({
  onSelectClaim,
  scopedClaims,
}: {
  onSelectClaim: (claim: ClaimRecord) => void;
  scopedClaims: ClaimRecord[];
}) {
  const { t } = useTranslation();
  return (
    <Panel title={t("workbench.claimReview")} icon={<GitCompareArrows size={16} aria-hidden />}>
      <div className="review-claim-list">
        {scopedClaims.map((claim) => (
          <button className="review-claim-item" key={claim.id} type="button" onClick={() => onSelectClaim(claim)}>
            <StatusPill tone={claim.status === "accepted" ? "good" : claim.status === "rejected" ? "bad" : "warn"}>
              {claim.status}
            </StatusPill>
            <strong>{claim.claim_type}</strong>
            <span>{claim.claim_text}</span>
            <em>{Math.round(claim.confidence * 100)}% confidence / {claim.evidence_ids.length} evidence</em>
          </button>
        ))}
        {scopedClaims.length === 0 ? <EmptyState title="No scoped claims" /> : null}
      </div>
    </Panel>
  );
}

function EvidenceScopePanel({
  evidenceById,
  onEvidenceQuality,
  onSelectEvidence,
  selectedVersion,
}: {
  evidenceById: Map<string, EvidenceRecord>;
  onEvidenceQuality: (evidenceId: string, qualityLabel: EvidenceQualityLabel) => void;
  onSelectEvidence: (evidence: EvidenceRecord) => void;
  selectedVersion: ReportVersionRecord | null;
}) {
  const { t } = useTranslation();
  return (
    <Panel title="Evidence scope" icon={<Database size={16} aria-hidden />}>
      {selectedVersion ? (
        <div className="source-scope-list">
          {selectedVersion.evidence_ids.slice(0, 8).map((id) => {
            const evidence = evidenceById.get(id);
            return (
              <article className="source-scope-item" key={id}>
                <strong>{evidence?.title ?? id}</strong>
                <span>{evidence?.dimension ?? "unknown"}</span>
                {evidence ? (
                  <div className="scope-review-actions">
                    <button className="table-action-button" type="button" onClick={() => onSelectEvidence(evidence)}>
                      Inspect
                    </button>
                    <select
                      aria-label={`Quality for ${evidence.title}`}
                      value={evidence.quality_label}
                      onChange={(event) => onEvidenceQuality(evidence.id, event.target.value as EvidenceQualityLabel)}
                    >
                      <option value="unreviewed">unreviewed</option>
                      <option value="accepted">accepted</option>
                      <option value="rejected">rejected</option>
                      <option value="stale">stale</option>
                    </select>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : (
        <EmptyState title={t("workbench.selectVersion")} />
      )}
    </Panel>
  );
}
