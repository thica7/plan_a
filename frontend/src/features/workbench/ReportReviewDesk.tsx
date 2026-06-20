import { Database, GitCompareArrows, MessageSquareWarning, RotateCcw } from "lucide-react";
import type {
  ClaimRecord,
  EvidenceQualityLabel,
  EvidenceRecord,
  ReportReleaseGate,
  ReportVersionDiff,
  ReportVersionRecord,
} from "../../api/types";
import { EmptyState, LoadingState, MetricCard, Panel, StatusPill } from "../../components/ui";
import { useTranslation } from "../../stores/i18n";
import type { KnowledgeRollbackRequest, KnowledgeRollbackResult } from "../../stores/knowledgeStore";
import {
  buildReleaseIssueAuditRows,
  buildReleaseIssueRollbackTarget,
} from "./releaseGateReview";

export { buildReleaseIssueAuditRows, buildReleaseIssueRollbackTarget } from "./releaseGateReview";


interface ReportReviewDeskProps {
  diff: ReportVersionDiff | null;
  evidenceById: Map<string, EvidenceRecord>;
  isDiffLoading: boolean;
  gateRedoIssueId?: string | null;
  gateRedoResult?: ReleaseIssueRedoResult | null;
  kbRollbackIssueId?: string | null;
  kbRollbackResult?: ReleaseIssueRollbackResult | null;
  onEvidenceQuality: (evidenceId: string, qualityLabel: EvidenceQualityLabel) => void;
  onRedoGateIssue?: (issueId: string) => void | Promise<void>;
  onRollbackKbIssue?: (issueId: string, request: KnowledgeRollbackRequest) => void | Promise<void>;
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
  gateRedoIssueId = null,
  gateRedoResult = null,
  kbRollbackIssueId = null,
  kbRollbackResult = null,
  onEvidenceQuality,
  onRedoGateIssue,
  onRollbackKbIssue,
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
      <ReleaseIssuesPanel
        gateRedoIssueId={gateRedoIssueId}
        gateRedoResult={gateRedoResult}
        kbRollbackIssueId={kbRollbackIssueId}
        kbRollbackResult={kbRollbackResult}
        onRedoGateIssue={onRedoGateIssue}
        onRollbackKbIssue={onRollbackKbIssue}
        releaseGate={releaseGate}
      />
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

function ReleaseIssuesPanel({
  gateRedoIssueId,
  gateRedoResult,
  kbRollbackIssueId,
  kbRollbackResult,
  onRedoGateIssue,
  onRollbackKbIssue,
  releaseGate,
}: {
  gateRedoIssueId: string | null;
  gateRedoResult: ReleaseIssueRedoResult | null;
  kbRollbackIssueId: string | null;
  kbRollbackResult: ReleaseIssueRollbackResult | null;
  onRedoGateIssue?: (issueId: string) => void | Promise<void>;
  onRollbackKbIssue?: (issueId: string, request: KnowledgeRollbackRequest) => void | Promise<void>;
  releaseGate: ReportReleaseGate | null;
}) {
  const { t } = useTranslation();
  return (
    <Panel title={t("workbench.gateIssues")} icon={<MessageSquareWarning size={16} aria-hidden />}>
      {releaseGate ? (
        <div className="recommendation-list compact">
          {releaseGate.issues.slice(0, 5).map((issue) => {
            const auditRows = buildReleaseIssueAuditRows(issue);
            const rollbackTarget = buildReleaseIssueRollbackTarget(issue);
            const redoResult = gateRedoResult?.issueId === issue.id ? gateRedoResult : null;
            const isRedoing = gateRedoIssueId === issue.id;
            const rollbackResult = kbRollbackResult?.issueId === issue.id ? kbRollbackResult.result : null;
            const isRollingBack = kbRollbackIssueId === issue.id;
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
                {rollbackTarget || onRedoGateIssue ? (
                  <div className="release-issue-actions">
                    {rollbackTarget && onRollbackKbIssue ? (
                      <button
                        className="table-action-button"
                        disabled={Boolean(kbRollbackIssueId)}
                        onClick={() => void onRollbackKbIssue(rollbackTarget.issueId, rollbackTarget.request)}
                        title={`Rollback ${rollbackTarget.selectorSummary}`}
                        type="button"
                      >
                        <RotateCcw size={14} aria-hidden />
                        {isRollingBack ? "Rolling back" : "Rollback KB evidence"}
                      </button>
                    ) : null}
                    {onRedoGateIssue ? (
                      <button
                        className="table-action-button"
                        disabled={Boolean(gateRedoIssueId)}
                        onClick={() => void onRedoGateIssue(issue.id)}
                        title="Run scoped redo for the affected branch"
                        type="button"
                      >
                        {isRedoing ? "Redoing" : "Redo affected branch"}
                      </button>
                    ) : null}
                    {rollbackTarget ? <span>{rollbackTarget.selectorSummary}</span> : null}
                  </div>
                ) : null}
                {redoResult ? (
                  <p className="release-issue-feedback">
                    Scoped redo started for {redoResult.runId}; current status {redoResult.status}.
                  </p>
                ) : null}
                {rollbackResult ? (
                  <p className="release-issue-feedback">
                    Rollback matched {rollbackResult.matched_count}, archived {rollbackResult.rolled_back_count},
                    restored {rollbackResult.restored_count}.
                  </p>
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

export interface ReleaseIssueRedoResult {
  issueId: string;
  runId: string;
  status: string;
}

export interface ReleaseIssueRollbackResult {
  issueId: string;
  result: KnowledgeRollbackResult;
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
