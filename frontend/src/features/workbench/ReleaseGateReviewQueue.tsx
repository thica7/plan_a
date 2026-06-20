import { GitBranch, ListChecks, RotateCcw } from "lucide-react";
import type { ReportReleaseGate, ReportVersionRecord } from "../../api/types";
import { EmptyState, LoadingState, Panel, StatusPill } from "../../components/ui";
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
  const tasks = buildReleaseGateReviewTasks(releaseGate);
  const canRedo = Boolean(selectedVersion?.run_id && onRedoGateIssue);

  return (
    <Panel
      className="release-review-queue-panel"
      icon={<ListChecks size={16} aria-hidden />}
      title="Release gate review queue"
    >
      {!releaseGate ? <LoadingState label="Loading review queue" /> : null}
      {releaseGate && tasks.length === 0 ? (
        <EmptyState title="No release gate review tasks">Current report version has no active blockers.</EmptyState>
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
  const rollbackResult = kbRollbackResult?.issueId === task.id ? kbRollbackResult.result : null;
  const redoResult = gateRedoResult?.issueId === task.id ? gateRedoResult : null;
  const isRollingBack = kbRollbackIssueId === task.id;
  const isRedoing = gateRedoIssueId === task.id;

  return (
    <article className={`release-review-task ${task.issue.severity}`}>
      <header>
        <div>
          <strong>{task.issue.rule_name}</strong>
          <span>{releaseReviewPhaseLabel(task.phase)}</span>
        </div>
        <StatusPill tone={task.issue.severity === "blocker" ? "bad" : task.issue.severity === "warn" ? "warn" : "neutral"}>
          {task.issue.severity}
        </StatusPill>
      </header>

      <p>{task.issue.message}</p>

      <div className="release-review-task-metrics">
        <span>{task.claimCount} claims</span>
        <span>{task.evidenceCount} evidence</span>
        <span>{task.issue.rule_id}</span>
      </div>

      {task.auditRows.length > 0 ? (
        <dl className="release-issue-audit-grid" aria-label={`Review audit trail for ${task.id}`}>
          {task.auditRows.slice(0, 6).map((row) => (
            <div key={`${task.id}-${row.label}-${row.value}`}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {task.rollbackTarget || canRedo ? (
        <div className="release-issue-actions">
          {task.rollbackTarget && onRollbackKbIssue ? (
            <button
              className="table-action-button"
              disabled={Boolean(kbRollbackIssueId)}
              onClick={() => void onRollbackKbIssue(task.rollbackTarget!.issueId, task.rollbackTarget!.request)}
              title={`Rollback ${task.rollbackTarget.selectorSummary}`}
              type="button"
            >
              <RotateCcw size={14} aria-hidden />
              {isRollingBack ? "Rolling back" : "Rollback KB"}
            </button>
          ) : null}
          {canRedo && onRedoGateIssue ? (
            <button
              className="table-action-button"
              disabled={Boolean(gateRedoIssueId)}
              onClick={() => void onRedoGateIssue(task.id)}
              title="Run scoped redo for this review task"
              type="button"
            >
              <GitBranch size={14} aria-hidden />
              {isRedoing ? "Redoing" : "Scoped redo"}
            </button>
          ) : null}
          {task.rollbackTarget ? <span>{task.rollbackTarget.selectorSummary}</span> : null}
        </div>
      ) : null}

      {redoResult ? (
        <p className="release-issue-feedback">
          Scoped redo started for {redoResult.runId}; current status {redoResult.status}.
        </p>
      ) : null}
      {rollbackResult ? <RollbackFeedback result={rollbackResult} /> : null}
    </article>
  );
}

function RollbackFeedback({ result }: { result: KnowledgeRollbackResult }) {
  return (
    <p className="release-issue-feedback">
      Rollback matched {result.matched_count}, archived {result.rolled_back_count}, restored {result.restored_count}.
    </p>
  );
}
