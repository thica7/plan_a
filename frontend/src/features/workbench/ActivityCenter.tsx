import { CalendarClock } from "lucide-react";
import type {
  AuditLogRecord,
  EvalOpsReport,
  NotificationRecord,
  ProjectRecord,
} from "../../api/types";
import { Panel } from "../../components/ui";
import { useTranslation } from "../../stores/i18n";
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
        <BenchmarkPanel evalOps={evalOps} />
      </aside>
    </div>
  );
}
