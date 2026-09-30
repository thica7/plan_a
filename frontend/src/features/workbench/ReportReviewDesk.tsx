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
import { displayLabel, runtimeDiagnostic } from '../../i18n/display';
import { SystemMessage } from '../../i18n/SystemMessage';
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
      {isLoading ? <LoadingState label={t('workbench.loadingDiff')} /> : null}
      {!isLoading && diff ? (
        <div className="report-diff-panel">
          <div className="metric-grid compact">
            <MetricCard label={t('workbench.added')} value={diff.added_lines} tone="good" />
            <MetricCard label={t('workbench.removed')} value={diff.removed_lines} tone="warn" />
            <MetricCard label={t('workbench.same')} value={diff.unchanged_lines} />
          </div>
          <p className="muted-line">
            {previousVersion ? `${t('workbench.comparedWith')} v${previousVersion.version_number}` : t('workbench.noPrevVersion')}
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
      {!isLoading && !diff ? <EmptyState title={t('workbench.noDiffAvailable')} /> : null}
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
  const { t, locale } = useTranslation();
  return (
    <Panel title={t("workbench.gateIssues")} icon={<MessageSquareWarning size={16} aria-hidden />}>
      {releaseGate ? (
        <div className="recommendation-list compact">
          {releaseGate.issues.slice(0, 5).map((issue) => {
            const auditRows = buildReleaseIssueAuditRows(issue, locale);
            const rollbackTarget = buildReleaseIssueRollbackTarget(issue);
            const redoResult = gateRedoResult?.issueId === issue.id ? gateRedoResult : null;
            const isRedoing = gateRedoIssueId === issue.id;
            const rollbackResult = kbRollbackResult?.issueId === issue.id ? kbRollbackResult.result : null;
            const isRollingBack = kbRollbackIssueId === issue.id;
            return (
              <article className={`recommendation-card ${issue.severity}`} key={issue.id}>
                <strong><SystemMessage message={issue.rule_name} /></strong>
                <p><SystemMessage message={issue.message} /></p>
                {auditRows.length > 0 ? (
                  <dl className="release-issue-audit-grid" aria-label={`${t('workbench.auditFor')} ${issue.id}`}>
                    {auditRows.map((row) => (
                      <div key={`${row.label}-${row.value}`}>
                        <dt>{displayLabel(row.label, locale)}</dt>
                        <dd title={row.value}>{row.href ? <a className="link link-primary" href={row.href}>{row.value}</a> : row.value}</dd>
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
                        title={`${t('workbench.rollback')} ${runtimeDiagnostic(rollbackTarget.selectorSummary, locale)}`}
                        type="button"
                      >
                        <RotateCcw size={14} aria-hidden />
                        {isRollingBack ? t('workbench.rollingBack') : t('workbench.rollbackKbEvidence')}
                      </button>
                    ) : null}
                    {onRedoGateIssue ? (
                      <button
                        className="table-action-button"
                        disabled={Boolean(gateRedoIssueId)}
                        onClick={() => void onRedoGateIssue(issue.id)}
                        title={t('workbench.redoBranchHint')}
                        type="button"
                      >
                        {isRedoing ? t('workbench.redoing') : t('workbench.redoAffectedBranch')}
                      </button>
                    ) : null}
                    {rollbackTarget ? <span title={rollbackTarget.selectorSummary}>{runtimeDiagnostic(rollbackTarget.selectorSummary, locale)}</span> : null}
                  </div>
                ) : null}
                {redoResult ? (
                  <p className="release-issue-feedback">
                    {t('workbench.redoStarted').replace('{run}', redoResult.runId).replace('{status}', displayLabel(redoResult.status, locale))}
                  </p>
                ) : null}
                {rollbackResult ? (
                  <p className="release-issue-feedback">
                    {t('workbench.rollbackFeedback').replace('{matched}', String(rollbackResult.matched_count)).replace('{archived}', String(rollbackResult.rolled_back_count)).replace('{restored}', String(rollbackResult.restored_count))}
                  </p>
                ) : null}
              </article>
            );
          })}
          {releaseGate.issues.length === 0 ? <p className="muted-line">{t('workbench.noGateIssues')}</p> : null}
        </div>
      ) : (
        <LoadingState label={t('workbench.loadingGateIssues')} />
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
  const { t, locale } = useTranslation();
  return (
    <Panel title={t("workbench.claimReview")} icon={<GitCompareArrows size={16} aria-hidden />}>
      <div className="review-claim-list">
        {scopedClaims.map((claim) => (
          <button className="review-claim-item" key={claim.id} type="button" onClick={() => onSelectClaim(claim)}>
            <StatusPill tone={claim.status === "accepted" ? "good" : claim.status === "rejected" ? "bad" : "warn"}>
              {displayLabel(claim.status, locale)}
            </StatusPill>
            <strong>{displayLabel(claim.claim_type, locale)}</strong>
            <span>{claim.claim_text}</span>
            <em>{Math.round(claim.confidence * 100)}% {t('workbench.confidence')} / {claim.evidence_ids.length} {t('workbench.evidence')}</em>
          </button>
        ))}
        {scopedClaims.length === 0 ? <EmptyState title={t('workbench.noScopedClaims')} /> : null}
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
  const { t, locale } = useTranslation();
  return (
    <Panel title={t('summary.evidenceScope')} icon={<Database size={16} aria-hidden />}>
      {selectedVersion ? (
        <div className="source-scope-list">
          {selectedVersion.evidence_ids.slice(0, 8).map((id) => {
            const evidence = evidenceById.get(id);
            return (
              <article className="source-scope-item" key={id}>
                <strong>{evidence?.title ?? id}</strong>
                <span>{displayLabel(evidence?.dimension ?? "unknown", locale)}</span>
                {evidence ? (
                  <div className="scope-review-actions">
                    <button className="table-action-button" type="button" onClick={() => onSelectEvidence(evidence)}>
                      {t('workbench.inspect')}
                    </button>
                    <select
                      aria-label={`${t('workbench.runQuality')} ${evidence.title}`}
                      value={evidence.quality_label}
                      onChange={(event) => onEvidenceQuality(evidence.id, event.target.value as EvidenceQualityLabel)}
                    >
                      <option value="unreviewed">{displayLabel('unreviewed', locale)}</option>
                      <option value="accepted">{displayLabel('accepted', locale)}</option>
                      <option value="rejected">{displayLabel('rejected', locale)}</option>
                      <option value="stale">{displayLabel('stale', locale)}</option>
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
