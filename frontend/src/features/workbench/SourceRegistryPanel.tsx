import { Database } from "lucide-react";
import type { SourceRegistryRecord } from "../../api/types";
import { Panel, StatusPill } from "../../components/ui";
import { formatDate } from "./format";
import { useTranslation } from "../../stores/i18n";
import { displayLabel } from '../../i18n/display';

interface SourceRegistryPanelProps {
  registry: SourceRegistryRecord[];
}

export function SourceRegistryPanel({ registry }: SourceRegistryPanelProps) {
  const { t, locale } = useTranslation();
  return (
    <Panel className="source-registry-panel" title={t('workbench.sourceRegistry')} icon={<Database size={16} aria-hidden />}>
      <div className="source-registry-summary">
        <RegistryStat label={t('workbench.registered')} value={registry.length} />
        <RegistryStat label={t('workbench.approved')} value={registry.filter((item) => item.policy_review_status === "approved").length} />
        <RegistryStat label={t('workbench.blockedRobots')} value={registry.filter((item) => item.robots_status === "blocked").length} />
        <RegistryStat label={t('workbench.official')} value={registry.filter((item) => item.trust_level === "official").length} />
      </div>

      <div className="data-table source-registry-table">
        <div className="data-table-head">
          <span>{t('workbench.source')}</span>
          <span>{t('workbench.trust')}</span>
          <span>{t('workbench.robots')}</span>
          <span>{t('workbench.review')}</span>
          <span>{t('workbench.seen')}</span>
        </div>
        {registry.slice(0, 50).map((source) => (
          <article className="data-row" key={source.id}>
            <span>
              <strong>{source.display_name}</strong>
              <em>{source.domain}</em>
            </span>
            <span>
              <StatusPill tone={source.trust_level === "official" || source.trust_level === "verified" ? "good" : "neutral"}>
                {displayLabel(source.trust_level, locale)}
              </StatusPill>
            </span>
            <span>
              <StatusPill tone={source.robots_status === "blocked" ? "bad" : source.robots_status === "allowed" ? "good" : "neutral"}>
                {displayLabel(source.robots_status, locale)}
              </StatusPill>
            </span>
            <span>
              <StatusPill tone={source.policy_review_status === "rejected" ? "bad" : source.policy_review_status === "approved" ? "good" : "neutral"}>
                {displayLabel(source.policy_review_status, locale)}
              </StatusPill>
            </span>
            <span>
              <strong>{source.seen_count}</strong>
              <em>{formatDate(source.last_seen_at)}</em>
            </span>
          </article>
        ))}
      </div>
    </Panel>
  );
}

function RegistryStat({ label, value }: { label: string; value: number }) {
  return (
    <span className="registry-stat">
      <strong>{value}</strong>
      <em>{label}</em>
    </span>
  );
}
