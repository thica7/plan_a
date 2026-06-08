import { useState } from "react";

import type {
  AuditLogRecord,
  BusinessQAEvaluation,
  ClaimRecord,
  ClaimValidationReport,
  CompetitorRecord,
  CompetitorScoreReport,
  EvidenceGapReport,
  EvidenceRecord,
  EvalOpsReport,
  ProjectReadinessScore,
  QualityAgentMatrix,
  RedTeamReport,
  ReportVersionRecord,
} from "../../api/types";
import { ContextInspector } from "./ContextInspector";
import { CompetitorsOverviewTable, QaBlockersPanel, RecentActivityPanel } from "./OverviewPanels";
import { ActiveReportCard, CoverageHeatmap, EvidenceQualityCard, ReadinessCard } from "./OverviewSummaryCards";
import "./overview.css";

export interface OverviewDashboardProps {
  auditLogs: AuditLogRecord[];
  claimValidation: ClaimValidationReport | null;
  claims: ClaimRecord[];
  competitorScores: CompetitorScoreReport | null;
  competitors: CompetitorRecord[];
  evidence: EvidenceRecord[];
  evidenceGaps: EvidenceGapReport | null;
  evalOps: EvalOpsReport | null;
  matrix: QualityAgentMatrix | null;
  qaEvaluation: BusinessQAEvaluation | null;
  readiness: ProjectReadinessScore | null;
  redTeam: RedTeamReport | null;
  selectedVersion: ReportVersionRecord | null;
}

type InspectorTab = "source" | "claim" | "report";

export function OverviewDashboard(props: OverviewDashboardProps) {
  const {
    auditLogs,
    claimValidation,
    claims,
    competitorScores,
    competitors,
    evidence,
    evidenceGaps,
    evalOps,
    matrix,
    qaEvaluation,
    readiness,
    redTeam,
    selectedVersion,
  } = props;
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>("source");
  const evidenceQuality = summarizeEvidenceQuality(evidence);
  const selectedSource = pickInspectorSource(evidence);
  const selectedClaim = pickInspectorClaim(claims, selectedSource);

  return (
    <div className="concept-workbench-grid">
      <div className="concept-main-column">
        <div className="concept-summary-grid">
          <ReadinessCard readiness={readiness} />
          <EvidenceQualityCard
            acceptedRate={evidenceQuality.acceptedRate}
            evidence={evidence}
            verifiedRate={evidenceQuality.verifiedRate}
          />
          <CoverageHeatmap competitors={competitors} evidence={evidence} />
          <ActiveReportCard selectedVersion={selectedVersion} />
        </div>

        <div className="concept-lower-grid">
          <QaBlockersPanel
            claimValidation={claimValidation}
            evidenceGaps={evidenceGaps}
            matrix={matrix}
            qaEvaluation={qaEvaluation}
            redTeam={redTeam}
          />
          <RecentActivityPanel auditLogs={auditLogs} evalOps={evalOps} selectedVersion={selectedVersion} />
        </div>

        <CompetitorsOverviewTable competitorScores={competitorScores} competitors={competitors} evidence={evidence} />
      </div>

      <ContextInspector
        claim={selectedClaim}
        evidence={selectedSource}
        report={selectedVersion}
        selectedTab={inspectorTab}
        setSelectedTab={setInspectorTab}
      />
    </div>
  );
}

function summarizeEvidenceQuality(evidence: EvidenceRecord[]) {
  if (evidence.length === 0) return { acceptedRate: 0, verifiedRate: 0 };
  const verifiedCount = evidence.filter((item) => item.source_type.includes("verified") || item.reliability_score >= 0.72).length;
  const acceptedCount = evidence.filter((item) => item.quality_label === "accepted").length;
  return {
    acceptedRate: acceptedCount / evidence.length,
    verifiedRate: verifiedCount / evidence.length,
  };
}

function pickInspectorSource(evidence: EvidenceRecord[]) {
  return evidence.find((item) => item.quality_label === "accepted") ?? evidence.find((item) => item.url) ?? evidence[0] ?? null;
}

function pickInspectorClaim(claims: ClaimRecord[], source: EvidenceRecord | null) {
  return claims.find((claim) => source && claim.evidence_ids.includes(source.id)) ?? claims[0] ?? null;
}
