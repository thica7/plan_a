import { GitBranch, ListChecks, RotateCcw } from "lucide-react";
import type { ReportReleaseGate, ReportVersionRecord } from "../../api/types";
import { EmptyState, LoadingState, Panel, StatusPill } from "../../components/ui";
import { ActionButton } from "../../components/interaction/ActionButton";
import { useTranslation } from '../../stores/i18n';
import { displayLabel, runtimeDiagnostic } from '../../i18n/display';
import { SystemMessage } from '../../i18n/SystemMessage';
import type { KnowledgeRollbackRequest, KnowledgeRollbackResult } from "../../stores/knowledgeStore";
import type { ReleaseIssueRedoResult, ReleaseIssueRollbackResult } from "./ReportReviewDesk";
import {
  buildReleaseGateReviewTasks,
  releaseReviewPhaseLabel,
  type ReleaseGateReviewTask,
} from "./releaseGateReview";

interface ReleaseGateReviewQueueProps {
  gateRedoIssueId?: string | null;
  gateRedoResult?: ReleaseIssueRedoResult | null;
  kbRollbackIssueId?: string | null;
  kbRollbackResult?: ReleaseIssueRollbackResult | null;
  onRedoGateIssue?: (issueId: string) => void | Promise<void>;
  onRollbackKbIssue?: (issueId: string, request: KnowledgeRollbackRequest) => void | Promise<void>;
  releaseGate: ReportReleaseGate | null;
  selectedVersion: ReportVersionRecord | null;
}

export function ReleaseGateReviewQueue({
  gateRedoIssueId = null,
  gateRedoResult = null,
  kbRollbackIssueId = null,
  kbRollbackResult = null,
  onRedoGateIssue,
  onRollbackKbIssue,
  releaseGate,
  selectedVersion,
}: ReleaseGateReviewQueueProps) {
  const { t, locale } = useTranslation();
  const tasks = buildReleaseGateReviewTasks(releaseGate, locale);
  const canRedo = Boolean(selectedVersion?.run_id && onRedoGateIssue);

  return (
    <Panel
      className="release-review-queue-panel"
      icon={<ListChecks size={16} aria-hidden />}
      title={t('workbench.reviewQueue')}
    >
      {!releaseGate ? <LoadingState label={t('workbench.loadingReviewQueue')} /> : null}
      {releaseGate && tasks.length === 0 ? (
        <EmptyState title={t('workbench.noReviewTasks')}>{t('workbench.noVersionBlockers')}</EmptyState>
      ) : null}
      {tasks.length > 0 ? (
        <div className="release-review-task-list">
          {tasks.slice(0, 6).map((task) => (
            <ReleaseGateReviewTaskCard
              canRedo={canRedo}
              gateRedoIssueId={gateRedoIssueId}
              gateRedoResult={gateRedoResult}
              kbRollbackIssueId={kbRollbackIssueId}
              kbRollbackResult={kbRollbackResult}
              key={task.id}
              onRedoGateIssue={onRedoGateIssue}
              onRollbackKbIssue={onRollbackKbIssue}
              task={task}
            />
          ))}
        </div>
      ) : null}
    </Panel>
  );
}

