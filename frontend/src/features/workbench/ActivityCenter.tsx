import { CalendarClock } from "lucide-react";
import type {
  AuditLogRecord,
  EvalOpsReport,
  NotificationRecord,
  ProjectRecord,
  ReportReleaseGate,
  ReportVersionRecord,
} from "../../api/types";
import { Panel } from "../../components/ui";
import type { KnowledgeRollbackRequest, KnowledgeRollbackResult } from "../../stores/knowledgeStore";
import { useTranslation } from "../../stores/i18n";
import { AuditTrail } from "./AuditTrail";
import { BenchmarkPanel } from "./BenchmarkPanel";
import { NotificationStream } from "./NotificationStream";
import { ReleaseGateReviewQueue } from "./ReleaseGateReviewQueue";

interface ActivityCenterProps {
  auditLogs: AuditLogRecord[];
  evalOps: EvalOpsReport | null;
  gateRedoIssueId: string | null;
  gateRedoResult: { issueId: string; runId: string; status: string } | null;
  kbRollbackIssueId: string | null;
  kbRollbackResult: { issueId: string; result: KnowledgeRollbackResult } | null;
  notifications: NotificationRecord[];
  onRedoGateIssue: (issueId: string) => void;
  onRollbackKbIssue: (issueId: string, request: KnowledgeRollbackRequest) => void;
  project: ProjectRecord;
  releaseGate: ReportReleaseGate | null;
  selectedVersion: ReportVersionRecord | null;
}

export function ActivityCenter({
  auditLogs,
  evalOps,
  gateRedoIssueId,
  gateRedoResult,
  kbRollbackIssueId,
  kbRollbackResult,
  notifications,
  onRedoGateIssue,
  onRollbackKbIssue,
  project,
  releaseGate,
  selectedVersion,
}: ActivityCenterProps) {
  const { t } = useTranslation();
  return (
    <div className="activity-workbench">
      <main className="activity-main">
        <NotificationStream notifications={notifications} project={project} />
        <Panel title={t('workbench.auditTrail')} icon={<CalendarClock size={16} aria-hidden />}>
          <AuditTrail logs={auditLogs} />
        </Panel>
      </main>
      <aside className="activity-side-rail">
        <ReleaseGateReviewQueue
          gateRedoIssueId={gateRedoIssueId}
          gateRedoResult={gateRedoResult}
          kbRollbackIssueId={kbRollbackIssueId}
          kbRollbackResult={kbRollbackResult}
          onRedoGateIssue={selectedVersion?.run_id ? onRedoGateIssue : undefined}
          onRollbackKbIssue={onRollbackKbIssue}
          releaseGate={releaseGate}
          selectedVersion={selectedVersion}
        />
        <BenchmarkPanel evalOps={evalOps} />
      </aside>
    </div>
  );
}
