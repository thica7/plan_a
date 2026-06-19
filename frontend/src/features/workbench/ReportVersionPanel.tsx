import { GitCompareArrows } from "lucide-react";
import type { ReportVersionRecord } from "../../api/types";
import { EmptyState, Panel, StatusPill } from "../../components/ui";
import { formatDate, reportStatusTone } from "./format";
import { useTranslation } from '../../stores/i18n';

interface ReportVersionPanelProps {
  onSelectReport: (report: ReportVersionRecord) => void;
  selectedVersionId: string | null;
  setSelectedVersionId: (versionId: string) => void;
  versions: ReportVersionRecord[];
}

export function ReportVersionPanel({
  onSelectReport,
  selectedVersionId,
  setSelectedVersionId,
  versions,
}: ReportVersionPanelProps) {
  const { t } = useTranslation();
  return (
    <Panel className="report-version-panel" title={t('workbench.versionHistory')} icon={<GitCompareArrows size={16} aria-hidden />}>
      <div className="report-version-strip">
        {versions.map((version) => (
          <button
            className={version.id === selectedVersionId ? "version-item active" : "version-item"}
            key={version.id}
            type="button"
            onClick={() => {
              setSelectedVersionId(version.id);
              onSelectReport(version);
            }}
          >
            <strong>v{version.version_number}</strong>
            <StatusPill tone={reportStatusTone(version.status)}>{version.status}</StatusPill>
            <em>{formatDate(version.created_at)}</em>
          </button>
        ))}
      </div>
      {versions.length === 0 ? <EmptyState title={t('workbench.noVersions')} /> : null}
    </Panel>
  );
}
