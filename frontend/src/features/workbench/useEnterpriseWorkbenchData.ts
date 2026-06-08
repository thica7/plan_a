import { useEffect, useMemo, useState } from "react";

import {
  approveReportWorkflow,
  exportReportVersion,
  fillProjectEvidenceGaps,
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
  publishReportVersion,
  rejectReportWorkflow,
  startReportApprovalWorkflow,
  updateEvidenceQuality,
} from "../../api/client";
import type {
  ArtifactRecord,
  EvidenceGapFillResult,
  EvidenceQualityLabel,
  EvidenceRecord,
  ProjectRecord,
  ReportReleaseGate,
  ReportVersionRecord,
} from "../../api/types";
import { buildReportSourceBundle } from "../report/sourceBundle";
import { emptyProjectData, type EnterpriseView, type ProjectData } from "./types";

export type ReportAction = "start_review" | "approve" | "reject" | "publish";
export type ReportExportFormat = "markdown" | "html" | "csv";

export function useEnterpriseWorkbenchData(initialView: EnterpriseView) {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<EnterpriseView>(initialView);
  const [data, setData] = useState<ProjectData>(emptyProjectData);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [releaseGate, setReleaseGate] = useState<ReportReleaseGate | null>(null);
  const [gapFillResult, setGapFillResult] = useState<EvidenceGapFillResult | null>(null);
  const [query, setQuery] = useState("");
  const [isLoadingProjects, setLoadingProjects] = useState(true);
  const [isLoadingProject, setLoadingProject] = useState(false);
  const [isFillingGaps, setFillingGaps] = useState(false);
  const [isReportActionPending, setReportActionPending] = useState(false);
  const [lastExport, setLastExport] = useState<ArtifactRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setActiveView(initialView), [initialView]);

  useEffect(() => {
    refreshProjects();
  }, []);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );

  const selectedVersion = useMemo(
    () => data.versions.find((version) => version.id === selectedVersionId) ?? data.versions[0] ?? null,
    [data.versions, selectedVersionId],
  );

  const competitorById = useMemo(
    () => new Map(data.competitors.map((competitor) => [competitor.id, competitor])),
    [data.competitors],
  );

  const evidenceById = useMemo(
    () => new Map(data.evidence.map((item) => [item.id, item])),
    [data.evidence],
  );

  const reportSources = useMemo(
    () =>
      buildReportSourceBundle(data.evidence, {
        competitorById,
        scopedEvidenceIds: selectedVersion?.evidence_ids ?? null,
      }),
    [competitorById, data.evidence, selectedVersion?.evidence_ids],
  );

  const filteredEvidence = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return data.evidence;
    return data.evidence.filter((item) => {
      const competitor = competitorById.get(item.competitor_id)?.name ?? item.competitor_id;
      return [item.title, item.dimension, item.source_type, item.snippet, competitor]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [competitorById, data.evidence, query]);

  useEffect(() => {
    if (!selectedProject) {
      setData(emptyProjectData);
      setSelectedVersionId(null);
      setReleaseGate(null);
      return;
    }
    void refreshProject(selectedProject);
  }, [selectedProject?.id]);

  useEffect(() => {
    if (!selectedVersion) {
      setReleaseGate(null);
      return;
    }
    let active = true;
    setLastExport(null);
    getReportReleaseGate(selectedVersion.id)
      .then((gate) => {
        if (active) setReleaseGate(gate);
      })
      .catch(() => {
        if (active) setReleaseGate(null);
      });
    return () => {
      active = false;
    };
  }, [selectedVersion?.id]);

  function refreshProjects() {
    setLoadingProjects(true);
    setError(null);
    Promise.all([listEnterpriseProjects(), listEnterpriseNotifications({ limit: 8 })])
      .then(([items, notifications]) => {
        setProjects(items);
        setData((current) => ({ ...current, notifications }));
        setSelectedProjectId((current) => current ?? items[0]?.id ?? null);
      })
      .catch((err: Error) => {
        setError(err.message);
        setProjects([]);
      })
      .finally(() => setLoadingProjects(false));
  }

  async function refreshProject(project: ProjectRecord) {
    setLoadingProject(true);
    setError(null);
    setGapFillResult(null);
    try {
      const [competitors, artifacts, evidence, claims, versions, notifications] = await Promise.all([
        listEnterpriseCompetitors({ projectId: project.id }),
        listArtifacts({ projectId: project.id }),
        listProjectEvidence(project.id),
        listProjectClaims(project.id),
        listProjectReportVersions(project.id),
        listEnterpriseNotifications({ workspaceId: project.workspace_id, limit: 8 }).catch(() => []),
      ]);
      setData({
        ...emptyProjectData,
        artifacts,
        claims,
        competitors,
        evidence,
        notifications,
        versions,
      });
      setSelectedVersionId((current) =>
        current && versions.some((version) => version.id === current) ? current : versions[0]?.id ?? null,
      );
      setLoadingProject(false);
      void refreshProjectSignals(project);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load enterprise project");
      setData(emptyProjectData);
      setSelectedVersionId(null);
      setLoadingProject(false);
    }
  }

  async function refreshProjectSignals(project: ProjectRecord) {
    try {
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
      setData((current) => ({
        ...current,
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
        readiness,
        redTeam,
        registry,
        retention,
        usage,
        quota,
      }));
    } catch (err) {
      console.warn("Unable to refresh project signals", err);
    } finally {
      setLoadingProject(false);
    }
  }

  async function handleGapFill() {
    if (!selectedProject) return;
    setFillingGaps(true);
    setError(null);
    try {
      const result = await fillProjectEvidenceGaps(selectedProject.id);
      setGapFillResult(result);
      await refreshProject(selectedProject);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to fill evidence gaps");
    } finally {
      setFillingGaps(false);
    }
  }

  async function handleEvidenceQuality(evidenceId: string, qualityLabel: EvidenceQualityLabel) {
    try {
      const result = await updateEvidenceQuality(evidenceId, { quality_label: qualityLabel });
      setData((current) => ({
        ...current,
        evidence: current.evidence.map((item) => (item.id === evidenceId ? result.evidence : item)),
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update evidence quality");
    }
  }

  async function handleReportAction(action: ReportAction) {
    if (!selectedVersion) return;
    setReportActionPending(true);
    setError(null);
    try {
      if (action === "start_review") {
        await startReportApprovalWorkflow({
          report_version_id: selectedVersion.id,
          requested_by: "ui-reviewer",
          approver_ids: ["ui-reviewer"],
          timeout_seconds: 3600,
        });
      } else if (action === "approve") {
        await approveReportWorkflow(selectedVersion.id, {
          approver_id: "ui-reviewer",
          note: "Approved in report studio",
        });
      } else if (action === "reject") {
        await rejectReportWorkflow(selectedVersion.id, {
          approver_id: "ui-reviewer",
          note: "Rejected in report studio",
        });
      } else {
        await publishReportVersion(selectedVersion.id);
      }
      if (selectedProject) await refreshProject(selectedProject);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Report action failed");
    } finally {
      setReportActionPending(false);
    }
  }

  async function handleExport(format: ReportExportFormat) {
    if (!selectedVersion) return;
    setReportActionPending(true);
    setError(null);
    try {
      const result = await exportReportVersion(selectedVersion.id, format);
      setLastExport(result.artifact);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to export report");
    } finally {
      setReportActionPending(false);
    }
  }

  return {
    activeView,
    competitorById,
    data,
    error,
    evidenceById,
    filteredEvidence,
    gapFillResult,
    handleEvidenceQuality,
    handleExport,
    handleGapFill,
    handleReportAction,
    isFillingGaps,
    isLoadingProject,
    isLoadingProjects,
    isReportActionPending,
    lastExport,
    projects,
    query,
    refreshProjects,
    releaseGate,
    reportSources,
    selectedProject,
    selectedProjectId,
    selectedVersion,
    selectedVersionId,
    setActiveView,
    setQuery,
    setSelectedProjectId,
    setSelectedVersionId,
  };
}
