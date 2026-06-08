import type {
  ArtifactRecord,
  AuditLogRecord,
  BusinessIntelPlan,
  BusinessQAEvaluation,
  ClaimRecord,
  ClaimValidationReport,
  CompetitorRecord,
  CompetitorScoreReport,
  DataRetentionReport,
  EvidenceGapReport,
  EvidenceRecord,
  EvalOpsReport,
  ModelPolicyReport,
  ModelRouteDecision,
  NotificationRecord,
  ProjectReadinessScore,
  QualityAgentMatrix,
  RedTeamReport,
  ReportVersionRecord,
  SourceRegistryRecord,
  WorkspaceQuotaDecision,
  WorkspaceUsageSummary,
} from "../../api/types";

export type EnterpriseView =
  | "overview"
  | "competitors"
  | "evidence"
  | "reports"
  | "governance"
  | "activity";

export interface ProjectData {
  artifacts: ArtifactRecord[];
  auditLogs: AuditLogRecord[];
  businessPlan: BusinessIntelPlan | null;
  claimValidation: ClaimValidationReport | null;
  claims: ClaimRecord[];
  competitorScores: CompetitorScoreReport | null;
  competitors: CompetitorRecord[];
  evidence: EvidenceRecord[];
  evidenceGaps: EvidenceGapReport | null;
  evalOps: EvalOpsReport | null;
  matrix: QualityAgentMatrix | null;
  modelPolicy: ModelPolicyReport | null;
  modelRoute: ModelRouteDecision | null;
  notifications: NotificationRecord[];
  qaEvaluation: BusinessQAEvaluation | null;
  readiness: ProjectReadinessScore | null;
  redTeam: RedTeamReport | null;
  registry: SourceRegistryRecord[];
  retention: DataRetentionReport | null;
  usage: WorkspaceUsageSummary | null;
  quota: WorkspaceQuotaDecision | null;
  versions: ReportVersionRecord[];
}

export const emptyProjectData: ProjectData = {
  artifacts: [],
  auditLogs: [],
  businessPlan: null,
  claimValidation: null,
  claims: [],
  competitorScores: null,
  competitors: [],
  evidence: [],
  evidenceGaps: null,
  evalOps: null,
  matrix: null,
  modelPolicy: null,
  modelRoute: null,
  notifications: [],
  qaEvaluation: null,
  readiness: null,
  redTeam: null,
  registry: [],
  retention: null,
  usage: null,
  quota: null,
  versions: [],
};
