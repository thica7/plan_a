import { Bell } from "lucide-react";
import type { NotificationRecord, ProjectRecord } from "../../api/types";
import { EmptyState, Panel, StatusPill } from "../../components/ui";
import { useTranslation } from "../../stores/i18n";
import { formatDate } from "./format";

interface NotificationStreamProps {
  notifications: NotificationRecord[];
  project: ProjectRecord;
}

export function NotificationStream({ notifications, project }: NotificationStreamProps) {
  const { t } = useTranslation();
  return (
    <Panel className="activity-notification-panel" title={t("workbench.signals")} icon={<Bell size={16} aria-hidden />}>
      <div className="notification-list redesigned">
        {notifications.map((notification) => {
          const details = summarizeNotification(notification.body);
          return (
            <article className={`notification-item ${notification.severity}`} key={notification.id}>
              <header>
                <div>
                  <strong>{notification.title}</strong>
                  <span className="notification-type">{notification.notification_type.replace(/_/g, " ")}</span>
                </div>
                <StatusPill tone={notification.severity === "critical" ? "bad" : notification.severity === "warning" ? "warn" : "good"}>
                  {notification.severity}
                </StatusPill>
              </header>

              <p className="notification-body">{details.summary}</p>

              {details.chips.length > 0 ? (
                <div className="notification-detail-grid">
                  {details.chips.map((chip) => (
                    <span className="notification-detail-chip" key={chip}>
                      {chip}
                    </span>
                  ))}
                </div>
              ) : null}

              <footer>
                <span>{notification.status} / {notification.channel}</span>
                <time dateTime={notification.created_at}>{formatDate(notification.created_at)}</time>
              </footer>
            </article>
          );
        })}
        {notifications.length === 0 ? <EmptyState title={t("workbench.noNotifications")}>No notifications for {project.name}.</EmptyState> : null}
      </div>
    </Panel>
  );
}

function summarizeNotification(body: string) {
  const normalized = body
    .replace(/[a-f0-9]{24,}/gi, (value) => `${value.slice(0, 8)}...`)
    .replace(/\s+/g, " ")
    .trim();
  const [summary = "", ...rest] = normalized.split(";").map((part) => part.trim()).filter(Boolean);
  return {
    chips: rest.slice(0, 4),
    summary: clipText(summary || normalized, 150),
  };
}

function clipText(value: string, maxLength: number) {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1).trim()}...`;
}