function ReleaseGateReviewTaskCard({
  canRedo,
  gateRedoIssueId,
  gateRedoResult,
  kbRollbackIssueId,
  kbRollbackResult,
  onRedoGateIssue,
  onRollbackKbIssue,
  task,
}: {
  canRedo: boolean;
  gateRedoIssueId: string | null;
  gateRedoResult: ReleaseIssueRedoResult | null;
  kbRollbackIssueId: string | null;
  kbRollbackResult: ReleaseIssueRollbackResult | null;
  onRedoGateIssue?: (issueId: string) => void | Promise<void>;
  onRollbackKbIssue?: (issueId: string, request: KnowledgeRollbackRequest) => void | Promise<void>;
  task: ReleaseGateReviewTask;
}) {
  const { t, locale } = useTranslation();
  const rollbackResult = kbRollbackResult?.issueId === task.id ? kbRollbackResult.result : null;
  const redoResult = gateRedoResult?.issueId === task.id ? gateRedoResult : null;
  const isRollingBack = kbRollbackIssueId === task.id;
  const isRedoing = gateRedoIssueId === task.id;

  return (
    <article className={`release-review-task ${task.issue.severity}`}>
      <header>
        <div>
          <strong><SystemMessage message={task.issue.rule_name} /></strong>
          <span>{displayLabel(releaseReviewPhaseLabel(task.phase), locale)}</span>
        </div>
        <StatusPill tone={task.issue.severity === "blocker" ? "bad" : task.issue.severity === "warn" ? "warn" : "neutral"}>
          {displayLabel(task.issue.severity, locale)}
        </StatusPill>
      </header>

      <p><SystemMessage message={task.issue.message} /></p>

      <div className="release-review-task-metrics">
        <span>{task.claimCount} {t('workbench.claims')}</span>
        <span>{task.evidenceCount} {t('workbench.evidence')}</span>
        <span title={task.issue.rule_id}>{displayLabel(task.issue.rule_id, locale)}</span>
      </div>

      {task.auditRows.length > 0 ? (
        <dl className="release-issue-audit-grid" aria-label={`${t('workbench.reviewAuditFor')} ${task.id}`}>
          {task.auditRows.slice(0, 6).map((row) => (
            <div key={`${task.id}-${row.label}-${row.value}`}>
              <dt>{displayLabel(row.label, locale)}</dt>
              <dd title={row.value}>{row.href ? <a className="link link-primary" href={row.href}>{row.value}</a> : row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {task.rollbackTarget || canRedo ? (
        <div className="release-issue-actions">
          {task.rollbackTarget && onRollbackKbIssue ? (
            <ActionButton
              authenticity={{ actionId: "release-gate.kb.rollback", kind: "mutation", description: "rolls back KB documents linked to this issue" }}
              className="table-action-button"
              disabled={Boolean(kbRollbackIssueId)}
              disabledReason={kbRollbackIssueId ? t('workbench.rollbackPending') : undefined}
              onClick={() => void onRollbackKbIssue(task.rollbackTarget!.issueId, task.rollbackTarget!.request)}
              title={`${t('workbench.rollback')} ${runtimeDiagnostic(task.rollbackTarget.selectorSummary, locale)}`}
              type="button"
            >
              <RotateCcw size={14} aria-hidden />
              {isRollingBack ? t('workbench.rollingBack') : t('workbench.rollbackKb')}
            </ActionButton>
          ) : null}
          {canRedo && onRedoGateIssue ? (
            <ActionButton
              authenticity={{ actionId: "release-gate.issue.redo", kind: "mutation", description: "starts scoped redo for this report issue" }}
              className="table-action-button"
              disabled={Boolean(gateRedoIssueId)}
              disabledReason={gateRedoIssueId ? t('workbench.redoPending') : undefined}
              onClick={() => void onRedoGateIssue(task.id)}
              title={t('workbench.redoTaskHint')}
              type="button"
            >
              <GitBranch size={14} aria-hidden />
              {isRedoing ? t('workbench.redoing') : t('workbench.scopedRedo')}
            </ActionButton>
          ) : null}
          {task.rollbackTarget ? <span title={task.rollbackTarget.selectorSummary}>{runtimeDiagnostic(task.rollbackTarget.selectorSummary, locale)}</span> : null}
        </div>
      ) : null}

      {redoResult ? (
        <p className="release-issue-feedback">
          {t('workbench.redoStarted').replace('{run}', redoResult.runId).replace('{status}', displayLabel(redoResult.status, locale))}
        </p>
      ) : null}
      {rollbackResult ? <RollbackFeedback result={rollbackResult} /> : null}
    </article>
  );
}

function RollbackFeedback({ result }: { result: KnowledgeRollbackResult }) {
  const { t } = useTranslation();
  return (
    <p className="release-issue-feedback">
      {t('workbench.rollbackFeedback').replace('{matched}', String(result.matched_count)).replace('{archived}', String(result.rolled_back_count)).replace('{restored}', String(result.restored_count))}
    </p>
  );
}
