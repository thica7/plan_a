import type {
  AuditLogRecord,
  BusinessQAEvaluation,
  ClaimRecord,
  ClaimValidationReport,
  CompetitorRecord,
  CompetitorScoreReport,
  DecisionReplayReport,
  EvidenceGapReport,
  EvidenceRecord,
  EvalOpsReport,
  ProjectReadinessScore,
  QualityAgentMatrix,
  RedTeamReport,
  ReportReleaseGate,
  ReportVersionRecord,
  TraceSpan,
} from "../../api/types";
import { CompetitorsOverviewTable, QaBlockersPanel, TraceTimelinePanel } from "./OverviewPanels";
import { CoverageHeatmap, ReportReviewStudioPanel, RunQualityPanel } from "./OverviewSummaryCards";
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
  releaseGate: ReportReleaseGate | null;
  runDecisionReplay: DecisionReplayReport | null;
  runTraceSpans: TraceSpan[];
  selectedVersion: ReportVersionRecord | null;
}

export function OverviewDashboard(props: OverviewDashboardProps) {
  const {
    auditLogs,
    claimValidation,
    competitorScores,
    competitors,
    evidence,
    evidenceGaps,
    evalOps,
    matrix,
    qaEvaluation,
    readiness,
    redTeam,
    releaseGate,
    runDecisionReplay,
    runTraceSpans,
    selectedVersion,
  } = props;
  const evidenceQuality = summarizeEvidenceQuality(evidence);

  return (
    <div className="workbench-overview">
      <div className="workbench-overview-grid">
        <RunQualityPanel
          acceptedRate={evidenceQuality.acceptedRate}
          claimValidation={claimValidation}
          evidence={evidence}
          evidenceGaps={evidenceGaps}
          qaEvaluation={qaEvaluation}
          readiness={readiness}
          redTeam={redTeam}
          verifiedRate={evidenceQuality.verifiedRate}
        />
        <CoverageHeatmap competitors={competitors} evidence={evidence} />
        <TraceTimelinePanel
          auditLogs={auditLogs}
          decisionReplay={runDecisionReplay}
          evalOps={evalOps}
          selectedVersion={selectedVersion}
          traceSpans={runTraceSpans}
        />
        <ReportReviewStudioPanel releaseGate={releaseGate} selectedVersion={selectedVersion} />
      </div>

      <div className="workbench-support-grid">
        <QaBlockersPanel
          claimValidation={claimValidation}
          evidenceGaps={evidenceGaps}
          matrix={matrix}
          qaEvaluation={qaEvaluation}
          redTeam={redTeam}
        />
        <CompetitorsOverviewTable competitorScores={competitorScores} competitors={competitors} evidence={evidence} />
      </div>
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
