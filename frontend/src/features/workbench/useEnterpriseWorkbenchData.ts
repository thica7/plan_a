import { useEffect, useMemo, useState } from "react";

import { fillProjectEvidenceGaps, updateEvidenceQuality } from "../../api/client";
import type {
  ArtifactRecord,
  EvidenceGapFillResult,
  EvidenceQualityLabel,
  ProjectRecord,
  ReportReleaseGate,
} from "../../api/types";
import { loadProjectCore, loadProjectSignals, loadReleaseGate, loadWorkbenchProjects } from "./dataLoaders";
import { exportReportArtifact, performReportAction, type ReportAction, type ReportExportFormat } from "./reportOperations";
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
      return;
    }
    let active = true;
    setLastExport(null);
    loadReleaseGate(selectedVersion.id).then((gate) => {
      if (active) setReleaseGate(gate);
    });
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
