import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ProjectRecord } from "../../api/types";
import {
  listArtifacts,
  listEnterpriseCompetitors,
  listEnterpriseNotifications,
  listProjectClaims,
  listProjectEvidence,
  listProjectReportVersions,
} from "../../api/client";
import { loadProjectCore } from "./dataLoaders";

vi.mock("../../api/client", () => ({
  getEnterpriseEvalOps: vi.fn(),
  getModelPolicy: vi.fn(),
  getModelRouteDecision: vi.fn(),
  getProjectBusinessPlan: vi.fn(),
  getProjectClaimValidation: vi.fn(),
  getProjectCompetitorScores: vi.fn(),
  getProjectEvidenceGaps: vi.fn(),
  getProjectQAEvaluation: vi.fn(),
  getProjectQualityMatrix: vi.fn(),
  getProjectReadinessScore: vi.fn(),
  getProjectRedTeam: vi.fn(),
  getReportReleaseGate: vi.fn(),
  getWorkspaceQuotaDecision: vi.fn(),
  getWorkspaceRetentionReport: vi.fn(),
  getWorkspaceUsage: vi.fn(),
  listArtifacts: vi.fn(),
  listEnterpriseAuditLogs: vi.fn(),
  listEnterpriseCompetitors: vi.fn(),
  listEnterpriseNotifications: vi.fn(),
  listEnterpriseProjects: vi.fn(),
  listProjectClaims: vi.fn(),
  listProjectEvidence: vi.fn(),
  listProjectReportVersions: vi.fn(),
  listSourceRegistry: vi.fn(),
}));

const project = {
  id: "project-1",
  workspace_id: "workspace-1",
  name: "AI coding assistants",
} as ProjectRecord;

describe("workbench data loaders", () => {
  beforeEach(() => {
    vi.mocked(listEnterpriseCompetitors).mockResolvedValue([]);
    vi.mocked(listArtifacts).mockResolvedValue([]);
    vi.mocked(listProjectEvidence).mockResolvedValue([]);
    vi.mocked(listProjectClaims).mockResolvedValue([]);
    vi.mocked(listProjectReportVersions).mockResolvedValue([]);
    vi.mocked(listEnterpriseNotifications).mockResolvedValue([]);
  });

  it("loads project notifications scoped by workspace and project", async () => {
    await loadProjectCore(project);

    expect(listEnterpriseNotifications).toHaveBeenCalledWith({
      workspaceId: "workspace-1",
      projectId: "project-1",
      limit: 8,
    });
  });
});
