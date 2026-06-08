import { Bell, CalendarClock, Gauge } from "lucide-react";
import type {
  AuditLogRecord,
  EvalOpsReport,
  NotificationRecord,
  ProjectRecord,
} from "../../api/types";
import { MetricCard, Panel } from "../../components/ui";
import { AuditTrail } from "./AuditTrail";
import { formatDate, formatPercent } from "./format";

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
    <div className="workspace-two-column">
      <Panel title="Notification stream" icon={<Bell size={16} aria-hidden />}>
        <div className="notification-list">
          {notifications.map((notification) => (
            <article className={`notification-item ${notification.severity}`} key={notification.id}>
              <strong>{notification.title}</strong>
              <span>{notification.body}</span>
              <em>{notification.status} / {formatDate(notification.created_at)}</em>
            </article>
          ))}
          {notifications.length === 0 ? <p className="muted-line">No notifications for {project.name}.</p> : null}
        </div>
      </Panel>

      <Panel title="Benchmark panel" icon={<Gauge size={16} aria-hidden />}>
        <div className="metric-grid compact">
          <MetricCard label="Runs evaluated" value={evalOps?.run_count ?? "n/a"} />
          <MetricCard label="Golden pass" value={evalOps ? formatPercent(evalOps.golden_set_pass_rate) : "n/a"} />
          <MetricCard label="Report quality" value={evalOps?.report_quality_score ?? "n/a"} />
          <MetricCard label="Time saved" value={evalOps ? `${evalOps.manual_time_saved_hours.toFixed(1)}h` : "n/a"} />
          <MetricCard label="Gate" value={evalOps?.regression_gate_status ?? "n/a"} tone={evalOps?.regression_gate_status === "fail" ? "warn" : "good"} />
        </div>
        <div className="recommendation-list compact">
          {(evalOps?.recommendations ?? []).slice(0, 5).map((item) => (
            <article className="recommendation-card medium" key={item}>
              <strong>Next</strong>
              <p>{item}</p>
            </article>
          ))}
        </div>
      </Panel>

      <Panel title="Audit trail" icon={<CalendarClock size={16} aria-hidden />}>
        <AuditTrail logs={auditLogs} />
      </Panel>
    </div>
  );
}
