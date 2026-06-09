import {
  getEnterpriseEvalOps,
  getModelPolicy,
  getModelRouteDecision,
  getProjectBusinessPlan,
  getProjectClaimValidation,
  getProjectCompetitorScores,
  getProjectEvidenceGaps,
  getProjectQAEvaluation,
  getProjectQualityMatrix,
  getProjectReadinessScore,
  getProjectRedTeam,
  getReportReleaseGate,
  getWorkspaceQuotaDecision,
  getWorkspaceRetentionReport,
  getWorkspaceUsage,
  listArtifacts,
  listEnterpriseAuditLogs,
  listEnterpriseCompetitors,
  listEnterpriseNotifications,
  listEnterpriseProjects,
  listProjectClaims,
  listProjectEvidence,
  listProjectReportVersions,
  listSourceRegistry,
} from "../../api/client";
import type { ProjectRecord, ReportReleaseGate } from "../../api/types";
import type { ProjectData } from "./types";

export async function loadWorkbenchProjects() {
  const [projects, notifications] = await Promise.all([
    listEnterpriseProjects(),
    listEnterpriseNotifications({ limit: 8 }),
  ]);
  return { notifications, projects };
}

export async function loadProjectCore(project: ProjectRecord): Promise<Pick<ProjectData, "artifacts" | "claims" | "competitors" | "evidence" | "notifications" | "versions">> {
  const [competitors, artifacts, evidence, claims, versions, notifications] = await Promise.all([
    listEnterpriseCompetitors({ projectId: project.id }),
    listArtifacts({ projectId: project.id }),
    listProjectEvidence(project.id),
    listProjectClaims(project.id),
    listProjectReportVersions(project.id),
    listEnterpriseNotifications({ workspaceId: project.workspace_id, limit: 8 }).catch(() => []),
  ]);

  return {
    artifacts,
    claims,
    competitors,
    evidence,
    notifications,
    versions,
  };
}

export async function loadProjectSignals(project: ProjectRecord): Promise<Partial<ProjectData>> {
  const [
    businessPlan,
    qaEvaluation,
    claimValidation,
    readiness,
    competitorScores,
    evidenceGaps,
    redTeam,
    matrix,
    evalOps,
    registry,
    modelPolicy,
    modelRoute,
    usage,
    quota,
    retention,
    auditLogs,
  ] = await Promise.all([
    getProjectBusinessPlan(project.id).catch(() => null),
    getProjectQAEvaluation(project.id).catch(() => null),
    getProjectClaimValidation(project.id).catch(() => null),
    getProjectReadinessScore(project.id).catch(() => null),
    getProjectCompetitorScores(project.id).catch(() => null),
    getProjectEvidenceGaps(project.id).catch(() => null),
    getProjectRedTeam(project.id).catch(() => null),
    getProjectQualityMatrix(project.id).catch(() => null),
    getEnterpriseEvalOps({ projectId: project.id }).catch(() => null),
    listSourceRegistry(project.workspace_id).catch(() => []),
    getModelPolicy().catch(() => null),
    getModelRouteDecision().catch(() => null),
    getWorkspaceUsage(project.workspace_id).catch(() => null),
    getWorkspaceQuotaDecision(project.workspace_id).catch(() => null),
    getWorkspaceRetentionReport(project.workspace_id).catch(() => null),
    listEnterpriseAuditLogs({ workspaceId: project.workspace_id, limit: 50 }).catch(() => []),
  ]);

  return {
    auditLogs,
    businessPlan,
    claimValidation,
    competitorScores,
    evidenceGaps,
    evalOps,
    matrix,
    modelPolicy,
    modelRoute,
    qaEvaluation,
    quota,
    readiness,
    redTeam,
    registry,
    retention,
    usage,
  };
}

export async function loadReleaseGate(versionId: string): Promise<ReportReleaseGate | null> {
  return getReportReleaseGate(versionId).catch(() => null);
}
