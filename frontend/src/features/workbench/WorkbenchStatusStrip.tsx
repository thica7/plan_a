import { Database, FileText, ShieldCheck, Target } from "lucide-react";
import type { ReactNode } from "react";

import type { EvidenceRecord, ProjectRecord, ReportReleaseGate, ReportVersionRecord } from "../../api/types";
import { StatusPill } from "../../components/ui";
import { useTranslation } from "../../stores/i18n";
import { formatPercent } from "./format";

interface WorkbenchStatusStripProps {
  evidence: EvidenceRecord[];
  project: ProjectRecord | null;
  releaseGate: ReportReleaseGate | null;
  report: ReportVersionRecord | null;
  competitorCount: number;
}

export function WorkbenchStatusStrip({
  competitorCount,
  evidence,
  project,
  releaseGate,
  report,
}: WorkbenchStatusStripProps) {
  const { t } = useTranslation();
  const acceptedEvidence = evidence.filter((item) => item.quality_label === "accepted").length;
  const verifiedEvidence = evidence.filter((item) => item.source_type.includes("verified") || item.reliability_score >= 0.72).length;
  const evidenceRate = evidence.length > 0 ? verifiedEvidence / evidence.length : 0;

  return (
    <section className="workbench-status-strip" aria-label={t('workbench.status')}>
      <StatusMetric
        icon={<Target size={16} aria-hidden />}
        label={t('workbench.scope')}
        value={project ? project.competitor_layer.toUpperCase() : t('workbench.noProject')}
        detail={`${competitorCount} ${t('workbench.competitorCount')}`}
      />
      <StatusMetric
        icon={<Database size={16} aria-hidden />}
        label={t('workbench.evidenceStatus')}
        value={`${verifiedEvidence}/${evidence.length}`}
        detail={`${acceptedEvidence} ${t('workbench.accepted')} / ${formatPercent(evidenceRate)} ${t('workbench.verified')}`}
      />
      <StatusMetric
        icon={<FileText size={16} aria-hidden />}
        label={t('workbench.reportStatus')}
        value={report ? `v${report.version_number}` : t('common.none')}
        detail={report ? `${report.status} / ${report.claim_ids.length} ${t('workbench.claims')}` : t('workbench.runAnalysis')}
      />
      <div className="status-metric gate">
        <span className="metric-icon">
          <ShieldCheck size={16} aria-hidden />
        </span>
        <div>
          <span>{t('workbench.releaseGate')}</span>
          <strong>{releaseGate?.status ?? t('workbench.notChecked')}</strong>
          <em>{releaseGate ? `${releaseGate.blocker_count} ${t('workbench.blockers')} / ${releaseGate.warn_count} ${t('workbench.warnings')}` : t('workbench.noActiveVersion')}</em>
        </div>
        <StatusPill tone={releaseGate?.status === "pass" ? "good" : releaseGate ? "bad" : "neutral"}>
          {releaseGate?.allowed ? t('common.ready') : t('common.hold')}
        </StatusPill>
      </div>
    </section>
  );
}

function StatusMetric({
  detail,
  icon,
  label,
  value,
}: {
  detail: string;
  icon: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="status-metric">
      <span className="metric-icon">{icon}</span>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
        <em>{detail}</em>
      </div>
    </div>
  );
}
