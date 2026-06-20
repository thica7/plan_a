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
          const details = summarizeNotification(notification);
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

export function summarizeNotification(notification: NotificationRecord) {
  const normalized = notification.body
    .replace(/[a-f0-9]{24,}/gi, (value) => `${value.slice(0, 8)}...`)
    .replace(/\s+/g, " ")
    .trim();
  const [summary = "", ...rest] = normalized.split(";").map((part) => part.trim()).filter(Boolean);
  return {
    chips: uniqueStrings([...rest.slice(0, 4), ...notificationMetadataChips(notification)]).slice(0, 8),
    summary: clipText(summary || normalized || notification.title, 150),
  };
}

function clipText(value: string, maxLength: number) {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, maxLength - 1).trim()}...`;
}

function notificationMetadataChips(notification: NotificationRecord): string[] {
  if (notification.notification_type !== "release_gate_blocked") return [];
  const metadata = notification.metadata ?? {};
  const chips: string[] = [];
  const score = metadataNumber(metadata, "readiness_score");
  const blockerCount = metadataNumber(metadata, "blocker_count");
  const warnCount = metadataNumber(metadata, "warn_count");
  const reportVersionId =
    metadataText(metadata, "report_version_id") ||
    (notification.resource_type === "report_version" ? notification.resource_id ?? "" : "");

  if (score !== null) chips.push(`score ${score}`);
  if (blockerCount !== null) chips.push(`${blockerCount} blockers`);
  if (warnCount !== null) chips.push(`${warnCount} warnings`);
  if (reportVersionId) chips.push(`report ${shortId(reportVersionId)}`);

  const firstIssue = metadataObjectList(metadata["issues"])[0];
  const rule = firstIssue
    ? metadataText(firstIssue, "rule_id") || metadataText(firstIssue, "rule_name")
    : "";
  if (rule) chips.push(`issue ${clipText(rule.replace(/_/g, " "), 36)}`);

  const issueMetadata = firstIssue ? metadataObject(firstIssue["metadata"]) : {};
  const firstAudit = metadataObjectList(issueMetadata["evidence_audit_trail"])[0];
  const kbDocumentId = firstAudit ? metadataText(firstAudit, "kb_document_id") : "";
  if (kbDocumentId) chips.push(`KB ${shortId(kbDocumentId)}`);

  return chips;
}

function metadataObject(value: unknown): Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function metadataObjectList(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item),
  );
}

function metadataText(metadata: Record<string, unknown>, key: string): string {
  const value = metadata[key];
  if (value === null || value === undefined || value === "") return "";
  return String(value);
}

function metadataNumber(metadata: Record<string, unknown>, key: string): number | null {
  const value = metadata[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function shortId(value: string): string {
  if (value.length <= 28) return value;
  return `${value.slice(0, 8)}...`;
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}
