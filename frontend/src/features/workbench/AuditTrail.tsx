import type { AuditLogRecord } from "../../api/types";
import { formatDate } from "./format";
import { useTranslation } from '../../stores/i18n';
import { displayLabel } from '../../i18n/display';

export function AuditTrail({ logs }: { logs: AuditLogRecord[] }) {
  const { t, locale } = useTranslation();
  return (
    <div className="audit-timeline">
      {logs.slice(0, 24).map((log) => (
        <article key={log.id}>
          <strong title={log.action}>{displayLabel(log.action, locale)}</strong>
          <span>{displayLabel(log.resource_type, locale)} / {log.resource_id}</span>
          <em>{displayLabel(log.actor_type, locale)}{log.actor_id ? `:${log.actor_id}` : ""} / {formatDate(log.created_at)}</em>
        </article>
      ))}
      {logs.length === 0 ? <p className="muted-line">{t('workbench.noAuditRecords')}</p> : null}
    </div>
  );
}
