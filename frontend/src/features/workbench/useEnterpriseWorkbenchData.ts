import { useEffect, useMemo, useState } from "react";

import { fillProjectEvidenceGaps, getDecisionReplay, getTraceSpans, redoRun, updateEvidenceQuality } from "../../api/client";
import type {
  ArtifactRecord,
  EvidenceGapFillResult,
  EvidenceQualityLabel,
  ProjectRecord,
  ReportReleaseGate,
} from "../../api/types";
import { useKnowledgeStore, type KnowledgeRollbackRequest, type KnowledgeRollbackResult } from "../../stores/knowledgeStore";
import { loadProjectCore, loadProjectSignals, loadReleaseGate, loadWorkbenchProjects } from "./dataLoaders";
import { exportReportArtifact, performReportAction, type ReportAction, type ReportExportFormat } from "./reportOperations";
import { buildReleaseIssueRedoTarget } from "./releaseGateReview";
import {
  buildCompetitorMap,
  buildEvidenceMap,
  buildWorkbenchReportSources,
  filterWorkbenchEvidence,
} from "./selectors";
import { emptyProjectData, type EnterpriseView, type ProjectData } from "./types";

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
  const [gateRedoIssueId, setGateRedoIssueId] = useState<string | null>(null);
  const [gateRedoResult, setGateRedoResult] = useState<{
    issueId: string;
    runId: string;
    status: string;
  } | null>(null);
  const [kbRollbackIssueId, setKbRollbackIssueId] = useState<string | null>(null);
  const [kbRollbackResult, setKbRollbackResult] = useState<{
    issueId: string;
    result: KnowledgeRollbackResult;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const rollbackDocuments = useKnowledgeStore((state) => state.rollbackDocuments);

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

  const competitorById = useMemo(() => buildCompetitorMap(data.competitors), [data.competitors]);

  const evidenceById = useMemo(() => buildEvidenceMap(data.evidence), [data.evidence]);

  const reportSources = useMemo(
    () => buildWorkbenchReportSources(data.evidence, competitorById, selectedVersion),
    [competitorById, data.evidence, selectedVersion],
  );

  const filteredEvidence = useMemo(
    () => filterWorkbenchEvidence(data.evidence, competitorById, query),
    [competitorById, data.evidence, query],
  );

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
      setData((current) => ({ ...current, runDecisionReplay: null, runTraceSpans: [] }));
      return;
    }
    let active = true;
    setLastExport(null);
    loadReleaseGate(selectedVersion.id).then((gate) => {
      if (active) setReleaseGate(gate);
    });
    if (selectedVersion.run_id) {
      Promise.all([
        getTraceSpans(selectedVersion.run_id).catch(() => []),
        getDecisionReplay(selectedVersion.run_id).catch(() => null),
      ]).then(([runTraceSpans, runDecisionReplay]) => {
        if (active) setData((current) => ({ ...current, runDecisionReplay, runTraceSpans }));
      });
    } else {
      setData((current) => ({ ...current, runDecisionReplay: null, runTraceSpans: [] }));
    }
    return () => {
      active = false;
    };
  }, [selectedVersion?.id]);

  function refreshProjects() {
    setLoadingProjects(true);
    setError(null);
    loadWorkbenchProjects()
      .then(({ notifications, projects: items }) => {
        setData((current) => ({ ...current, notifications }));
        setProjects(items);
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
      const coreData = await loadProjectCore(project);
      setData({
        ...emptyProjectData,
        ...coreData,
      });
      setSelectedVersionId((current) =>
        current && coreData.versions.some((version) => version.id === current)
          ? current
          : coreData.versions[0]?.id ?? null,
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
      const signals = await loadProjectSignals(project);
      setData((current) => ({ ...current, ...signals }));
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

  async function handleRedoGateIssue(issueId: string) {
    if (!selectedVersion?.run_id) return;
    setGateRedoIssueId(issueId);
    setGateRedoResult(null);
    setError(null);
    try {
      const issue = releaseGate?.issues.find((item) => item.id === issueId) ?? null;
      const redoTarget = issue ? buildReleaseIssueRedoTarget(issue) : null;
      const updated = await redoRun(selectedVersion.run_id, redoTarget ? { issue_ids: redoTarget.issueIds } : undefined);
      setGateRedoResult({ issueId, runId: updated.id, status: updated.status });
      if (selectedProject) await refreshProject(selectedProject);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to trigger scoped redo");
    } finally {
      setGateRedoIssueId(null);
    }
  }
  async function handleKbRollbackIssue(issueId: string, request: KnowledgeRollbackRequest) {
    setKbRollbackIssueId(issueId);
    setKbRollbackResult(null);
    setError(null);
    try {
      const result = await rollbackDocuments(request);
      setKbRollbackResult({ issueId, result });
      if (selectedProject) await refreshProject(selectedProject);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to rollback KB evidence");
    } finally {
      setKbRollbackIssueId(null);
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
      await performReportAction(selectedVersion.id, action);
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
      const artifact = await exportReportArtifact(selectedVersion.id, format);
      setLastExport(artifact);
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
    gateRedoIssueId,
    gateRedoResult,
    handleEvidenceQuality,
    handleExport,
    handleGapFill,
    handleKbRollbackIssue,
    handleRedoGateIssue,
    handleReportAction,
    isFillingGaps,
    isLoadingProject,
    isLoadingProjects,
    kbRollbackIssueId,
    kbRollbackResult,
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
