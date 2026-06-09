import type { AuditLogRecord } from "../../api/types";
import { formatDate } from "./format";
import { useTranslation } from '../../stores/i18n';

export function AuditTrail({ logs }: { logs: AuditLogRecord[] }) {
  const { t } = useTranslation();
  return (
    <div className="audit-timeline">
      {logs.slice(0, 24).map((log) => (
        <article key={log.id}>
          <strong>{log.action}</strong>
          <span>{log.resource_type} / {log.resource_id}</span>
          <em>{log.actor_type}{log.actor_id ? `:${log.actor_id}` : ""} / {formatDate(log.created_at)}</em>
        </article>
      ))}
      {logs.length === 0 ? <p className="muted-line">{t('workbench.noAuditRecords')}</p> : null}
    </div>
  );
}
