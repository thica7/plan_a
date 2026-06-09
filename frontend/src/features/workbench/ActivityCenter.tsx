import { CalendarClock } from "lucide-react";
import type {
  AuditLogRecord,
  EvalOpsReport,
  NotificationRecord,
  ProjectRecord,
} from "../../api/types";
import { Panel } from "../../components/ui";
import { AuditTrail } from "./AuditTrail";
import { BenchmarkPanel } from "./BenchmarkPanel";
import { NotificationStream } from "./NotificationStream";

interface ActivityCenterProps {
  auditLogs: AuditLogRecord[];
  evalOps: EvalOpsReport | null;
  notifications: NotificationRecord[];
  project: ProjectRecord;
}

export function ActivityCenter({
  auditLogs,
  evalOps,
  notifications,
  project,
}: ActivityCenterProps) {
  return (
    <div className="activity-workbench">
      <main className="activity-main">
        <NotificationStream notifications={notifications} project={project} />
        <Panel title="Audit trail" icon={<CalendarClock size={16} aria-hidden />}>
          <AuditTrail logs={auditLogs} />
        </Panel>
      </main>
      <aside className="activity-side-rail">
        <BenchmarkPanel evalOps={evalOps} />
      </aside>
    </div>
  );
}
