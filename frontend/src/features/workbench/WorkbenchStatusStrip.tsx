import { Database, FileText, ShieldCheck, Target } from "lucide-react";
import type { ReactNode } from "react";

import type { EvidenceRecord, ProjectRecord, ReportReleaseGate, ReportVersionRecord } from "../../api/types";
import { StatusPill } from "../../components/ui";
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
  const acceptedEvidence = evidence.filter((item) => item.quality_label === "accepted").length;
  const verifiedEvidence = evidence.filter((item) => item.source_type.includes("verified") || item.reliability_score >= 0.72).length;
  const evidenceRate = evidence.length > 0 ? verifiedEvidence / evidence.length : 0;

  return (
    <section className="workbench-status-strip" aria-label="Current workspace status">
      <StatusMetric
        icon={<Target size={16} aria-hidden />}
        label="Scope"
        value={project ? project.competitor_layer.toUpperCase() : "No project"}
        detail={`${competitorCount} competitors`}
      />
      <StatusMetric
        icon={<Database size={16} aria-hidden />}
        label="Evidence"
        value={`${verifiedEvidence}/${evidence.length}`}
        detail={`${acceptedEvidence} accepted · ${formatPercent(evidenceRate)} verified`}
      />
      <StatusMetric
        icon={<FileText size={16} aria-hidden />}
        label="Report"
        value={report ? `v${report.version_number}` : "None"}
        detail={report ? `${report.status} · ${report.claim_ids.length} claims` : "Run analysis to create a report"}
      />
      <div className="status-metric gate">
        <span className="metric-icon">
          <ShieldCheck size={16} aria-hidden />
        </span>
        <div>
          <span>Release gate</span>
          <strong>{releaseGate?.status ?? "not checked"}</strong>
          <em>{releaseGate ? `${releaseGate.blocker_count} blockers · ${releaseGate.warn_count} warnings` : "No active version"}</em>
        </div>
        <StatusPill tone={releaseGate?.status === "pass" ? "good" : releaseGate ? "bad" : "neutral"}>
          {releaseGate?.allowed ? "ready" : "hold"}
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
