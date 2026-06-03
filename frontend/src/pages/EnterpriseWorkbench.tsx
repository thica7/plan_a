import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Bell,
  Briefcase,
  CalendarClock,
  CheckCircle2,
  Database,
  Download,
  ExternalLink,
  FileText,
  Gauge,
  GitCompare,
  Layers,
  ListChecks,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import {
  exportReportVersion,
  fillProjectEvidenceGaps,
  getDecisionReplay,
  getEnterpriseEvalOps,
  getModelPolicy,
  getModelRouteDecision,
  getProjectClaimValidation,
  getProjectMemoryStats,
  getProjectEvidenceGaps,
  getProjectBusinessPlan,
  getProjectCompetitorScores,
  getProjectKnowledgeGraph,
  getProjectQAEvaluation,
  getProjectQualityMatrix,
  getProjectReadinessScore,
  getReportReleaseGate,
  getReportVersionDiff,
  getProjectRedTeam,
  getToolRegistry,
  getWorkspaceUsage,
  createSourceSnapshot,
  ingestProjectMemoryFeedback,
  listArtifacts,
  listEnterpriseAuditLogs,
  listEnterpriseCompetitors,
  listEnterpriseNotifications,
  listEnterpriseProjects,
  listProjectMemoryFeedback,
  listProjectClaims,
  listProjectEvidence,
  listProjectReportVersions,
  listSourceRegistry,
  publishReportVersion,
  recallProjectMemory,
  reviewProjectSchemaSuggestion,
  startMonitorWorkflow,
  approveReportWorkflow,
  rejectReportWorkflow,
  startReportApprovalWorkflow,
  startScheduledScanWorkflow,
  updateEvidenceQuality,
  updateProjectMemoryCandidate,
} from "../api/client";
import { ReportView } from "../features/report/ReportView";
import type {
  BusinessIntelPlan,
  BusinessQAEvaluation,
  BusinessQAFinding,
  ArtifactRecord,
  AuditLogRecord,
  ClaimValidationReport,
  ClaimValidationResult,
  ClaimRecord,
  CompetitorScoreReport,
  CompetitorRecord,
  DecisionReplayEvent,
  DecisionReplayReport,
  EvidenceGapFillResult,
  EvidenceGapItem,
  EvidenceGapReport,
  EvidenceQualityLabel,
  EvidenceRecord,
  EvalOpsMetric,
  EvalOpsReport,
  KnowledgeGraphReadModel,
  MemoryCandidateStatus,
  MemoryRecallContext,
  MemoryStats,
  ModelPolicyReport,
  ModelRouteDecision,
  NotificationRecord,
  ProjectReadinessScore,
  ProjectRecord,
  QualityAgentMatrix,
  QualityAgentMatrixEntry,
  RawSource,
  RedTeamFinding,
  RedTeamReport,
  ReportReleaseGate,
  ReportVersionDiff,
  ReportVersionRecord,
  SchemaEvolutionSuggestion,
  SourceSnapshotCreateRequest,
  SourceRegistryRecord,
  ToolRegistryReport,
  UserFeedbackRecord,
  WorkspaceUsageSummary,
} from "../api/types";

type EnterpriseTab = "competitors" | "evidence" | "claims" | "reports";

export function EnterpriseWorkbench({
  initialTab = "evidence",
}: {
  initialTab?: EnterpriseTab;
}) {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorRecord[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactRecord[]>([]);
  const [evidence, setEvidence] = useState<EvidenceRecord[]>([]);
  const [claims, setClaims] = useState<ClaimRecord[]>([]);
  const [versions, setVersions] = useState<ReportVersionRecord[]>([]);
  const [businessPlan, setBusinessPlan] = useState<BusinessIntelPlan | null>(null);
  const [qaEvaluation, setQaEvaluation] = useState<BusinessQAEvaluation | null>(null);
  const [claimValidation, setClaimValidation] = useState<ClaimValidationReport | null>(null);
  const [readinessScore, setReadinessScore] = useState<ProjectReadinessScore | null>(null);
  const [competitorScores, setCompetitorScores] = useState<CompetitorScoreReport | null>(null);
  const [evidenceGaps, setEvidenceGaps] = useState<EvidenceGapReport | null>(null);
  const [gapFillResult, setGapFillResult] = useState<EvidenceGapFillResult | null>(null);
  const [redTeam, setRedTeam] = useState<RedTeamReport | null>(null);
  const [qualityMatrix, setQualityMatrix] = useState<QualityAgentMatrix | null>(null);
  const [evalOps, setEvalOps] = useState<EvalOpsReport | null>(null);
  const [evalOpsBaselineRunId, setEvalOpsBaselineRunId] = useState<string | null>(null);
  const [sourceRegistry, setSourceRegistry] = useState<SourceRegistryRecord[]>([]);
  const [modelPolicy, setModelPolicy] = useState<ModelPolicyReport | null>(null);
  const [modelRoute, setModelRoute] = useState<ModelRouteDecision | null>(null);
  const [toolRegistry, setToolRegistry] = useState<ToolRegistryReport | null>(null);
  const [knowledgeGraph, setKnowledgeGraph] = useState<KnowledgeGraphReadModel | null>(null);
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null);
  const [memoryRecall, setMemoryRecall] = useState<MemoryRecallContext | null>(null);
  const [memoryFeedback, setMemoryFeedback] = useState<UserFeedbackRecord[]>([]);
  const [workspaceUsage, setWorkspaceUsage] = useState<WorkspaceUsageSummary | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLogRecord[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [diff, setDiff] = useState<ReportVersionDiff | null>(null);
  const [releaseGate, setReleaseGate] = useState<ReportReleaseGate | null>(null);
  const [decisionReplay, setDecisionReplay] = useState<DecisionReplayReport | null>(null);
  const [activeTab, setActiveTab] = useState<EnterpriseTab>(initialTab);
  const [query, setQuery] = useState("");
  const [isLoadingProjects, setLoadingProjects] = useState(true);
  const [isLoadingProject, setLoadingProject] = useState(false);
  const [isStartingScan, setStartingScan] = useState(false);
  const [isStartingMonitor, setStartingMonitor] = useState(false);
  const [isFillingGaps, setFillingGaps] = useState(false);
  const [isLoadingEvalOps, setLoadingEvalOps] = useState(false);
  const [isSubmittingReportApproval, setSubmittingReportApproval] = useState(false);
  const [isPublishingReport, setPublishingReport] = useState(false);
  const [isExportingReport, setExportingReport] = useState(false);
  const [isSavingMemoryFeedback, setSavingMemoryFeedback] = useState(false);
  const [reviewingMemoryCandidateId, setReviewingMemoryCandidateId] = useState<string | null>(null);
  const [reviewingSchemaSuggestionId, setReviewingSchemaSuggestionId] = useState<string | null>(null);
  const [snapshottingEvidenceId, setSnapshottingEvidenceId] = useState<string | null>(null);
  const [memoryFeedbackDraft, setMemoryFeedbackDraft] = useState("");
  const [lastReportExport, setLastReportExport] = useState<ArtifactRecord | null>(null);
  const [scanMessage, setScanMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function refreshProjects() {
    setLoadingProjects(true);
    setError(null);
    Promise.all([listEnterpriseProjects(), listEnterpriseNotifications({ limit: 8 })])
      .then(([items, notificationItems]) => {
        setProjects(items);
        setNotifications(notificationItems);
        setSelectedProjectId((current) => current ?? items[0]?.id ?? null);
      })
      .catch((err: Error) => {
        setError(err.message);
        setProjects([]);
        setNotifications([]);
      })
      .finally(() => setLoadingProjects(false));
  }

  useEffect(() => {
    refreshProjects();
  }, []);

  useEffect(() => {
    setActiveTab(initialTab);
  }, [initialTab]);

  useEffect(() => {
    const projectForLoad = projects.find((project) => project.id === selectedProjectId) ?? null;
    if (!selectedProjectId || !projectForLoad) {
      setCompetitors([]);
      setArtifacts([]);
      setEvidence([]);
      setClaims([]);
      setVersions([]);
      setBusinessPlan(null);
      setQaEvaluation(null);
      setClaimValidation(null);
      setReadinessScore(null);
      setCompetitorScores(null);
      setEvidenceGaps(null);
      setGapFillResult(null);
      setRedTeam(null);
      setQualityMatrix(null);
      setEvalOps(null);
      setSourceRegistry([]);
      setModelPolicy(null);
      setModelRoute(null);
      setToolRegistry(null);
      setKnowledgeGraph(null);
      setMemoryStats(null);
      setMemoryRecall(null);
      setMemoryFeedback([]);
      setWorkspaceUsage(null);
      setAuditLogs([]);
      setSelectedVersionId(null);
      setLastReportExport(null);
      setEvalOpsBaselineRunId(null);
      return;
    }

    let active = true;
    setLoadingProject(true);
    setError(null);
    Promise.all([
      listEnterpriseCompetitors({ projectId: selectedProjectId }),
      listArtifacts({ projectId: selectedProjectId }),
      listProjectEvidence(selectedProjectId),
      listProjectClaims(selectedProjectId),
      listProjectReportVersions(selectedProjectId),
      getProjectBusinessPlan(selectedProjectId),
      getProjectQAEvaluation(selectedProjectId),
      getProjectClaimValidation(selectedProjectId),
      getProjectReadinessScore(selectedProjectId),
      getProjectCompetitorScores(selectedProjectId),
      getProjectEvidenceGaps(selectedProjectId),
      getProjectRedTeam(selectedProjectId),
      getProjectQualityMatrix(selectedProjectId),
      getEnterpriseEvalOps({ projectId: selectedProjectId }),
      listSourceRegistry(projectForLoad.workspace_id),
      getModelPolicy(),
      getModelRouteDecision(),
      getToolRegistry(),
      getProjectKnowledgeGraph(selectedProjectId),
      getProjectMemoryStats(selectedProjectId),
      recallProjectMemory(selectedProjectId, {
        query: projectForLoad.topic,
        limit: 6,
        includeUnconfirmed: true,
      }),
      listProjectMemoryFeedback(selectedProjectId),
      getWorkspaceUsage(projectForLoad.workspace_id),
      listEnterpriseAuditLogs(projectForLoad.workspace_id),
    ])
      .then(
        ([
          competitorItems,
          artifactItems,
          evidenceItems,
          claimItems,
          versionItems,
          businessPlanValue,
          qaEvaluationValue,
          claimValidationValue,
          readinessScoreValue,
          competitorScoresValue,
          evidenceGapsValue,
          redTeamValue,
          qualityMatrixValue,
          evalOpsValue,
          sourceRegistryValue,
          modelPolicyValue,
          modelRouteValue,
          toolRegistryValue,
          knowledgeGraphValue,
          memoryStatsValue,
          memoryRecallValue,
          memoryFeedbackValue,
          workspaceUsageValue,
          auditLogItems,
        ]) => {
          if (!active) return;
          setCompetitors(competitorItems);
          setArtifacts(artifactItems);
          setEvidence(evidenceItems);
          setClaims(claimItems);
          setVersions(versionItems);
          setBusinessPlan(businessPlanValue);
          setQaEvaluation(qaEvaluationValue);
          setClaimValidation(claimValidationValue);
          setReadinessScore(readinessScoreValue);
          setCompetitorScores(competitorScoresValue);
          setEvidenceGaps(evidenceGapsValue);
          setGapFillResult(null);
          setRedTeam(redTeamValue);
          setQualityMatrix(qualityMatrixValue);
          setEvalOps(evalOpsValue);
          setSourceRegistry(sourceRegistryValue);
          setModelPolicy(modelPolicyValue);
          setModelRoute(modelRouteValue);
          setToolRegistry(toolRegistryValue);
          setKnowledgeGraph(knowledgeGraphValue);
          setMemoryStats(memoryStatsValue);
          setMemoryRecall(memoryRecallValue);
          setMemoryFeedback(memoryFeedbackValue);
          setWorkspaceUsage(workspaceUsageValue);
          setAuditLogs(auditLogItems);
          setSelectedVersionId(versionItems[0]?.id ?? null);
          setEvalOpsBaselineRunId(null);
        },
      )
      .catch((err: Error) => {
        if (!active) return;
        setError(err.message);
        setCompetitors([]);
        setArtifacts([]);
        setEvidence([]);
        setClaims([]);
        setVersions([]);
        setBusinessPlan(null);
        setQaEvaluation(null);
        setClaimValidation(null);
        setReadinessScore(null);
        setCompetitorScores(null);
        setEvidenceGaps(null);
        setGapFillResult(null);
        setRedTeam(null);
        setQualityMatrix(null);
        setEvalOps(null);
        setSourceRegistry([]);
        setModelPolicy(null);
        setModelRoute(null);
        setToolRegistry(null);
        setKnowledgeGraph(null);
        setMemoryStats(null);
        setMemoryRecall(null);
        setMemoryFeedback([]);
        setWorkspaceUsage(null);
        setAuditLogs([]);
        setSelectedVersionId(null);
        setDecisionReplay(null);
        setEvalOpsBaselineRunId(null);
      })
      .finally(() => {
        if (active) setLoadingProject(false);
      });

    return () => {
      active = false;
    };
  }, [projects, selectedProjectId]);

  useEffect(() => {
    if (!selectedVersionId) {
      setDiff(null);
      setReleaseGate(null);
      setLastReportExport(null);
      return;
    }
    setLastReportExport(null);

    let active = true;
    Promise.all([getReportVersionDiff(selectedVersionId), getReportReleaseGate(selectedVersionId)])
      .then(([diffValue, releaseGateValue]) => {
        if (!active) return;
        setDiff(diffValue);
        setReleaseGate(releaseGateValue);
      })
      .catch(() => {
        if (!active) return;
        setDiff(null);
        setReleaseGate(null);
      });
    return () => {
      active = false;
    };
  }, [selectedVersionId]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );
  const acceptedSchemaDimensions = useMemo(
    () => acceptedSchemaDimensionSet(selectedProject?.metadata),
    [selectedProject?.metadata],
  );
  const selectedVersion = useMemo(
    () => versions.find((version) => version.id === selectedVersionId) ?? null,
    [versions, selectedVersionId],
  );
  useEffect(() => {
    const runId = selectedVersion?.run_id;
    if (!runId) {
      setDecisionReplay(null);
      return;
    }

    let active = true;
    getDecisionReplay(runId)
      .then((replay) => {
        if (active) setDecisionReplay(replay);
      })
      .catch(() => {
        if (active) setDecisionReplay(null);
      });
    return () => {
      active = false;
    };
  }, [selectedVersion?.run_id]);
  const competitorById = useMemo(
    () => new Map(competitors.map((competitor) => [competitor.id, competitor])),
    [competitors],
  );
  const evidenceById = useMemo(
    () => new Map(evidence.map((item) => [item.id, item])),
    [evidence],
  );
  const reportSources = useMemo(
    () => buildReportSourceBundle(evidence, competitorById, selectedVersion),
    [competitorById, evidence, selectedVersion],
  );
  const snapshottedEvidenceIds = useMemo(
    () =>
      new Set(
        artifacts
          .map((artifact) => artifact.evidence_id)
          .filter((evidenceId): evidenceId is string => Boolean(evidenceId)),
      ),
    [artifacts],
  );
  const filteredEvidence = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return evidence;
    return evidence.filter((item) => {
      const competitor = competitorById.get(item.competitor_id)?.name ?? item.competitor_id;
      return [item.title, item.snippet, item.dimension, item.source_type, competitor]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [competitorById, evidence, query]);
  const latestVersion = versions[0] ?? null;
  const averageReliability =
    evidence.length > 0
      ? evidence.reduce((total, item) => total + item.reliability_score, 0) / evidence.length
      : 0;

  async function refreshAuditLogsForWorkspace(workspaceId: string | null | undefined) {
    if (!workspaceId) return;
    try {
      const items = await listEnterpriseAuditLogs(workspaceId);
      setAuditLogs(items);
    } catch (err) {
      console.warn("Unable to refresh audit logs", err);
    }
  }

  async function handleEvalOpsBaselineChange(nextRunId: string | null) {
    if (!selectedProjectId) return;
    const projectId = selectedProjectId;
    setEvalOpsBaselineRunId(nextRunId);
    setLoadingEvalOps(true);
    setScanMessage(null);
    setError(null);
    try {
      const report = await getEnterpriseEvalOps({
        projectId,
        baselineRunId: nextRunId ?? undefined,
      });
      setEvalOps(report);
      setScanMessage(
        nextRunId ? `EvalOps baseline set to ${nextRunId}.` : "EvalOps baseline cleared.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refresh EvalOps baseline.");
    } finally {
      setLoadingEvalOps(false);
    }
  }

  function handleStartScheduledScan() {
    if (!selectedProject) return;
    setStartingScan(true);
    setScanMessage(null);
    setError(null);
    startScheduledScanWorkflow({
      workspace_id: selectedProject.workspace_id,
      schedule_id: "manual-workbench-scan",
      requested_by: "workbench-user",
      project_ids: [selectedProject.id],
      dimensions: (businessPlan?.recommended_dimensions ?? ["pricing", "feature", "persona"]).slice(
        0,
        8,
      ),
      execution_mode: "auto",
      max_projects: 1,
    })
      .then((response) => {
        setScanMessage(`${response.status}: ${response.workflow_id}`);
        return listEnterpriseNotifications({
          workspaceId: selectedProject.workspace_id,
          limit: 8,
        });
      })
      .then((notificationItems) => {
        setNotifications(notificationItems);
        return refreshAuditLogsForWorkspace(selectedProject.workspace_id);
      })
      .catch((err: Error) => {
        setError(err.message);
      })
      .finally(() => setStartingScan(false));
  }

  function handleStartMonitor() {
    if (!selectedProject) return;
    setStartingMonitor(true);
    setScanMessage(null);
    setError(null);
    startMonitorWorkflow({
      workspace_id: selectedProject.workspace_id,
      project_id: selectedProject.id,
      monitor_id: "manual-workbench-monitor",
      requested_by: "workbench-user",
      dimensions: (businessPlan?.recommended_dimensions ?? ["pricing", "feature", "persona"]).slice(0, 8),
      execution_mode: "auto",
      interval_seconds: 604800,
      max_cycles: 1,
    })
      .then((response) => {
        setScanMessage(`${response.status}: ${response.workflow_id}`);
        return listEnterpriseNotifications({
          workspaceId: selectedProject.workspace_id,
          limit: 8,
        });
      })
      .then((notificationItems) => {
        setNotifications(notificationItems);
        return refreshAuditLogsForWorkspace(selectedProject.workspace_id);
      })
      .catch((err: Error) => {
        setError(err.message);
      })
      .finally(() => setStartingMonitor(false));
  }

  async function handleStartReportApproval() {
    if (!selectedProject || !selectedVersion) return;
    setSubmittingReportApproval(true);
    setScanMessage(null);
    setError(null);
    try {
      const response = await startReportApprovalWorkflow({
        report_version_id: selectedVersion.id,
        requested_by: "workbench-user",
        approver_ids: ["workbench-approver"],
        timeout_seconds: 86400,
      });
      const versionItems = await listProjectReportVersions(selectedProject.id);
      setVersions(versionItems);
      await refreshAuditLogsForWorkspace(selectedProject.workspace_id);
      setScanMessage(`Report approval ${response.status}: ${response.workflow_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to start report approval");
    } finally {
      setSubmittingReportApproval(false);
    }
  }

  async function handleSignalReportApproval(decision: "approved" | "rejected") {
    if (!selectedProject || !selectedVersion) return;
    setSubmittingReportApproval(true);
    setScanMessage(null);
    setError(null);
    try {
      const payload = {
        approver_id: "workbench-approver",
        note:
          decision === "approved"
            ? "Approved from Enterprise Workbench."
            : "Rejected from Enterprise Workbench.",
      };
      const response =
        decision === "approved"
          ? await approveReportWorkflow(selectedVersion.id, payload)
          : await rejectReportWorkflow(selectedVersion.id, payload);
      const [versionItems, gateValue] = await Promise.all([
        listProjectReportVersions(selectedProject.id),
        getReportReleaseGate(selectedVersion.id),
      ]);
      setVersions(versionItems);
      setReleaseGate(gateValue);
      await refreshAuditLogsForWorkspace(selectedProject.workspace_id);
      setScanMessage(`Report approval ${response.decision}: ${response.workflow_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update report approval");
    } finally {
      setSubmittingReportApproval(false);
    }
  }

  async function handlePublishReport() {
    if (!selectedProject || !selectedVersion) return;
    setPublishingReport(true);
    setScanMessage(null);
    setError(null);
    try {
      const updated = await publishReportVersion(selectedVersion.id);
      const [versionItems, gateValue] = await Promise.all([
        listProjectReportVersions(selectedProject.id),
        getReportReleaseGate(updated.id),
      ]);
      setVersions(versionItems);
      setSelectedVersionId(updated.id);
      setReleaseGate(gateValue);
      await refreshAuditLogsForWorkspace(selectedProject.workspace_id);
      setScanMessage(`Report v${updated.version_number} published.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to publish report");
    } finally {
      setPublishingReport(false);
    }
  }

  async function handleExportReport(format: "markdown" | "html" | "csv") {
    if (!selectedProject || !selectedVersion) return;
    setExportingReport(true);
    setScanMessage(null);
    setError(null);
    try {
      const result = await exportReportVersion(selectedVersion.id, format);
      setLastReportExport(result.artifact);
      const artifactItems = await listArtifacts({ projectId: selectedProject.id });
      setArtifacts(artifactItems);
      await refreshAuditLogsForWorkspace(selectedProject.workspace_id);
      setScanMessage(`Report v${selectedVersion.version_number} exported as ${format}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to export report");
    } finally {
      setExportingReport(false);
    }
  }

  async function handleFillEvidenceGaps() {
    if (!selectedProjectId) return;
    const projectId = selectedProjectId;
    setFillingGaps(true);
    setScanMessage(null);
    setError(null);
    try {
      const result = await fillProjectEvidenceGaps(projectId);
      const [
        evidenceItems,
        versionItems,
        qaEvaluationValue,
        readinessScoreValue,
        competitorScoresValue,
        redTeamValue,
      ] = await Promise.all([
        listProjectEvidence(projectId),
        listProjectReportVersions(projectId),
        getProjectQAEvaluation(projectId),
        getProjectReadinessScore(projectId),
        getProjectCompetitorScores(projectId),
        getProjectRedTeam(projectId),
      ]);
      setGapFillResult(result);
      setEvidenceGaps(result.report);
      setEvidence(evidenceItems);
      setVersions(versionItems);
      setQaEvaluation(qaEvaluationValue);
      setReadinessScore(readinessScoreValue);
      setCompetitorScores(competitorScoresValue);
      setRedTeam(redTeamValue);
      setSelectedVersionId(result.updated_report_version_id ?? versionItems[0]?.id ?? null);
      await refreshAuditLogsForWorkspace(selectedProject?.workspace_id);
      setScanMessage(`Gap fill linked ${result.added_evidence_count} candidate evidence item(s).`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to fill evidence gaps");
    } finally {
      setFillingGaps(false);
    }
  }

  async function handleReviewSchemaSuggestion(
    suggestion: SchemaEvolutionSuggestion,
    decision: "accepted" | "rejected",
  ) {
    if (!selectedProjectId) return;
    const projectId = selectedProjectId;
    setReviewingSchemaSuggestionId(suggestion.id);
    setScanMessage(null);
    setError(null);
    try {
      const result = await reviewProjectSchemaSuggestion(projectId, suggestion.id, {
        decision,
        note:
          decision === "accepted"
            ? "Accepted from Enterprise Workbench evidence-gap panel."
            : "Rejected from Enterprise Workbench evidence-gap panel.",
        suggestion,
      });
      const [projectItems, gapsValue, planValue] = await Promise.all([
        listEnterpriseProjects(),
        getProjectEvidenceGaps(projectId),
        getProjectBusinessPlan(projectId),
      ]);
      setProjects(projectItems.map((item) => (item.id === result.project.id ? result.project : item)));
      setEvidenceGaps(gapsValue);
      setBusinessPlan(planValue);
      await refreshAuditLogsForWorkspace(result.project.workspace_id);
      setScanMessage(
        `${decision === "accepted" ? "Accepted" : "Rejected"} schema dimension ${suggestion.normalized_dimension}.`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to review schema suggestion");
    } finally {
      setReviewingSchemaSuggestionId(null);
    }
  }

  async function handleSubmitMemoryFeedback() {
    if (!selectedProjectId || !memoryFeedbackDraft.trim()) return;
    const project = selectedProject;
    if (!project) return;
    setSavingMemoryFeedback(true);
    setError(null);
    try {
      const result = await ingestProjectMemoryFeedback(selectedProjectId, {
        feedback_type: "preference",
        target_type: "project",
        target_id: selectedProjectId,
        message: memoryFeedbackDraft.trim(),
        auto_confirm: false,
        tags: ["workbench"],
      });
      const [statsValue, recallValue] = await Promise.all([
        getProjectMemoryStats(selectedProjectId),
        recallProjectMemory(selectedProjectId, {
          query: project.topic,
          limit: 6,
          includeUnconfirmed: true,
        }),
      ]);
      setMemoryFeedback((current) => [result.feedback, ...current]);
      setMemoryRecall(recallValue);
      setMemoryStats(statsValue);
      setMemoryFeedbackDraft("");
      await refreshAuditLogsForWorkspace(project.workspace_id);
      setScanMessage(
        result.candidates.length > 0
          ? `Memory feedback saved with ${result.candidates.length} candidate(s) pending review.`
          : "Memory feedback saved.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save memory feedback");
    } finally {
      setSavingMemoryFeedback(false);
    }
  }

  async function handleMemoryCandidateStatusChange(
    candidateId: string,
    status: MemoryCandidateStatus,
  ) {
    if (!selectedProjectId || reviewingMemoryCandidateId) return;
    const projectId = selectedProjectId;
    setReviewingMemoryCandidateId(candidateId);
    setScanMessage(null);
    setError(null);
    try {
      const updated = await updateProjectMemoryCandidate(projectId, candidateId, status);
      const [statsValue, recallValue] = await Promise.all([
        getProjectMemoryStats(projectId),
        recallProjectMemory(projectId, {
          query: selectedProject?.topic ?? "",
          limit: 6,
          includeUnconfirmed: true,
        }),
      ]);
      setMemoryStats(statsValue);
      setMemoryRecall(recallValue);
      await refreshAuditLogsForWorkspace(selectedProject?.workspace_id);
      setScanMessage(`Memory ${updated.kind.replace(/_/g, " ")} marked ${updated.status}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update memory candidate");
    } finally {
      setReviewingMemoryCandidateId(null);
    }
  }

  async function handleCreateEvidenceSnapshot(item: EvidenceRecord) {
    if (!selectedProject) return;
    setSnapshottingEvidenceId(item.id);
    setScanMessage(null);
    setError(null);
    try {
      const competitorName = competitorById.get(item.competitor_id)?.name ?? item.competitor_id;
      const result = await createSourceSnapshot(
        buildEvidenceSnapshotRequest(selectedProject, item, competitorName),
      );
      const [artifactItems, sourceRegistryValue] = await Promise.all([
        listArtifacts({ projectId: selectedProject.id }),
        listSourceRegistry(selectedProject.workspace_id),
      ]);
      setArtifacts(artifactItems);
      setSourceRegistry(sourceRegistryValue);
      await refreshAuditLogsForWorkspace(selectedProject.workspace_id);
      setScanMessage(
        `Snapshot captured: ${result.artifact.filename} (${result.snapshot_quality_score}/100).`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to capture source snapshot");
    } finally {
      setSnapshottingEvidenceId(null);
    }
  }

  function handleQualityChange(evidenceId: string, qualityLabel: EvidenceQualityLabel) {
    setEvidence((items) =>
      items.map((item) =>
        item.id === evidenceId ? { ...item, quality_label: qualityLabel } : item,
      ),
    );
    updateEvidenceQuality(evidenceId, { quality_label: qualityLabel })
      .then(({ evidence: updated }) => {
        setEvidence((items) => items.map((item) => (item.id === updated.id ? updated : item)));
        if (selectedProjectId) {
          void Promise.all([
            getProjectQAEvaluation(selectedProjectId),
            getProjectReadinessScore(selectedProjectId),
            getProjectCompetitorScores(selectedProjectId),
            getProjectEvidenceGaps(selectedProjectId),
            getProjectRedTeam(selectedProjectId),
          ]).then(([qaValue, readinessValue, competitorScoresValue, evidenceGapsValue, redTeamValue]) => {
            setQaEvaluation(qaValue);
            setReadinessScore(readinessValue);
            setCompetitorScores(competitorScoresValue);
            setEvidenceGaps(evidenceGapsValue);
            setRedTeam(redTeamValue);
          });
        }
        void refreshAuditLogsForWorkspace(selectedProject?.workspace_id);
      })
      .catch((err: Error) => {
        setError(err.message);
        void listProjectEvidence(selectedProjectId ?? "").then(setEvidence);
      });
  }

  return (
    <section className="work-surface enterprise-workbench">
      <header className="page-header">
        <div>
          <h1>Enterprise workbench</h1>
          <p>Projects, evidence, claims, and report versions from the enterprise projection store.</p>
        </div>
        <button className="icon-text-button" type="button" onClick={refreshProjects}>
          <RefreshCw size={16} aria-hidden />
          Refresh
        </button>
      </header>

      {error ? <p className="error-line">{error}</p> : null}

      <div className="enterprise-layout">
        <aside className="panel project-rail">
          <div className="panel-heading-row">
            <h2>Projects</h2>
            <Briefcase size={17} aria-hidden />
          </div>
          {isLoadingProjects ? <p className="muted-line">Loading projects...</p> : null}
          {!isLoadingProjects && projects.length === 0 ? (
            <div className="empty-state">
              <Database size={18} aria-hidden />
              <span>No enterprise projects yet.</span>
            </div>
          ) : null}
          <div className="project-list">
            {projects.map((project) => (
              <button
                className={project.id === selectedProjectId ? "project-card active" : "project-card"}
                key={project.id}
                type="button"
                onClick={() => setSelectedProjectId(project.id)}
              >
                <strong>{project.name}</strong>
                <span>{project.competitor_layer} / v{project.competitor_set_hash.slice(0, 8)}</span>
                <em>{formatDate(project.updated_at)}</em>
              </button>
            ))}
          </div>
          <div className="operations-panel">
            <div className="panel-heading-row">
              <h2>Operations</h2>
              <CalendarClock size={17} aria-hidden />
            </div>
            <button
              className="icon-text-button full-width"
              disabled={!selectedProject || isStartingScan}
              type="button"
              onClick={handleStartScheduledScan}
            >
              <RefreshCw size={16} aria-hidden />
              {isStartingScan ? "Starting scan" : "Scan selected"}
            </button>
            <button
              className="icon-text-button full-width"
              disabled={!selectedProject || isStartingMonitor}
              type="button"
              onClick={handleStartMonitor}
            >
              <CalendarClock size={16} aria-hidden />
              {isStartingMonitor ? "Starting monitor" : "Monitor selected"}
            </button>
            {scanMessage ? <p className="muted-line">{scanMessage}</p> : null}
            {workspaceUsage ? <WorkspaceUsagePanel usage={workspaceUsage} /> : null}
            <div className="notification-list">
              {notifications.slice(0, 5).map((notification) => (
                <article className={`notification-item ${notification.severity}`} key={notification.id}>
                  <div>
                    <Bell size={14} aria-hidden />
                    <strong>{notification.title}</strong>
                  </div>
                  <span>{notification.status} / {formatDate(notification.created_at)}</span>
                </article>
              ))}
            </div>
            {notifications.length === 0 ? <p className="muted-line">No notifications yet.</p> : null}
          </div>
        </aside>

        <div className="enterprise-main">
          {selectedProject ? (
            <>
              <section className="panel project-summary">
                <div>
                  <span className="eyebrow">Project</span>
                  <h2>{selectedProject.name}</h2>
                  <p>{selectedProject.topic}</p>
                </div>
                <div className="metric-grid compact">
                  <Metric icon={<Layers size={17} aria-hidden />} label="Competitors" value={competitors.length} />
                  <Metric icon={<Database size={17} aria-hidden />} label="Evidence" value={evidence.length} />
                  <Metric icon={<ShieldCheck size={17} aria-hidden />} label="Claims" value={claims.length} />
                  <Metric icon={<FileText size={17} aria-hidden />} label="Versions" value={versions.length} />
                </div>
                <div className="project-meta-row">
                  <span>Layer {businessPlan?.competitor_layer.layer ?? selectedProject.competitor_layer}</span>
                  <span>Scenario {businessPlan?.scenario_pack.name ?? selectedProject.scenario_id ?? "none"}</span>
                  <span>Reliability {formatPercent(averageReliability)}</span>
                  <span>Latest {latestVersion ? `v${latestVersion.version_number}` : "none"}</span>
                </div>
              </section>

              {businessPlan ? (
                <section className="panel scenario-panel">
                  <div className="panel-heading-row">
                    <h2>{businessPlan.scenario_pack.name}</h2>
                    <CheckCircle2 size={17} aria-hidden />
                  </div>
                  <p>{businessPlan.scenario_pack.description}</p>
                  <div className="scenario-chip-row">
                    {businessPlan.recommended_dimensions.map((dimension) => (
                      <span key={dimension}>{dimension}</span>
                    ))}
                  </div>
                  <div className="qa-rule-row">
                    {businessPlan.qa_rules.map((rule) => (
                      <span key={rule.id} className={`qa-rule ${rule.severity}`}>
                        {rule.name}
                      </span>
                    ))}
                  </div>
                </section>
              ) : null}

              {readinessScore ? <ReadinessScorePanel readinessScore={readinessScore} /> : null}

              {evalOps ? (
                <EvalOpsPanel
                  baselineRunId={evalOpsBaselineRunId}
                  isLoading={isLoadingEvalOps}
                  onBaselineRunChange={handleEvalOpsBaselineChange}
                  report={evalOps}
                  versions={versions}
                />
              ) : null}

              <DecisionReplayPanel replay={decisionReplay} runId={selectedVersion?.run_id} />

              {qualityMatrix ? <QualityAgentMatrixPanel matrix={qualityMatrix} /> : null}

              {claimValidation ? <ClaimValidationPanel report={claimValidation} /> : null}

              <SourceRegistryPanel sources={sourceRegistry} />

              <ResearchEvidencePanel
                claims={claims}
                competitors={competitors}
                evidence={evidence}
              />

              <GovernanceRuntimePanel
                knowledgeGraph={knowledgeGraph}
                modelPolicy={modelPolicy}
                modelRoute={modelRoute}
                toolRegistry={toolRegistry}
              />

              <AuditLogPanel logs={auditLogs} />

              <MemoryAgentPanel
                feedback={memoryFeedback}
                feedbackDraft={memoryFeedbackDraft}
                isSubmitting={isSavingMemoryFeedback}
                reviewingCandidateId={reviewingMemoryCandidateId}
                onCandidateStatusChange={handleMemoryCandidateStatusChange}
                onFeedbackDraftChange={setMemoryFeedbackDraft}
                onSubmitFeedback={handleSubmitMemoryFeedback}
                recall={memoryRecall}
                stats={memoryStats}
              />

              <ArtifactStorePanel artifacts={artifacts} />

              {competitorScores ? <CompetitorScorePanel report={competitorScores} /> : null}

              {evidenceGaps ? (
                <EvidenceGapPanel
                  acceptedSchemaDimensions={acceptedSchemaDimensions}
                  fillResult={gapFillResult}
                  isFilling={isFillingGaps}
                  reviewingSuggestionId={reviewingSchemaSuggestionId}
                  onFill={handleFillEvidenceGaps}
                  onReviewSchemaSuggestion={handleReviewSchemaSuggestion}
                  report={evidenceGaps}
                />
              ) : null}

              {redTeam ? <RedTeamPanel report={redTeam} /> : null}

              {qaEvaluation ? <QAEvaluationPanel evaluation={qaEvaluation} /> : null}

              <section className="panel competitor-strip-panel">
                <div className="panel-heading-row">
                  <h2>Competitor library</h2>
                  <Layers size={17} aria-hidden />
                </div>
                <div className="competitor-strip">
                  {competitors.map((competitor) => (
                    <span key={competitor.id} title={competitor.id}>
                      {competitor.name}
                      <em>{competitor.layer}</em>
                    </span>
                  ))}
                </div>
              </section>

              <section className="panel enterprise-data-panel">
                <div className="enterprise-tabs">
                  <button
                    className={activeTab === "competitors" ? "active" : ""}
                    type="button"
                    onClick={() => setActiveTab("competitors")}
                  >
                    Competitors
                  </button>
                  <button
                    className={activeTab === "evidence" ? "active" : ""}
                    type="button"
                    onClick={() => setActiveTab("evidence")}
                  >
                    Evidence
                  </button>
                  <button
                    className={activeTab === "claims" ? "active" : ""}
                    type="button"
                    onClick={() => setActiveTab("claims")}
                  >
                    Claims
                  </button>
                  <button
                    className={activeTab === "reports" ? "active" : ""}
                    type="button"
                    onClick={() => setActiveTab("reports")}
                  >
                    Reports
                  </button>
                </div>

                {isLoadingProject ? <p className="muted-line">Loading project data...</p> : null}
                {activeTab === "competitors" ? (
                  <CompetitorLibrary competitors={competitors} scores={competitorScores} />
                ) : null}
                {activeTab === "evidence" ? (
                  <EvidenceTable
                    capturedEvidenceIds={snapshottedEvidenceIds}
                    competitorById={competitorById}
                    evidence={filteredEvidence}
                    onQualityChange={handleQualityChange}
                    onSnapshotEvidence={handleCreateEvidenceSnapshot}
                    query={query}
                    setQuery={setQuery}
                    snapshottingEvidenceId={snapshottingEvidenceId}
                  />
                ) : null}
                {activeTab === "claims" ? (
                  <ClaimList
                    claims={claims}
                    competitorById={competitorById}
                    evidenceById={evidenceById}
                  />
                ) : null}
                {activeTab === "reports" ? (
                  <ReportHistory
                    diff={diff}
                    isApprovalSubmitting={isSubmittingReportApproval}
                    isExporting={isExportingReport}
                    isPublishing={isPublishingReport}
                    lastExport={lastReportExport}
                    onApproveReport={() => handleSignalReportApproval("approved")}
                    onExportReport={handleExportReport}
                    onPublishReport={handlePublishReport}
                    onRejectReport={() => handleSignalReportApproval("rejected")}
                    onStartApproval={handleStartReportApproval}
                    releaseGate={releaseGate}
                    sourceAliases={reportSources.aliases}
                    sources={reportSources.sources}
                    selectedVersion={selectedVersion}
                    selectedVersionId={selectedVersionId}
                    setSelectedVersionId={setSelectedVersionId}
                    versions={versions}
                  />
                ) : null}
              </section>
            </>
          ) : (
            <div className="empty-state">
              <Briefcase size={18} aria-hidden />
              <span>Select a project after an analysis run has completed.</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function CompetitorLibrary({
  competitors,
  scores,
}: {
  competitors: CompetitorRecord[];
  scores: CompetitorScoreReport | null;
}) {
  const scoreByCompetitor = new Map(
    (scores?.scores ?? []).map((score) => [score.competitor_id, score]),
  );
  if (competitors.length === 0) {
    return (
      <div className="empty-state">
        <Layers size={18} aria-hidden />
        <span>No competitors are linked to this project.</span>
      </div>
    );
  }
  return (
    <div className="competitor-library-grid">
      {competitors.map((competitor) => {
        const score = scoreByCompetitor.get(competitor.id);
        return (
          <article className="competitor-library-card" key={competitor.id}>
            <div>
              <strong>{competitor.name}</strong>
              <span>{competitor.layer}</span>
            </div>
            <p>{competitor.homepage_url ?? "No homepage recorded"}</p>
            <div className="project-meta-row">
              <span>Aliases {competitor.aliases.length}</span>
              <span>Score {score ? score.total_score : "-"}</span>
              <span>Rank {score ? `#${score.rank}` : "-"}</span>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function AuditLogPanel({ logs }: { logs: AuditLogRecord[] }) {
  const recentLogs = logs.slice(0, 6);
  const reportLogs = logs.filter(
    (log) => log.resource_type === "report_version" || log.action.startsWith("report_version."),
  );
  const statusChanges = logs.filter((log) => log.action === "report_version.status_changed");
  const actorCount = new Set(logs.map((log) => `${log.actor_type}:${log.actor_id ?? "unknown"}`)).size;

  return (
    <section className="panel readiness-panel pass">
      <div className="panel-heading-row">
        <h2>Audit log</h2>
        <ListChecks size={17} aria-hidden />
      </div>
      <div className="metric-grid compact">
        <Metric icon={<ListChecks size={17} aria-hidden />} label="Events" value={logs.length} />
        <Metric icon={<FileText size={17} aria-hidden />} label="Reports" value={reportLogs.length} />
        <Metric icon={<ShieldCheck size={17} aria-hidden />} label="Status" value={statusChanges.length} />
        <Metric icon={<Briefcase size={17} aria-hidden />} label="Actors" value={actorCount} />
      </div>
      {recentLogs.length > 0 ? (
        <div className="recommendation-list">
          {recentLogs.map((log) => (
            <article className="recommendation-card low" key={log.id} title={log.id}>
              <strong>{log.action}</strong>
              <span>
                {log.resource_type} / {formatDate(log.created_at)}
              </span>
              <p>{auditLogSummary(log)}</p>
              <div className="project-meta-row">
                <span>{log.actor_type}</span>
                <span>{log.actor_id ?? "unknown actor"}</span>
                <span>{log.resource_id}</span>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted-line">No audit events recorded for this workspace.</p>
      )}
    </section>
  );
}

function EvalOpsPanel({
  baselineRunId,
  isLoading,
  onBaselineRunChange,
  report,
  versions,
}: {
  baselineRunId: string | null;
  isLoading: boolean;
  onBaselineRunChange: (runId: string | null) => void;
  report: EvalOpsReport;
  versions: ReportVersionRecord[];
}) {
  const watchMetrics = report.metrics.filter((metric) => metric.status !== "pass").slice(0, 4);
  const coverageLiftRate = evalOpsMetricValue(report, "coverage_lift_rate");
  const citationValidityRate = evalOpsMetricValue(report, "citation_validity_rate");
  const judgeScore = report.llm_judge_avg_score ?? report.judge_avg_score;
  const watchCases = [...report.cases]
    .sort((left, right) => {
      const statusDelta = evalOpsStatusRank(right.status) - evalOpsStatusRank(left.status);
      return statusDelta || left.score - right.score || left.case_id.localeCompare(right.case_id);
    })
    .slice(0, 4);
  const baselineOptions = versions
    .filter((version): version is ReportVersionRecord & { run_id: string } => Boolean(version.run_id))
    .map((version) => ({
      label: `v${version.version_number} · ${formatDate(version.created_at)}`,
      runId: version.run_id,
      versionId: version.id,
    }));
  return (
    <section className={`panel readiness-panel ${report.regression_gate_status}`}>
      <div className="panel-heading-row">
        <h2>EvalOps</h2>
        <div className="panel-heading-actions">
          <label className="compact-select">
            <span>Baseline</span>
            <select
              disabled={isLoading || baselineOptions.length === 0}
              value={baselineRunId ?? ""}
              onChange={(event) => onBaselineRunChange(event.target.value || null)}
            >
              <option value="">No baseline</option>
              {baselineOptions.map((option) => (
                <option key={option.versionId} value={option.runId}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          {report.regression_gate_status === "pass" ? (
            <CheckCircle2 size={17} aria-hidden />
          ) : (
            <AlertTriangle size={17} aria-hidden />
          )}
        </div>
      </div>
      <div className="metric-grid compact">
        <Metric
          icon={<Gauge size={17} aria-hidden />}
          label="Quality"
          value={report.report_quality_score}
        />
        <Metric
          icon={<ListChecks size={17} aria-hidden />}
          label="Golden"
          value={formatPercent(report.golden_set_pass_rate)}
        />
        <Metric
          icon={<Gauge size={17} aria-hidden />}
          label="Judge"
          value={judgeScore.toFixed(1)}
        />
        <Metric
          icon={<Search size={17} aria-hidden />}
          label="Recall"
          value={formatPercent(report.source_recall)}
        />
        <Metric
          icon={<ShieldCheck size={17} aria-hidden />}
          label="Citation valid"
          value={citationValidityRate === null ? "n/a" : formatPercent(citationValidityRate)}
        />
        <Metric
          icon={<CheckCircle2 size={17} aria-hidden />}
          label="Real chain"
          value={formatPercent(report.real_quality_chain_rate)}
        />
        <Metric
          icon={<CalendarClock size={17} aria-hidden />}
          label="Hours saved"
          value={report.task_time_saved_hours.toFixed(1)}
        />
        <Metric
          icon={<Briefcase size={17} aria-hidden />}
          label="Manual base"
          value={report.manual_baseline_hours.toFixed(1)}
        />
        <Metric
          icon={<RefreshCw size={17} aria-hidden />}
          label="System time"
          value={report.automation_runtime_hours.toFixed(1)}
        />
        <Metric
          icon={<Gauge size={17} aria-hidden />}
          label="Saved"
          value={formatPercent(report.time_savings_rate)}
        />
      </div>
      <div className="project-meta-row">
        <span>{report.regression_gate_status}</span>
        <span>{report.run_count} run(s)</span>
        <span>Real {report.real_run_count}</span>
        <span>Demo {report.demo_run_count}</span>
        <span>Judge {report.judge_mode}</span>
        <span>Baseline {report.baseline_run_id ?? "none"}</span>
        <span>Delta {formatScoreDelta(report.average_delta_score)}</span>
        <span>Citation validity {citationValidityRate === null ? "n/a" : formatPercent(citationValidityRate)}</span>
        <span>Coverage lift {coverageLiftRate === null ? "n/a" : formatSignedPercent(coverageLiftRate)}</span>
        <span>Regressed {report.regressed_run_count}</span>
        <span>HITL {formatPercent(report.hitl_enabled_run_rate)}</span>
        <span>Human fix {formatPercent(report.human_correction_rate)}</span>
        <span>Redo {report.redo_iteration_count}</span>
        <span>Convergence {formatPercent(report.redo_convergence_ratio)}</span>
        <span>Manual {report.manual_baseline_hours_per_report.toFixed(1)}h / report</span>
        <span>${report.cost_per_report_usd.toFixed(4)} / report</span>
        <span>{report.golden_set_size} golden cases</span>
      </div>
      <p>{report.regression_gate_reason}</p>
      {report.judge_fallback_reason ? <p className="muted-line">{report.judge_fallback_reason}</p> : null}
      {watchMetrics.length > 0 ? (
        <div className="readiness-breakdown">
          {watchMetrics.map((metric) => (
            <ScoreBar
              key={metric.name}
              label={metric.name.replace(/_/g, " ")}
              value={metricProgressPercent(metric)}
            />
          ))}
        </div>
      ) : null}
      {watchCases.length > 0 ? (
        <div className="recommendation-list">
          {watchCases.map((item) => (
            <article className={`recommendation-card ${evalOpsCasePriority(item.status)}`} key={item.case_id}>
              <strong>{item.name}</strong>
              <span>
                {item.status} / {item.score}
              </span>
              <p>{item.summary}</p>
              <div className="project-meta-row">
                <span>Target {item.target_run_id ?? "n/a"}</span>
                <span>Baseline {item.baseline_run_id ?? "none"}</span>
              </div>
            </article>
          ))}
        </div>
      ) : null}
      {report.recommendations.length > 0 ? (
        <div className="recommendation-list">
          {report.recommendations.slice(0, 3).map((item) => (
            <article className="recommendation-card medium" key={item}>
              <strong>EvalOps</strong>
              <span>next</span>
              <p>{item}</p>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function DecisionReplayPanel({
  replay,
  runId,
}: {
  replay: DecisionReplayReport | null;
  runId?: string | null;
}) {
  if (!runId) return null;

  const timelineEvents = [...(replay?.events ?? [])]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .slice(0, 8);
  const eventTypeCounts = replay
    ? Object.entries(replay.event_type_counts).sort((left, right) => right[1] - left[1])
    : [];
  const status = !replay
    ? "warn"
    : replay.blocker_count > 0
      ? "fail"
      : replay.warn_count > 0
        ? "warn"
        : "pass";

  return (
    <section className={`panel readiness-panel ${status}`}>
      <div className="panel-heading-row">
        <h2>Decision replay</h2>
        {status === "pass" ? (
          <CheckCircle2 size={17} aria-hidden />
        ) : (
          <AlertTriangle size={17} aria-hidden />
        )}
      </div>
      {replay ? (
        <>
          <div className="metric-grid compact">
            <Metric icon={<ListChecks size={17} aria-hidden />} label="Events" value={replay.event_count} />
            <Metric icon={<Gauge size={17} aria-hidden />} label="Coverage" value={`${replay.replay_coverage_score}%`} />
            <Metric icon={<AlertTriangle size={17} aria-hidden />} label="Blockers" value={replay.blocker_count} />
            <Metric icon={<ShieldCheck size={17} aria-hidden />} label="Warnings" value={replay.warn_count} />
          </div>
          <div className="project-meta-row">
            <span>Run {runId}</span>
            <span>Types {Object.keys(replay.event_type_counts).length}</span>
            <span>Status {replay.status}</span>
            <span>Generated {formatDate(replay.generated_at)}</span>
          </div>
          {eventTypeCounts.length > 0 ? (
            <div className="decision-event-types">
              {eventTypeCounts.slice(0, 8).map(([eventType, count]) => (
                <span key={eventType}>
                  {formatDecisionEventType(eventType)}
                  <em>{count}</em>
                </span>
              ))}
            </div>
          ) : null}
          {timelineEvents.length > 0 ? (
            <div className="decision-timeline">
              {timelineEvents.map((event) => (
                <article
                  className={`decision-event-card ${decisionReplayPriority(event.event_type)}`}
                  key={event.id}
                >
                  <div>
                    <strong>{formatDecisionEventType(event.event_type)}</strong>
                    <span>{event.agent ?? "system"} / {formatDate(event.created_at)}</span>
                  </div>
                  <p>{event.message}</p>
                  <div className="project-meta-row">
                    <span>Evidence {event.evidence_ids.length}</span>
                    <span>Claims {event.claim_ids.length}</span>
                    <span>Spans {event.related_span_ids.length}</span>
                  </div>
                  <TargetAnchorLinks evidenceIds={event.evidence_ids} claimIds={event.claim_ids} />
                  <em>{decisionPayloadSummary(event)}</em>
                </article>
              ))}
            </div>
          ) : (
            <p className="muted-line">No replayable decision events yet.</p>
          )}
        </>
      ) : (
        <p className="muted-line">Decision replay is unavailable for the selected report run.</p>
      )}
    </section>
  );
}

function QualityAgentMatrixPanel({ matrix }: { matrix: QualityAgentMatrix }) {
  const blockerCount = matrix.entries.reduce((total, entry) => total + entry.blocker_count, 0);
  const warnCount = matrix.entries.reduce((total, entry) => total + entry.warn_count, 0);
  const watchEntries = [...matrix.entries]
    .sort((left, right) => qualityStatusRank(right.status) - qualityStatusRank(left.status))
    .slice(0, 5);

  return (
    <section className={`panel readiness-panel ${matrix.status}`}>
      <div className="panel-heading-row">
        <h2>Quality matrix</h2>
        {matrix.status === "pass" ? (
          <CheckCircle2 size={17} aria-hidden />
        ) : (
          <AlertTriangle size={17} aria-hidden />
        )}
      </div>
      <div className="metric-grid compact">
        <Metric icon={<Gauge size={17} aria-hidden />} label="Score" value={matrix.overall_score} />
        <Metric icon={<ListChecks size={17} aria-hidden />} label="Agents" value={matrix.entries.length} />
        <Metric icon={<AlertTriangle size={17} aria-hidden />} label="Blockers" value={blockerCount} />
        <Metric icon={<ShieldCheck size={17} aria-hidden />} label="Warnings" value={warnCount} />
      </div>
      <div className="project-meta-row">
        <span>Status {matrix.status}</span>
        <span>Generated {formatDate(matrix.generated_at)}</span>
      </div>
      <div className="recommendation-list">
        {watchEntries.map((entry) => (
          <article className={`recommendation-card ${qualityEntryPriority(entry)}`} key={entry.agent_name}>
            <strong>{entry.agent_name}</strong>
            <span>{entry.status} / {entry.framework}</span>
            <QualityPeerReviewLine entry={entry} />
            <p>{entry.summary}</p>
            <TargetAnchorLinks evidenceIds={entry.evidence_ids} claimIds={entry.claim_ids} />
          </article>
        ))}
      </div>
    </section>
  );
}

function QualityPeerReviewLine({ entry }: { entry: QualityAgentMatrixEntry }) {
  const peerReviewedBy = metadataStringList(entry.metadata, "peer_reviewed_by");
  const reviewTargets = metadataStringList(entry.metadata, "review_targets");
  if (peerReviewedBy.length === 0 && reviewTargets.length === 0) return null;
  return (
    <span>
      Reviewed by {peerReviewedBy.length ? peerReviewedBy.join(", ") : "none"}
      {reviewTargets.length ? `; reviews ${reviewTargets.join(", ")}` : ""}
    </span>
  );
}

function ClaimValidationPanel({ report }: { report: ClaimValidationReport }) {
  const panelStatus = report.blocker_count > 0 ? "blocker" : report.warn_count > 0 ? "warn" : "pass";
  const watchIssues = report.issues.slice(0, 4);
  const weakResults = report.results
    .filter((result) => result.status !== "supported")
    .slice(0, 4);

  return (
    <section className={`panel readiness-panel ${panelStatus}`}>
      <div className="panel-heading-row">
        <h2>Claim validation</h2>
        {panelStatus === "pass" ? (
          <CheckCircle2 size={17} aria-hidden />
        ) : (
          <AlertTriangle size={17} aria-hidden />
        )}
      </div>
      <div className="metric-grid compact">
        <Metric icon={<Gauge size={17} aria-hidden />} label="Consistency" value={report.self_consistency_score} />
        <Metric icon={<CheckCircle2 size={17} aria-hidden />} label="Supported" value={report.supported_count} />
        <Metric icon={<AlertTriangle size={17} aria-hidden />} label="Weak" value={report.weak_count} />
        <Metric icon={<ShieldCheck size={17} aria-hidden />} label="Blocked" value={report.blocked_count} />
      </div>
      <div className="project-meta-row">
        <span>Total claims {report.total_claims}</span>
        <span>Unsupported {report.unsupported_count}</span>
        <span>Low consistency {report.low_consistency_count}</span>
        <span>Issues {report.issue_count}</span>
      </div>
      {watchIssues.length > 0 ? (
        <div className="recommendation-list">
          {watchIssues.map((issue) => (
            <article className={`recommendation-card ${issue.severity === "blocker" ? "high" : "medium"}`} key={issue.id}>
              <strong>{issue.issue_type.replace(/_/g, " ")}</strong>
              <span>{issue.severity} / {issue.claim_id}</span>
              <p>{issue.message}</p>
              <ClaimValidationTargetLinks claimId={issue.claim_id} evidenceIds={issue.evidence_ids} />
            </article>
          ))}
        </div>
      ) : null}
      {weakResults.length > 0 ? (
        <div className="recommendation-list">
          {weakResults.map((result) => (
            <article
              className={`recommendation-card ${claimValidationResultPriority(result)}`}
              key={result.claim_id}
              title={result.claim_id}
            >
              <strong>{result.status}</strong>
              <span>
                support {result.support_score} / self {result.self_consistency_score}
              </span>
              <p>
                text {result.text_support_score}, evidence {result.evidence_quality_score},
                triangulation {result.triangulation_score}. {formatConsistencyVotes(result)}
              </p>
              {result.validation_samples.length > 0 ? (
                <p className="muted-line">{formatValidationSamples(result)}</p>
              ) : null}
              <ClaimValidationTargetLinks claimId={result.claim_id} evidenceIds={result.usable_evidence_ids} />
            </article>
          ))}
        </div>
      ) : (
        <p className="muted-line">All validated claims are currently supported.</p>
      )}
    </section>
  );
}

function ClaimValidationTargetLinks({
  claimId,
  evidenceIds,
}: {
  claimId: string;
  evidenceIds: string[];
}) {
  return <TargetAnchorLinks claimIds={[claimId]} evidenceIds={evidenceIds} />;
}

function formatConsistencyVotes(result: ClaimValidationResult) {
  const text = result.consistency_votes.text_support ?? 0;
  const evidence = result.consistency_votes.evidence_quality ?? 0;
  const triangulation = result.consistency_votes.triangulation ?? 0;
  const usableEvidenceCount = result.usable_evidence_ids.length;
  const issueCount = result.issue_ids.length;
  return `Votes ${text}/${evidence}/${triangulation}; evidence ${usableEvidenceCount}; issues ${issueCount}.`;
}

function formatValidationSamples(result: ClaimValidationResult) {
  return result.validation_samples
    .slice(0, 3)
    .map((sample) => {
      const label = sample.checker.replace(/_/g, " ");
      return `${label} ${sample.vote} ${sample.score}/${sample.threshold}`;
    })
    .join("; ");
}

function claimValidationResultPriority(result: ClaimValidationResult) {
  if (result.status === "blocked" || result.status === "unsupported") {
    return "high";
  }
  return "medium";
}

function SourceRegistryPanel({ sources }: { sources: SourceRegistryRecord[] }) {
  const activeSources = sources.filter((source) => source.is_active);
  const allowedSources = sources.filter((source) => source.robots_status === "allowed");
  const blockedSources = sources.filter((source) => source.robots_status === "blocked");
  const trustedSources = sources.filter((source) =>
    ["official", "verified"].includes(source.trust_level),
  );
  const recentSources = [...sources]
    .sort((left, right) => right.last_seen_at.localeCompare(left.last_seen_at))
    .slice(0, 4);

  return (
    <section className={`panel readiness-panel ${blockedSources.length > 0 ? "warn" : "pass"}`}>
      <div className="panel-heading-row">
        <h2>Source registry</h2>
        {blockedSources.length > 0 ? (
          <AlertTriangle size={17} aria-hidden />
        ) : (
          <ShieldCheck size={17} aria-hidden />
        )}
      </div>
      <div className="metric-grid compact">
        <Metric icon={<Database size={17} aria-hidden />} label="Sources" value={sources.length} />
        <Metric icon={<CheckCircle2 size={17} aria-hidden />} label="Active" value={activeSources.length} />
        <Metric icon={<ShieldCheck size={17} aria-hidden />} label="Allowed" value={allowedSources.length} />
        <Metric icon={<AlertTriangle size={17} aria-hidden />} label="Blocked" value={blockedSources.length} />
      </div>
      <div className="project-meta-row">
        <span>Trusted {formatPercent(sources.length ? trustedSources.length / sources.length : 0)}</span>
        <span>Robots known {formatPercent(sources.length ? (allowedSources.length + blockedSources.length) / sources.length : 0)}</span>
      </div>
      {recentSources.length > 0 ? (
        <div className="competitor-strip">
          {recentSources.map((source) => (
            <span key={source.id} title={source.homepage_url ?? source.domain}>
              {source.display_name || source.domain}
              <em>{source.trust_level} / {source.robots_status}</em>
            </span>
          ))}
        </div>
      ) : (
        <p className="muted-line">No source registry entries yet.</p>
      )}
    </section>
  );
}

function ResearchEvidencePanel({
  claims,
  competitors,
  evidence,
}: {
  claims: ClaimRecord[];
  competitors: CompetitorRecord[];
  evidence: EvidenceRecord[];
}) {
  const researchEvidence = evidence.filter((item) => isResearchEvidenceSource(item.source_type));
  const researchEvidenceIds = new Set(researchEvidence.map((item) => item.id));
  const coveredCompetitorIds = new Set(researchEvidence.map((item) => item.competitor_id));
  const personaClaimCount = claims.filter(
    (claim) =>
      isPersonaClaim(claim.claim_type)
      && claim.evidence_ids.some((evidenceId) => researchEvidenceIds.has(evidenceId)),
  ).length;
  const surveyCount = researchEvidence.filter((item) => item.source_type === "survey_simulated").length;
  const interviewCount = researchEvidence.filter((item) => item.source_type === "interview_record").length;
  const manualCount = researchEvidence.filter((item) =>
    ["manual_transcript", "manual_note", "manual"].includes(item.source_type),
  ).length;
  const coverageRate = competitors.length > 0 ? coveredCompetitorIds.size / competitors.length : 0;
  const averageResearchReliability =
    researchEvidence.length > 0
      ? researchEvidence.reduce((total, item) => total + item.reliability_score, 0) / researchEvidence.length
      : 0;
  const status = researchEvidence.length === 0
    ? "warn"
    : coverageRate >= 0.5 && personaClaimCount > 0
      ? "pass"
      : "warn";
  const recentEvidence = researchEvidence.slice(0, 4);

  return (
    <section className={`panel readiness-panel ${status}`}>
      <div className="panel-heading-row">
        <h2>Survey / Interview</h2>
        {status === "pass" ? (
          <CheckCircle2 size={17} aria-hidden />
        ) : (
          <AlertTriangle size={17} aria-hidden />
        )}
      </div>
      <div className="metric-grid compact">
        <Metric icon={<ListChecks size={17} aria-hidden />} label="Research" value={researchEvidence.length} />
        <Metric icon={<Search size={17} aria-hidden />} label="Coverage" value={formatPercent(coverageRate)} />
        <Metric icon={<ShieldCheck size={17} aria-hidden />} label="Persona claims" value={personaClaimCount} />
        <Metric
          icon={<Gauge size={17} aria-hidden />}
          label="Reliability"
          value={formatPercent(averageResearchReliability)}
        />
      </div>
      <div className="project-meta-row">
        <span>Survey {surveyCount}</span>
        <span>Interview {interviewCount}</span>
        <span>Manual {manualCount}</span>
        <span>Covered competitors {coveredCompetitorIds.size}/{competitors.length}</span>
      </div>
      {recentEvidence.length > 0 ? (
        <div className="recommendation-list">
          {recentEvidence.map((item) => (
            <article className="recommendation-card medium" key={item.id}>
              <strong>{item.source_type.replace(/_/g, " ")}</strong>
              <span>{formatPercent(item.reliability_score)}</span>
              <p>{item.title}</p>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted-line">No survey, interview, or manual transcript evidence has been attached yet.</p>
      )}
    </section>
  );
}

function isResearchEvidenceSource(sourceType: string) {
  return ["survey_simulated", "interview_record", "manual_transcript", "manual_note", "manual"].includes(sourceType);
}

function isPersonaClaim(claimType: string) {
  const normalized = claimType.toLowerCase();
  return normalized.includes("persona") || normalized.includes("user") || normalized.includes("buyer");
}

function GovernanceRuntimePanel({
  knowledgeGraph,
  modelPolicy,
  modelRoute,
  toolRegistry,
}: {
  knowledgeGraph: KnowledgeGraphReadModel | null;
  modelPolicy: ModelPolicyReport | null;
  modelRoute: ModelRouteDecision | null;
  toolRegistry: ToolRegistryReport | null;
}) {
  const blocked = modelRoute?.status === "blocked" || (modelPolicy?.blocker_count ?? 0) > 0;
  const guarded = (toolRegistry?.guarded_count ?? 0) + (toolRegistry?.disabled_count ?? 0);
  const panelStatus = blocked ? "fail" : guarded > 0 ? "warn" : "pass";
  const governedTools =
    toolRegistry?.entries
      .filter((entry) => entry.status !== "enabled" || !entry.allowed_in_real_mode)
      .slice(0, 4) ?? [];
  const sideEffectTools =
    toolRegistry?.entries
      .filter((entry) => entry.side_effects.some((effect) => effect !== "none"))
      .slice(0, 4) ?? [];
  const modelCandidates = modelRoute?.candidates ?? [];
  const selectedProviderKind =
    modelRoute?.selected?.provider_kind ?? modelRoute?.fallback?.provider_kind ?? null;
  const kgRelations = summarizeKnowledgeGraphRelations(knowledgeGraph).slice(0, 5);

  return (
    <section className={`panel readiness-panel ${panelStatus}`}>
      <div className="panel-heading-row">
        <h2>Governance runtime</h2>
        {panelStatus === "pass" ? (
          <ShieldCheck size={17} aria-hidden />
        ) : (
          <AlertTriangle size={17} aria-hidden />
        )}
      </div>
      <div className="metric-grid compact">
        <Metric
          icon={<Gauge size={17} aria-hidden />}
          label="Route"
          value={modelRoute?.status ?? "loading"}
        />
        <Metric
          icon={<Briefcase size={17} aria-hidden />}
          label="Model"
          value={formatRouteCandidate(modelRoute?.selected ?? modelRoute?.fallback)}
        />
        <Metric
          icon={<ListChecks size={17} aria-hidden />}
          label="Tools"
          value={toolRegistry?.total_count ?? "-"}
        />
        <Metric
          icon={<GitCompare size={17} aria-hidden />}
          label="KG edges"
          value={knowledgeGraph?.edge_count ?? "-"}
        />
      </div>
      <div className="project-meta-row">
        <span>Policy {modelPolicy?.status ?? "loading"}</span>
        <span>Real exec {modelPolicy?.real_execution_allowed ? "yes" : "no"}</span>
        <span>Guarded tools {toolRegistry?.guarded_count ?? "-"}</span>
        <span>Disabled tools {toolRegistry?.disabled_count ?? "-"}</span>
        <span>KG nodes {knowledgeGraph?.node_count ?? "-"}</span>
      </div>
      {modelRoute?.blocked_reasons.length ? (
        <div className="recommendation-list">
          {modelRoute.blocked_reasons.slice(0, 3).map((reason) => (
            <article className="recommendation-card high" key={reason}>
              <strong>Model route</strong>
              <span>blocked</span>
              <p>{reason}</p>
            </article>
          ))}
        </div>
      ) : null}
      {modelCandidates.length > 0 ? (
        <div className="recommendation-list">
          {modelCandidates.map((candidate) => {
            const isActive = candidate.provider_kind === selectedProviderKind;
            return (
              <article
                className={`recommendation-card ${candidate.configured ? "medium" : "high"}`}
                key={`${candidate.provider_kind}-${candidate.provider_name}-${candidate.model_name}`}
              >
                <strong>{candidate.provider_name}</strong>
                <span>
                  {isActive ? "active" : candidate.configured ? "ready" : "missing"} / {candidate.provider_kind}
                </span>
                <p>
                  Q {candidate.quality_score} / Cost {candidate.cost_score} / Compliance{" "}
                  {candidate.compliance_score}
                </p>
              </article>
            );
          })}
        </div>
      ) : null}
      {governedTools.length > 0 ? (
        <div className="competitor-strip">
          {governedTools.map((entry) => (
            <span key={entry.name} title={entry.reason}>
              {entry.name}
              <em>{entry.status} / {entry.category}</em>
            </span>
          ))}
        </div>
      ) : (
        <p className="muted-line">Tool registry has no guarded or disabled tools.</p>
      )}
      {sideEffectTools.length > 0 ? (
        <div className="recommendation-list">
          {sideEffectTools.map((entry) => (
            <article className="recommendation-card medium" key={entry.name}>
              <strong>{entry.name}</strong>
              <span>
                {entry.side_effects.filter((effect) => effect !== "none").join(", ")} / $
                {entry.estimated_cost_usd.toFixed(2)}
              </span>
              <p>{entry.policy_tags.join(", ") || "no policy tags"}</p>
            </article>
          ))}
        </div>
      ) : null}
      {kgRelations.length > 0 ? (
        <div className="competitor-strip">
          {kgRelations.map((relation) => (
            <span key={relation.relation}>
              {relation.relation}
              <em>
                {relation.count} edge(s) / {relation.evidenceLinkCount} evidence link(s)
              </em>
            </span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function MemoryAgentPanel({
  feedback,
  feedbackDraft,
  isSubmitting,
  reviewingCandidateId,
  onCandidateStatusChange,
  onFeedbackDraftChange,
  onSubmitFeedback,
  recall,
  stats,
}: {
  feedback: UserFeedbackRecord[];
  feedbackDraft: string;
  isSubmitting: boolean;
  reviewingCandidateId: string | null;
  onCandidateStatusChange: (candidateId: string, status: MemoryCandidateStatus) => void;
  onFeedbackDraftChange: (value: string) => void;
  onSubmitFeedback: () => void;
  recall: MemoryRecallContext | null;
  stats: MemoryStats | null;
}) {
  const candidates = recall?.candidates ?? [];
  const confirmedCandidates = candidates.filter((candidate) => candidate.status === "confirmed");
  const averageMatch = candidates.length
    ? candidates.reduce((total, candidate) => total + candidate.match_score, 0) / candidates.length
    : 0;
  const panelStatus = (stats?.confirmed_candidate_count ?? 0) > 0 ? "pass" : "warn";

  return (
    <section className={`panel readiness-panel ${panelStatus}`}>
      <div className="panel-heading-row">
        <h2>MemoryAgent</h2>
        {confirmedCandidates.length > 0 ? (
          <CheckCircle2 size={17} aria-hidden />
        ) : (
          <AlertTriangle size={17} aria-hidden />
        )}
      </div>
      <div className="metric-grid compact">
        <Metric
          icon={<Database size={17} aria-hidden />}
          label="Feedback"
          value={stats?.feedback_count ?? "-"}
        />
        <Metric
          icon={<ListChecks size={17} aria-hidden />}
          label="Candidates"
          value={stats?.candidate_count ?? "-"}
        />
        <Metric
          icon={<CheckCircle2 size={17} aria-hidden />}
          label="Confirmed"
          value={stats?.confirmed_candidate_count ?? "-"}
        />
        <Metric
          icon={<Gauge size={17} aria-hidden />}
          label="Recall"
          value={formatPercent(averageMatch)}
        />
      </div>
      <div className="project-meta-row">
        <span>Prompt context {recall?.prompt_context.length ?? 0}</span>
        <span>Visible candidates {candidates.length}</span>
        <span>Latest feedback {feedback[0] ? formatDate(feedback[0].created_at) : "none"}</span>
      </div>
      <form
        className="memory-feedback-form"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmitFeedback();
        }}
      >
        <textarea
          aria-label="Memory feedback"
          onChange={(event) => onFeedbackDraftChange(event.target.value)}
          placeholder="Preference, correction, source rule, or writing style"
          rows={3}
          value={feedbackDraft}
        />
        <button
          className="icon-text-button"
          disabled={isSubmitting || !feedbackDraft.trim()}
          type="submit"
        >
          {isSubmitting ? (
            <RefreshCw className="spin" size={15} aria-hidden />
          ) : (
            <CheckCircle2 size={15} aria-hidden />
          )}
          {isSubmitting ? "Saving" : "Save memory"}
        </button>
      </form>
      {candidates.length > 0 ? (
        <div className="recommendation-list">
          {candidates.slice(0, 5).map((candidate) => (
            <article
              className={`recommendation-card ${memoryCandidatePriority(candidate.status)}`}
              key={candidate.id}
            >
              <strong>{candidate.kind.replace(/_/g, " ")}</strong>
              <span>{candidate.status} / {formatPercent(candidate.match_score)}</span>
              <p>{candidate.statement}</p>
              <div className="project-meta-row">
                <span>Weight {formatPercent(candidate.weight)}</span>
                <span>Used {candidate.used_count}</span>
                <span>{candidate.tags.slice(0, 3).join(", ") || "untagged"}</span>
              </div>
              {candidate.status === "candidate" ? (
                <div className="panel-heading-actions">
                  <button
                    className="icon-text-button"
                    disabled={reviewingCandidateId !== null}
                    type="button"
                    onClick={() => onCandidateStatusChange(candidate.id, "confirmed")}
                  >
                    {reviewingCandidateId === candidate.id ? (
                      <RefreshCw className="spin" size={15} aria-hidden />
                    ) : (
                      <CheckCircle2 size={15} aria-hidden />
                    )}
                    Confirm
                  </button>
                  <button
                    className="icon-text-button"
                    disabled={reviewingCandidateId !== null}
                    type="button"
                    onClick={() => onCandidateStatusChange(candidate.id, "rejected")}
                  >
                    <AlertTriangle size={15} aria-hidden />
                    Reject
                  </button>
                </div>
              ) : null}
            </article>
          ))}
        </div>
      ) : (
        <p className="muted-line">No recalled memory candidates yet.</p>
      )}
      {recall?.prompt_context.length ? (
        <div className="recommendation-list">
          {recall.prompt_context.slice(0, 2).map((item) => (
            <article className="recommendation-card medium" key={item}>
              <strong>Prompt memory</strong>
              <span>context</span>
              <p>{item}</p>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function ArtifactStorePanel({ artifacts }: { artifacts: ArtifactRecord[] }) {
  const snapshotCount = artifacts.filter((artifact) =>
    ["web_snapshot", "pdf", "screenshot"].includes(artifact.artifact_type),
  ).length;
  const linkedCount = artifacts.filter((artifact) => artifact.evidence_id).length;
  const snapshotQualityScores = artifacts
    .map((artifact) => artifactMetadataNumber(artifact, "snapshot_quality_score"))
    .filter((score): score is number => score !== null);
  const averageSnapshotQuality = snapshotQualityScores.length
    ? snapshotQualityScores.reduce((total, score) => total + score, 0) / snapshotQualityScores.length
    : 0;
  const snapshotWarningCount = artifacts.reduce(
    (total, artifact) => total + artifactMetadataListCount(artifact, "snapshot_warnings"),
    0,
  );
  const registryLinkedCount = artifacts.filter((artifact) =>
    artifactMetadataString(artifact, "source_registry_id"),
  ).length;
  const externalCount = artifacts.filter((artifact) =>
    ["external", "s3", "oss"].includes(artifact.storage_backend),
  ).length;
  const totalBytes = artifacts.reduce((total, artifact) => total + artifact.byte_size, 0);
  const recentArtifacts = [...artifacts]
    .sort((left, right) => right.created_at.localeCompare(left.created_at))
    .slice(0, 4);
  const panelStatus = artifacts.length === 0 || snapshotWarningCount > 0 ? "warn" : "pass";

  return (
    <section className={`panel readiness-panel ${panelStatus}`}>
      <div className="panel-heading-row">
        <h2>Artifact store</h2>
        {panelStatus === "pass" ? (
          <Database size={17} aria-hidden />
        ) : (
          <AlertTriangle size={17} aria-hidden />
        )}
      </div>
      <div className="metric-grid compact">
        <Metric icon={<FileText size={17} aria-hidden />} label="Artifacts" value={artifacts.length} />
        <Metric icon={<Search size={17} aria-hidden />} label="Snapshots" value={snapshotCount} />
        <Metric icon={<ShieldCheck size={17} aria-hidden />} label="Linked" value={linkedCount} />
        <Metric
          icon={<Gauge size={17} aria-hidden />}
          label="Snapshot Q"
          value={snapshotQualityScores.length ? Math.round(averageSnapshotQuality) : "-"}
        />
        <Metric icon={<Database size={17} aria-hidden />} label="External" value={externalCount} />
        <Metric icon={<AlertTriangle size={17} aria-hidden />} label="Warnings" value={snapshotWarningCount} />
      </div>
      <div className="project-meta-row">
        <span>Total size {formatBytes(totalBytes)}</span>
        <span>Evidence link {formatPercent(artifacts.length ? linkedCount / artifacts.length : 0)}</span>
        <span>Registry link {formatPercent(artifacts.length ? registryLinkedCount / artifacts.length : 0)}</span>
      </div>
      {recentArtifacts.length > 0 ? (
        <div className="recommendation-list">
          {recentArtifacts.map((artifact) => (
            <article className="recommendation-card medium" key={artifact.id}>
              <strong>{artifact.filename}</strong>
              <span>
                {artifact.artifact_type} / {artifact.storage_backend} / Q{" "}
                {artifactMetadataNumber(artifact, "snapshot_quality_score") ?? "-"}
              </span>
              <p>{artifact.uri}</p>
              <div className="project-meta-row">
                <span>{formatBytes(artifact.byte_size)}</span>
                <span>{artifactMetadataString(artifact, "source_domain") ?? "manual-source"}</span>
                <span>Warnings {artifactMetadataListCount(artifact, "snapshot_warnings")}</span>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted-line">No artifacts or source snapshots captured yet.</p>
      )}
    </section>
  );
}

function ReadinessScorePanel({
  readinessScore,
}: {
  readinessScore: ProjectReadinessScore;
}) {
  return (
    <section className={`panel readiness-panel ${readinessScore.risk_level}`}>
      <div className="panel-heading-row">
        <h2>Readiness score</h2>
        <Gauge size={17} aria-hidden />
      </div>
      <div className="readiness-score-row">
        <strong>{readinessScore.score}</strong>
        <div>
          <span>{readinessScore.risk_level.replace("_", " ")}</span>
          <p>{readinessScore.summary}</p>
        </div>
      </div>
      <div className="readiness-breakdown">
        <ScoreBar label="Evidence" value={readinessScore.evidence_score} />
        <ScoreBar label="Claims" value={readinessScore.claim_score} />
        <ScoreBar label="Coverage" value={readinessScore.coverage_score} />
        <ScoreBar label="QA" value={readinessScore.qa_score} />
      </div>
      <div className="recommendation-list">
        {readinessScore.recommendations.slice(0, 4).map((item) => (
          <article className={`recommendation-card ${item.priority}`} key={item.id}>
            <strong>{item.title}</strong>
            <span>{item.priority} / {item.action_type.replace("_", " ")}</span>
            <p>{item.detail}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function CompetitorScorePanel({ report }: { report: CompetitorScoreReport }) {
  if (report.scores.length === 0) {
    return null;
  }
  return (
    <section className="panel competitor-score-panel">
      <div className="panel-heading-row">
        <h2>Competitor scores</h2>
        <ListChecks size={17} aria-hidden />
      </div>
      <div className="scorecard-grid">
        {report.scores.slice(0, 4).map((score) => (
          <article className="competitor-score-card" key={score.competitor_id}>
            <div>
              <span>#{score.rank}</span>
              <strong>{score.competitor_name}</strong>
              <em>{score.total_score}</em>
            </div>
            <ScoreBar label="Evidence" value={score.evidence_score} />
            <ScoreBar label="Claims" value={score.claim_score} />
            <ScoreBar label="Coverage" value={score.coverage_score} />
            <p>{score.recommendation}</p>
            <div className="dimension-score-row">
              {score.dimension_scores.slice(0, 4).map((dimension) => (
                <span key={dimension.dimension} title={dimension.rationale}>
                  {dimension.dimension}
                  <em>{dimension.score}</em>
                </span>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="score-bar">
      <span>
        {label}
        <em>{value}%</em>
      </span>
      <div>
        <i style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

function WorkspaceUsagePanel({ usage }: { usage: WorkspaceUsageSummary }) {
  const rows = [
    {
      label: "Runs",
      value: `${usage.run_count}/${usage.monthly_run_quota}`,
      ratio: usage.run_usage_ratio,
    },
    {
      label: "Tokens",
      value: `${usage.total_tokens_estimate}/${usage.monthly_token_quota}`,
      ratio: usage.token_usage_ratio,
    },
    {
      label: "Cost",
      value: `$${usage.cost_estimate_usd.toFixed(4)}/$${usage.monthly_cost_quota_usd.toFixed(2)}`,
      ratio: usage.cost_usage_ratio,
    },
  ];
  return (
    <div className={`workspace-usage-panel ${usage.status}`}>
      <div>
        <Gauge size={14} aria-hidden />
        <strong>Workspace usage</strong>
        <span>{usage.status}</span>
      </div>
      {rows.map((row) => (
        <label key={row.label}>
          <span>
            {row.label}
            <em>{row.value}</em>
          </span>
          <meter max={1} min={0} value={Math.min(row.ratio, 1)} />
        </label>
      ))}
    </div>
  );
}

function EvidenceGapPanel({
  acceptedSchemaDimensions,
  fillResult,
  isFilling,
  reviewingSuggestionId,
  onFill,
  onReviewSchemaSuggestion,
  report,
}: {
  acceptedSchemaDimensions: Set<string>;
  fillResult: EvidenceGapFillResult | null;
  isFilling: boolean;
  reviewingSuggestionId: string | null;
  onFill: () => void;
  onReviewSchemaSuggestion: (
    suggestion: SchemaEvolutionSuggestion,
    decision: "accepted" | "rejected",
  ) => void;
  report: EvidenceGapReport;
}) {
  const status = report.critical_count > 0 ? "critical" : report.high_count > 0 ? "high" : "clear";
  return (
    <section className={`panel evidence-gap-panel ${status}`}>
      <div className="panel-heading-row">
        <h2>Evidence gaps</h2>
        <button
          className="icon-text-button"
          disabled={isFilling || report.gap_count === 0}
          type="button"
          onClick={onFill}
        >
          {isFilling ? <RefreshCw className="spin" size={15} aria-hidden /> : <Search size={15} aria-hidden />}
          {isFilling ? "Filling" : "Fill gaps"}
        </button>
      </div>
      <div className="evidence-gap-summary">
        <span>
          <strong>{report.gap_count}</strong>
          <em>Total gaps</em>
        </span>
        <span>
          <strong>{report.critical_count}</strong>
          <em>Critical</em>
        </span>
        <span>
          <strong>{report.high_count}</strong>
          <em>High</em>
        </span>
        <span>
          <strong>{report.medium_count}</strong>
          <em>Medium</em>
        </span>
      </div>
      <PydanticAiExecutionPanel
        available={report.pydantic_ai_available}
        executionMode={report.pydantic_ai_execution_mode}
        fallback={report.pydantic_ai_model_backed_fallback}
        modelName={report.pydantic_ai_model_name}
        modelBackedRequested={report.pydantic_ai_model_backed_requested}
        runtimeAgentCreated={report.pydantic_ai_runtime_agent_created}
        runtimePromptChars={report.pydantic_ai_runtime_prompt_chars}
        runtimePromptHash={report.pydantic_ai_runtime_prompt_hash}
        typedContractEnforced={report.typed_contract_enforced}
      />
      {fillResult ? (
        <div className="evidence-gap-summary">
          <span>
            <strong>{fillResult.filled_gap_count}</strong>
            <em>Filled gaps</em>
          </span>
          <span>
            <strong>{formatPercent(fillResult.gap_closure_rate)}</strong>
            <em>Closure</em>
          </span>
          <span>
            <strong>{fillResult.added_evidence_count}</strong>
            <em>Linked candidates</em>
          </span>
          <span>
            <strong>{fillResult.online_collected_evidence_count}</strong>
            <em>Online collected</em>
          </span>
          <span>
            <strong>{fillResult.online_failure_count}</strong>
            <em>Online failures</em>
          </span>
          <span>
            <strong>{fillResult.after_gap_count}</strong>
            <em>Remaining</em>
          </span>
          <span>
            <strong>{fillResult.updated_report_version_id ? "yes" : "no"}</strong>
            <em>Draft version</em>
          </span>
          <span>
            <strong>{fillResult.gap_fill_chain_closed ? "yes" : "no"}</strong>
            <em>Closed loop</em>
          </span>
          <span>
            <strong>{fillResult.release_gate_blocker_delta}</strong>
            <em>Blocker delta</em>
          </span>
          <span>
            <strong>{fillResult.release_gate_warn_delta}</strong>
            <em>Warn delta</em>
          </span>
          <span>
            <strong>
              {fillResult.readiness_score_delta > 0 ? "+" : ""}
              {fillResult.readiness_score_delta}
            </strong>
            <em>Readiness</em>
          </span>
        </div>
      ) : null}
      {fillResult?.decision_events.length ? (
        <div className="recommendation-list">
          {fillResult.decision_events.slice(0, 3).map((event) => (
            <article className="recommendation-card medium" key={`${event.event_type}-${event.created_at}`}>
              <strong>{event.event_type.replace(".", " ")}</strong>
              <span>{event.evidence_ids.length} evidence</span>
              <p>{event.message}</p>
              <em>{gapFillEventSummary(event.payload)}</em>
            </article>
          ))}
        </div>
      ) : null}
      {report.schema_suggestions.length > 0 ? (
        <div className="recommendation-list">
          {report.schema_suggestions.slice(0, 3).map((suggestion) => (
            <article className="recommendation-card medium" key={suggestion.id}>
              <strong>{suggestion.normalized_dimension}</strong>
              <span>
                {acceptedSchemaDimensions.has(suggestion.normalized_dimension)
                  ? "accepted"
                  : suggestion.status.replace("_", " ")}
              </span>
              <p>{suggestion.reason}</p>
              <em>
                {suggestion.proposed_skill.subagent_class} / {suggestion.proposed_skill.tools_allowlist.join(", ")}
              </em>
              <div className="inline-actions">
                <button
                  className="ghost-button"
                  disabled={
                    reviewingSuggestionId === suggestion.id
                    || acceptedSchemaDimensions.has(suggestion.normalized_dimension)
                  }
                  type="button"
                  onClick={() => onReviewSchemaSuggestion(suggestion, "accepted")}
                >
                  Accept
                </button>
                <button
                  className="ghost-button"
                  disabled={reviewingSuggestionId === suggestion.id}
                  type="button"
                  onClick={() => onReviewSchemaSuggestion(suggestion, "rejected")}
                >
                  Reject
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : null}
      {report.gaps.length > 0 ? (
        <div className="evidence-gap-list">
          {report.gaps.slice(0, 5).map((gap) => (
            <EvidenceGapCard gap={gap} key={gap.id} />
          ))}
        </div>
      ) : (
        <p className="muted-line">No structured evidence gaps for the active scenario.</p>
      )}
    </section>
  );
}

function gapFillEventSummary(payload: Record<string, unknown>) {
  const closure = typeof payload.gap_closure_rate === "number" ? formatPercent(payload.gap_closure_rate) : null;
  const retrievalCount = typeof payload.retrieval_record_count === "number" ? payload.retrieval_record_count : null;
  const failureCount = typeof payload.online_failure_count === "number" ? payload.online_failure_count : null;
  const versionId = typeof payload.updated_report_version_id === "string" ? payload.updated_report_version_id : null;
  if (closure || retrievalCount !== null) {
    return `closure ${closure ?? "n/a"} / retrieval records ${retrievalCount ?? 0}`;
  }
  if (failureCount !== null) {
    return `online failures ${failureCount}`;
  }
  if (versionId) {
    return `draft ${versionId}`;
  }
  return "decision event captured";
}

function EvidenceGapCard({ gap }: { gap: EvidenceGapItem }) {
  return (
    <article className={`evidence-gap-card ${gap.severity}`}>
      <div>
        <strong>{gap.gap_type.replace(/_/g, " ")}</strong>
        <span>
          {gap.severity}
          {gap.competitor_name ? ` / ${gap.competitor_name}` : ""}
          {gap.dimension ? ` / ${gap.dimension}` : ""}
        </span>
      </div>
      <p>{gap.message}</p>
      {gap.retrieval_query || gap.recommended_query ? (
        <em>{gap.retrieval_query || gap.recommended_query}</em>
      ) : null}
      {gap.retrieval_candidate_ids.length > 0 ? (
        <small>{gap.retrieval_candidate_ids.length} retrieval candidate(s)</small>
      ) : null}
      {gap.retrieval_candidate_chunk_count > 0 ? (
        <small>
          {gap.retrieval_candidate_chunk_count} chunks / {gap.retrieval_unique_evidence_count} unique evidence /{" "}
          {gap.retrieval_dedupe_drop_count} deduped
        </small>
      ) : null}
      {gap.retrieval_records.length > 0 ? (
        <div className="gap-retrieval-list">
          {gap.retrieval_records.slice(0, 2).map((record) => (
            <div key={`${record.evidence_id}-${record.chunk_id}`}>
              <strong>{record.title}</strong>
              <span>
                {record.retrieval_stage} / chunk {record.chunk_id || record.chunk_index} / hybrid{" "}
                {record.score.toFixed(2)} / bm25 {record.bm25_score.toFixed(2)} / vector {record.vector_score.toFixed(2)}
              </span>
              <p>{record.snippet}</p>
              {record.source_url ? (
                <a href={record.source_url} rel="noreferrer" target="_blank">
                  {record.source_url}
                </a>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
      {gap.retrieval_grounded_context ? (
        <blockquote className="gap-grounded-context">
          {gap.retrieval_grounded_context.slice(0, 520)}
        </blockquote>
      ) : null}
    </article>
  );
}

function RedTeamPanel({ report }: { report: RedTeamReport }) {
  const status = report.high_severity_count >= 2 ? "high" : report.finding_count > 0 ? "medium" : "clear";
  return (
    <section className={`panel red-team-panel ${status}`}>
      <div className="panel-heading-row">
        <h2>Red team</h2>
        {status === "clear" ? <CheckCircle2 size={17} aria-hidden /> : <AlertTriangle size={17} aria-hidden />}
      </div>
      <div className="red-team-summary">
        <span>
          <strong>{report.finding_count}</strong>
          <em>Findings</em>
        </span>
        <span>
          <strong>{report.high_severity_count}</strong>
          <em>High severity</em>
        </span>
        <span>
          <strong>{report.pydantic_ai_available ? "on" : "off"}</strong>
          <em>Pydantic-AI</em>
        </span>
      </div>
      <PydanticAiExecutionPanel
        available={report.pydantic_ai_available}
        executionMode={report.pydantic_ai_execution_mode}
        fallback={report.pydantic_ai_model_backed_fallback}
        modelName={report.pydantic_ai_model_name}
        modelBackedRequested={report.pydantic_ai_model_backed_requested}
        runtimeAgentCreated={report.pydantic_ai_runtime_agent_created}
        runtimePromptChars={report.pydantic_ai_runtime_prompt_chars}
        runtimePromptHash={report.pydantic_ai_runtime_prompt_hash}
        typedContractEnforced={report.typed_contract_enforced}
      />
      {report.findings.length > 0 ? (
        <div className="red-team-list">
          {report.findings.slice(0, 5).map((finding) => (
            <RedTeamFindingCard finding={finding} key={finding.id} />
          ))}
        </div>
      ) : (
        <p className="muted-line">No red-team findings for the active project.</p>
      )}
    </section>
  );
}

function PydanticAiExecutionPanel({
  available,
  executionMode,
  fallback,
  modelBackedRequested,
  modelName,
  runtimeAgentCreated,
  runtimePromptChars,
  runtimePromptHash,
  typedContractEnforced,
}: {
  available: boolean;
  executionMode: string;
  fallback: boolean;
  modelBackedRequested: boolean;
  modelName?: string | null;
  runtimeAgentCreated: boolean;
  runtimePromptChars: number;
  runtimePromptHash?: string | null;
  typedContractEnforced: boolean;
}) {
  return (
    <div className="agent-runtime-row">
      <span className={available ? "ok" : "warn"}>
        <strong>{available ? "on" : "off"}</strong>
        <em>Pydantic-AI</em>
      </span>
      <span className={modelBackedRequested ? "ok" : undefined}>
        <strong>{executionMode.replace(/^pydantic_ai_/, "").replace(/_/g, " ")}</strong>
        <em>Execution</em>
      </span>
      <span className={fallback ? "warn" : "ok"}>
        <strong>{fallback ? "yes" : "no"}</strong>
        <em>Fallback</em>
      </span>
      <span>
        <strong>{modelName || "default"}</strong>
        <em>Model</em>
      </span>
      <span className={typedContractEnforced ? "ok" : "warn"}>
        <strong>{typedContractEnforced ? "typed" : "loose"}</strong>
        <em>Schema</em>
      </span>
      <span className={runtimeAgentCreated ? "ok" : "warn"}>
        <strong>{runtimeAgentCreated ? "ready" : "none"}</strong>
        <em>Runtime</em>
      </span>
      <span>
        <strong>{runtimePromptHash ? runtimePromptHash.slice(0, 8) : "none"}</strong>
        <em>Prompt hash</em>
      </span>
      <span>
        <strong>{runtimePromptChars}</strong>
        <em>Prompt chars</em>
      </span>
    </div>
  );
}

function RedTeamFindingCard({ finding }: { finding: RedTeamFinding }) {
  return (
    <article className={`red-team-card ${finding.severity}`}>
      <div>
        <strong>{finding.finding_type.replace(/_/g, " ")}</strong>
        <span>
          {finding.severity}
          {finding.competitor_name ? ` / ${finding.competitor_name}` : ""}
          {finding.dimension ? ` / ${finding.dimension}` : ""}
        </span>
      </div>
      <p>{finding.message}</p>
      <em>{finding.recommendation}</em>
    </article>
  );
}

function QAEvaluationPanel({ evaluation }: { evaluation: BusinessQAEvaluation }) {
  const status = evaluation.blocker_count > 0 ? "blocker" : evaluation.warn_count > 0 ? "warn" : "pass";
  return (
    <section className={`panel business-qa-panel ${status}`}>
      <div className="panel-heading-row">
        <h2>Business QA</h2>
        {status === "pass" ? <CheckCircle2 size={17} aria-hidden /> : <AlertTriangle size={17} aria-hidden />}
      </div>
      <div className="business-qa-metrics">
        <span>
          <strong>{evaluation.passed_rules}/{evaluation.total_rules}</strong>
          <em>Rules passed</em>
        </span>
        <span>
          <strong>{evaluation.blocker_count}</strong>
          <em>Blockers</em>
        </span>
        <span>
          <strong>{evaluation.warn_count}</strong>
          <em>Warnings</em>
        </span>
        <span>
          <strong>{evaluation.info_count}</strong>
          <em>Info</em>
        </span>
      </div>
      {evaluation.findings.length > 0 ? (
        <div className="business-qa-findings">
          {evaluation.findings.slice(0, 5).map((finding) => (
            <QAFindingItem finding={finding} key={finding.id} />
          ))}
        </div>
      ) : (
        <p className="muted-line">All active business QA rules passed.</p>
      )}
    </section>
  );
}

function QAFindingItem({ finding }: { finding: BusinessQAFinding }) {
  return (
    <article className={`business-qa-finding ${finding.severity}`}>
      <div>
        <strong>{finding.rule_name}</strong>
        <span>
          {finding.severity}
          {finding.competitor_name ? ` / ${finding.competitor_name}` : ""}
          {finding.dimension ? ` / ${finding.dimension}` : ""}
        </span>
      </div>
      <p>{finding.message}</p>
      {finding.recommendation ? <em>{finding.recommendation}</em> : null}
      <FindingTargetLinks finding={finding} />
    </article>
  );
}

function FindingTargetLinks({ finding }: { finding: BusinessQAFinding }) {
  return <TargetAnchorLinks claimIds={finding.claim_ids} evidenceIds={finding.evidence_ids} />;
}

function TargetAnchorLinks({
  claimIds = [],
  evidenceIds = [],
}: {
  claimIds?: string[];
  evidenceIds?: string[];
}) {
  const evidenceTargets = evidenceIds.slice(0, 4);
  const claimTargets = claimIds.slice(0, 4);
  if (evidenceTargets.length === 0 && claimTargets.length === 0) return null;
  return (
    <div className="source-id-links finding-target-links">
      {claimTargets.map((claimId) => (
        <a href={`#claim-${claimId}`} key={`claim-${claimId}`}>
          claim {claimId.slice(0, 10)}
        </a>
      ))}
      {evidenceTargets.map((evidenceId) => (
        <a href={`#evidence-${evidenceId}`} key={`evidence-${evidenceId}`}>
          evidence {evidenceId.slice(0, 10)}
        </a>
      ))}
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: number | string;
}) {
  return (
    <span>
      {icon}
      <strong>{value}</strong>
      <em>{label}</em>
    </span>
  );
}

function buildEvidenceSnapshotRequest(
  project: ProjectRecord,
  evidence: EvidenceRecord,
  competitorName: string,
): SourceSnapshotCreateRequest {
  const snapshotKind = inferSnapshotKind(evidence);
  return {
    workspace_id: project.workspace_id,
    project_id: project.id,
    evidence_id: evidence.id,
    run_id: evidence.run_id ?? null,
    snapshot_kind: snapshotKind,
    artifact_type: snapshotKind === "webpage" ? "web_snapshot" : "raw_text",
    filename: buildSnapshotFilename(evidence),
    media_type: "text/plain; charset=utf-8",
    content_text: [
      `Title: ${evidence.title}`,
      `Competitor: ${competitorName}`,
      `Dimension: ${evidence.dimension}`,
      evidence.url ? `URL: ${evidence.url}` : null,
      `Source type: ${evidence.source_type}`,
      `Reliability: ${formatPercent(evidence.reliability_score)}`,
      `Captured at: ${evidence.captured_at}`,
      "",
      evidence.snippet || "No snippet captured.",
    ]
      .filter((line): line is string => line !== null)
      .join("\n"),
    source_url: evidence.url ?? null,
    source_type: evidence.source_type || `${snapshotKind}_snapshot`,
    display_name: evidence.title,
    trust_level: inferSourceTrustLevel(evidence),
    robots_status: evidence.url ? "allowed" : "unknown",
    metadata: {
      captured_from: "enterprise_workbench_evidence_table",
      competitor_id: evidence.competitor_id,
      competitor_name: competitorName,
      raw_source_id: evidence.raw_source_id,
      dimension: evidence.dimension,
      content_hash: evidence.content_hash,
      quality_label: evidence.quality_label,
      reliability_score: evidence.reliability_score,
      freshness_score: evidence.freshness_score,
    },
  };
}

function inferSnapshotKind(
  evidence: EvidenceRecord,
): NonNullable<SourceSnapshotCreateRequest["snapshot_kind"]> {
  const sourceType = evidence.source_type.toLowerCase();
  if (sourceType.includes("pdf")) return "pdf";
  if (sourceType.includes("screenshot")) return "screenshot";
  if (sourceType.includes("interview")) return "interview";
  if (sourceType.includes("survey")) return "survey";
  if (evidence.url) return "webpage";
  return "manual";
}

function inferSourceTrustLevel(
  evidence: EvidenceRecord,
): NonNullable<SourceSnapshotCreateRequest["trust_level"]> {
  const sourceType = evidence.source_type.toLowerCase();
  if (sourceType.includes("official") || sourceType.includes("pricing")) return "official";
  if (sourceType.includes("synthetic") || sourceType.includes("simulated")) return "synthetic";
  if (!evidence.url) return "unknown";
  return "verified";
}

function buildSnapshotFilename(evidence: EvidenceRecord) {
  const safeTitle = evidence.title
    .trim()
    .replace(/[<>:"/\\|?*\u0000-\u001f]+/g, "-")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 72);
  return `${safeTitle || "evidence"}-${evidence.id.slice(0, 8)}.txt`;
}

function EvidenceTable({
  capturedEvidenceIds,
  competitorById,
  evidence,
  onQualityChange,
  onSnapshotEvidence,
  query,
  setQuery,
  snapshottingEvidenceId,
}: {
  capturedEvidenceIds: Set<string>;
  competitorById: Map<string, CompetitorRecord>;
  evidence: EvidenceRecord[];
  onQualityChange: (evidenceId: string, qualityLabel: EvidenceQualityLabel) => void;
  onSnapshotEvidence: (item: EvidenceRecord) => void;
  query: string;
  setQuery: (value: string) => void;
  snapshottingEvidenceId: string | null;
}) {
  return (
    <div className="evidence-section">
      <label className="search-box">
        <Search size={16} aria-hidden />
        <input
          aria-label="Search evidence"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search evidence"
        />
      </label>
      <div className="enterprise-table-wrap">
        <table className="enterprise-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Competitor</th>
              <th>Dimension</th>
              <th>Quality</th>
              <th>Reliability</th>
              <th aria-label="Snapshot">
                <FileText size={14} aria-hidden />
              </th>
            </tr>
          </thead>
          <tbody>
            {evidence.map((item) => {
              const competitor = competitorById.get(item.competitor_id)?.name ?? item.competitor_id;
              const isCaptured = capturedEvidenceIds.has(item.id);
              const isSnapshotting = snapshottingEvidenceId === item.id;
              const dedupeSummary = evidenceDedupeSummary(item);
              return (
                <tr id={`evidence-${item.id}`} key={item.id}>
                  <td>
                    <strong>{item.title}</strong>
                    <span>{item.snippet}</span>
                    {dedupeSummary ? <span>{dedupeSummary}</span> : null}
                    {item.url ? (
                      <a href={item.url} rel="noreferrer" target="_blank">
                        <ExternalLink size={13} aria-hidden />
                        {item.url}
                      </a>
                    ) : null}
                  </td>
                  <td>{competitor}</td>
                  <td>{item.dimension}</td>
                  <td>
                    <select
                      aria-label={`Quality for ${item.title}`}
                      className="quality-select"
                      value={item.quality_label}
                      onChange={(event) =>
                        onQualityChange(item.id, event.target.value as EvidenceQualityLabel)
                      }
                    >
                      <option value="unreviewed">unreviewed</option>
                      <option value="accepted">accepted</option>
                      <option value="rejected">rejected</option>
                      <option value="stale">stale</option>
                    </select>
                  </td>
                  <td>{formatPercent(item.reliability_score)}</td>
                  <td>
                    <button
                      aria-label={`Capture source snapshot for ${item.title}`}
                      className="icon-button table-action-button"
                      disabled={isCaptured || isSnapshotting}
                      onClick={() => onSnapshotEvidence(item)}
                      title={isCaptured ? "Snapshot captured" : "Capture source snapshot"}
                      type="button"
                    >
                      {isSnapshotting ? (
                        <RefreshCw size={14} aria-hidden />
                      ) : isCaptured ? (
                        <CheckCircle2 size={14} aria-hidden />
                      ) : (
                        <FileText size={14} aria-hidden />
                      )}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {evidence.length === 0 ? <p className="muted-line">No matching evidence.</p> : null}
    </div>
  );
}

function evidenceDedupeSummary(item: EvidenceRecord) {
  const duplicateOf = payloadString(item.metadata, "embedding_duplicate_of");
  if (duplicateOf) {
    return `Duplicate of ${duplicateOf}`;
  }
  const duplicateCount =
    payloadNumber(item.metadata, "embedding_duplicate_count") ??
    payloadListCount(item.metadata, "embedding_duplicate_ids");
  if (duplicateCount !== null && duplicateCount > 0) {
    return `Canonical evidence; ${duplicateCount} duplicate item(s) folded.`;
  }
  return null;
}

function ClaimList({
  claims,
  competitorById,
  evidenceById,
}: {
  claims: ClaimRecord[];
  competitorById: Map<string, CompetitorRecord>;
  evidenceById: Map<string, EvidenceRecord>;
}) {
  if (claims.length === 0) {
    return <p className="muted-line">No claims have been projected yet.</p>;
  }
  return (
    <div className="claim-list">
      {claims.map((claim) => {
        const competitor = competitorById.get(claim.competitor_id)?.name ?? claim.competitor_id;
        return (
          <article id={`claim-${claim.id}`} key={claim.id}>
            <div>
              <strong>{claim.claim_text}</strong>
              <span>
                {competitor} / {claim.claim_type} / {formatPercent(claim.confidence)}
              </span>
            </div>
            <div className="source-id-links">
              {claim.evidence_ids.map((evidenceId) => (
                <a href={`#evidence-${evidenceId}`} key={evidenceId} title={evidenceById.get(evidenceId)?.title}>
                  {evidenceById.get(evidenceId)?.dimension ?? evidenceId.slice(0, 10)}
                </a>
              ))}
            </div>
          </article>
        );
      })}
    </div>
  );
}

function buildReportSourceBundle(
  evidence: EvidenceRecord[],
  competitorById: Map<string, CompetitorRecord>,
  selectedVersion: ReportVersionRecord | null,
): { sources: RawSource[]; aliases: Record<string, string> } {
  const scopedEvidenceIds =
    selectedVersion && selectedVersion.evidence_ids.length > 0
      ? new Set(selectedVersion.evidence_ids)
      : null;
  const sourcesByRawId = new Map<string, RawSource>();
  const aliases: Record<string, string> = {};

  for (const item of evidence) {
    if (scopedEvidenceIds && !scopedEvidenceIds.has(item.id)) continue;
    const competitorName = competitorById.get(item.competitor_id)?.name ?? item.competitor_id;
    aliases[item.id] = item.raw_source_id;

    const existing = sourcesByRawId.get(item.raw_source_id);
    if (existing) {
      if (!existing.covered_competitors.includes(competitorName)) {
        existing.covered_competitors = [...existing.covered_competitors, competitorName];
      }
      existing.confidence = Math.max(existing.confidence, item.reliability_score);
      continue;
    }

    sourcesByRawId.set(item.raw_source_id, {
      id: item.raw_source_id,
      competitor: competitorName,
      covered_competitors: [competitorName],
      dimension: item.dimension,
      source_type: item.source_type,
      title: item.title,
      url: item.url ?? null,
      snippet: item.snippet,
      content_hash: item.content_hash,
      confidence: item.reliability_score,
      extracted_at: item.captured_at,
    });
  }

  return { sources: Array.from(sourcesByRawId.values()), aliases };
}

function ReportHistory({
  diff,
  isApprovalSubmitting,
  isExporting,
  isPublishing,
  lastExport,
  onApproveReport,
  onExportReport,
  onPublishReport,
  onRejectReport,
  onStartApproval,
  releaseGate,
  sourceAliases,
  sources,
  selectedVersion,
  selectedVersionId,
  setSelectedVersionId,
  versions,
}: {
  diff: ReportVersionDiff | null;
  isApprovalSubmitting: boolean;
  isExporting: boolean;
  isPublishing: boolean;
  lastExport: ArtifactRecord | null;
  onApproveReport: () => void;
  onExportReport: (format: "markdown" | "html" | "csv") => void;
  onPublishReport: () => void;
  onRejectReport: () => void;
  onStartApproval: () => void;
  releaseGate: ReportReleaseGate | null;
  sourceAliases: Record<string, string>;
  sources: RawSource[];
  selectedVersion: ReportVersionRecord | null;
  selectedVersionId: string | null;
  setSelectedVersionId: (value: string) => void;
  versions: ReportVersionRecord[];
}) {
  if (versions.length === 0) {
    return <p className="muted-line">No report versions have been created yet.</p>;
  }
  return (
    <div className="report-history-grid">
      <aside className="version-list" aria-label="Report versions">
        {versions.map((version) => (
          <button
            className={version.id === selectedVersionId ? "active" : ""}
            key={version.id}
            type="button"
            onClick={() => setSelectedVersionId(version.id)}
          >
            <strong>v{version.version_number}</strong>
            <span>{version.status}</span>
            <em>{formatDate(version.created_at)}</em>
          </button>
        ))}
      </aside>
      <div className="report-reader">
        <div className="panel-heading-row">
          <h2>{selectedVersion ? `Report v${selectedVersion.version_number}` : "Report"}</h2>
          <GitCompare size={17} aria-hidden />
        </div>
        {selectedVersion ? (
          <ReportApprovalPanel
            isSubmitting={isApprovalSubmitting}
            isPublishing={isPublishing}
            onApprove={onApproveReport}
            onPublish={onPublishReport}
            onReject={onRejectReport}
            onStart={onStartApproval}
            version={selectedVersion}
          />
        ) : null}
        {selectedVersion ? (
          <ReportExportPanel
            isExporting={isExporting}
            lastExport={lastExport}
            onExport={onExportReport}
          />
        ) : null}
        {releaseGate ? <ReleaseGatePanel gate={releaseGate} /> : null}
        {selectedVersion ? (
          <ReportView
            markdown={selectedVersion.report_md || "No report body."}
            sourceAliases={sourceAliases}
            sources={sources}
          />
        ) : null}
        {diff ? (
          <div className="report-diff">
            <div className="diff-summary">
              <span>Base {diff.base_version ? `v${diff.base_version.version_number}` : "none"}</span>
              <span>+{diff.added_lines}</span>
              <span>-{diff.removed_lines}</span>
            </div>
            <pre>
              {diff.lines.map((line, index) => {
                const prefix = line.kind === "added" ? "+" : line.kind === "removed" ? "-" : " ";
                return `${prefix} ${line.text}${index === diff.lines.length - 1 ? "" : "\n"}`;
              })}
            </pre>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ReportApprovalPanel({
  isSubmitting,
  isPublishing,
  onApprove,
  onPublish,
  onReject,
  onStart,
  version,
}: {
  isSubmitting: boolean;
  isPublishing: boolean;
  onApprove: () => void;
  onPublish: () => void;
  onReject: () => void;
  onStart: () => void;
  version: ReportVersionRecord;
}) {
  const canStart = !["in_review", "approved", "published", "archived"].includes(version.status);
  const canSignal = version.status === "in_review";
  const canPublish = version.status === "approved";
  return (
    <section className={`report-approval-panel ${version.status}`}>
      <div>
        <strong>Report approval</strong>
        <span>
          {version.status} / run {version.run_id}
        </span>
      </div>
      <div className="approval-action-row">
        <button
          className="icon-text-button"
          disabled={isSubmitting || !canStart}
          type="button"
          onClick={onStart}
        >
          <ShieldCheck size={15} aria-hidden />
          {isSubmitting && canStart ? "Starting" : "Start review"}
        </button>
        <button
          className="icon-text-button"
          disabled={isSubmitting || !canSignal}
          type="button"
          onClick={onApprove}
        >
          <CheckCircle2 size={15} aria-hidden />
          Approve
        </button>
        <button
          className="icon-text-button"
          disabled={isSubmitting || !canSignal}
          type="button"
          onClick={onReject}
        >
          <AlertTriangle size={15} aria-hidden />
          Reject
        </button>
        <button
          className="icon-text-button"
          disabled={isSubmitting || isPublishing || !canPublish}
          type="button"
          onClick={onPublish}
        >
          <FileText size={15} aria-hidden />
          {isPublishing ? "Publishing" : "Publish"}
        </button>
      </div>
    </section>
  );
}

function ReportExportPanel({
  isExporting,
  lastExport,
  onExport,
}: {
  isExporting: boolean;
  lastExport: ArtifactRecord | null;
  onExport: (format: "markdown" | "html" | "csv") => void;
}) {
  return (
    <section className="report-export-panel">
      <div className="approval-action-row">
        {(["markdown", "html", "csv"] as const).map((format) => (
          <button
            className="icon-text-button"
            disabled={isExporting}
            key={format}
            type="button"
            onClick={() => onExport(format)}
          >
            <Download size={15} aria-hidden />
            {isExporting ? "Exporting" : format.toUpperCase()}
          </button>
        ))}
      </div>
      {lastExport ? (
        <p className="muted-line">
          {lastExport.filename} / {lastExport.uri}
        </p>
      ) : null}
    </section>
  );
}

function ReleaseGatePanel({ gate }: { gate: ReportReleaseGate }) {
  return (
    <section className={`release-gate-panel ${gate.status}`}>
      <div>
        <strong>{gate.allowed ? "Release gate passed" : "Release gate blocked"}</strong>
        <span>
          {gate.readiness.score} readiness / {gate.qa_evaluation.finding_count} QA finding(s)
        </span>
      </div>
      {gate.issues.length ? (
        <ul>
          {gate.issues.slice(0, 3).map((issue) => (
            <li key={issue.id}>
              <span>{issue.message}</span>
              <FindingTargetLinks finding={issue} />
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatSignedPercent(value: number) {
  const formatted = formatPercent(Math.abs(value));
  if (value > 0) return `+${formatted}`;
  if (value < 0) return `-${formatted}`;
  return formatted;
}

function formatScoreDelta(value?: number | null) {
  if (value === null || value === undefined) {
    return "n/a";
  }
  return value > 0 ? `+${value}` : `${value}`;
}

function evalOpsMetricValue(report: EvalOpsReport, name: string) {
  const metric = report.metrics.find((item) => item.name === name);
  return metric ? metric.value : null;
}

function evalOpsStatusRank(status: EvalOpsReport["regression_gate_status"]) {
  if (status === "fail") return 3;
  if (status === "warn") return 2;
  return 1;
}

function evalOpsCasePriority(status: EvalOpsReport["regression_gate_status"]) {
  if (status === "fail") return "high";
  if (status === "warn") return "medium";
  return "low";
}

function memoryCandidatePriority(status: MemoryCandidateStatus) {
  if (status === "candidate") return "medium";
  if (status === "confirmed") return "low";
  return "high";
}

function acceptedSchemaDimensionSet(metadata?: Record<string, unknown>) {
  const raw = metadata?.accepted_schema_dimensions;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return new Set<string>();
  }
  return new Set(Object.keys(raw));
}

function formatRouteCandidate(candidate?: ModelRouteDecision["selected"]) {
  if (!candidate) {
    return "none";
  }
  return candidate.model_name ? `${candidate.provider_name} / ${candidate.model_name}` : candidate.provider_name;
}

function summarizeKnowledgeGraphRelations(knowledgeGraph: KnowledgeGraphReadModel | null) {
  if (!knowledgeGraph) {
    return [];
  }
  const relations = new Map<string, { relation: string; count: number; evidenceLinkCount: number }>();
  for (const edge of knowledgeGraph.edges) {
    const current = relations.get(edge.relation) ?? {
      relation: edge.relation,
      count: 0,
      evidenceLinkCount: 0,
    };
    current.count += 1;
    current.evidenceLinkCount += edge.evidence_ids.length;
    relations.set(edge.relation, current);
  }
  return [...relations.values()].sort((left, right) => {
    if (right.count !== left.count) {
      return right.count - left.count;
    }
    return left.relation.localeCompare(right.relation);
  });
}

function formatBytes(value: number) {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)} MB`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(1)} KB`;
  }
  return `${value} B`;
}

function artifactMetadataNumber(artifact: ArtifactRecord, key: string) {
  const value = artifact.metadata[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function artifactMetadataString(artifact: ArtifactRecord, key: string) {
  const value = artifact.metadata[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function artifactMetadataListCount(artifact: ArtifactRecord, key: string) {
  const value = artifact.metadata[key];
  return Array.isArray(value) ? value.length : 0;
}

function decisionReplayPriority(eventType: string) {
  if (eventType.includes("blocker") || eventType.includes("failed")) {
    return "high";
  }
  if (eventType.includes("warn") || eventType.includes("redo") || eventType.includes("hitl")) {
    return "medium";
  }
  return "low";
}

function formatDecisionEventType(eventType: string) {
  return eventType.replace(/[._]/g, " ");
}

function decisionPayloadSummary(event: DecisionReplayEvent) {
  const payload = event.payload;
  const parts: string[] = [];

  if (event.event_type === "rag.retrieved") {
    const retrievalCount = payloadNumber(payload, "retrieval_record_count");
    const closureRate = payloadNumber(payload, "gap_closure_rate");
    const gapCount = payloadListCount(payload, "gap_ids") ?? payloadNumber(payload, "gap_count");
    parts.push(`retrieval ${retrievalCount ?? event.evidence_ids.length}`);
    if (gapCount !== null) parts.push(`gaps ${gapCount}`);
    if (closureRate !== null) parts.push(`closure ${formatPercent(closureRate)}`);
  } else if (event.event_type === "memory.recalled") {
    const candidateCount = payloadListCount(payload, "candidate_ids", "memory_candidate_ids");
    const explicitCandidateCount = payloadNumber(payload, "candidate_count");
    const recallScore = payloadNumber(payload, "score", "recall_score");
    parts.push(`candidates ${candidateCount ?? explicitCandidateCount ?? 0}`);
    if (recallScore !== null) {
      parts.push(`recall ${recallScore > 1 ? recallScore : formatPercent(recallScore)}`);
    }
  } else if (event.event_type === "memory.feedback_captured") {
    const feedbackId = payloadString(payload, "feedback_id");
    const candidateCount = payloadNumber(payload, "candidate_count") ?? payloadListCount(payload, "candidate_ids");
    const targetType = payloadString(payload, "target_type");
    if (feedbackId) parts.push(feedbackId);
    if (candidateCount !== null) parts.push(`candidates ${candidateCount}`);
    if (targetType) parts.push(`target ${targetType}`);
  } else if (event.event_type === "claim.validated") {
    const claimCount = payloadNumber(payload, "claim_count") ?? event.claim_ids.length;
    const supportedCount = payloadNumber(payload, "supported_count");
    const releaseGate = payloadRecord(payload, "release_gate");
    parts.push(`claims ${claimCount}`);
    if (supportedCount !== null) parts.push(`supported ${supportedCount}`);
    if (releaseGate) parts.push(`gate ${String(releaseGate.status ?? "unknown")}`);
  } else if (event.event_type === "self_consistency.sampled") {
    const sampleCount = payloadNumber(payload, "sample_count");
    const score = payloadNumber(payload, "self_consistency_score", "consistency_score");
    if (sampleCount !== null) parts.push(`samples ${sampleCount}`);
    if (score !== null) parts.push(`consistency ${formatPercent(score)}`);
  } else if (event.event_type === "qa.blocked" || event.event_type === "redo.routed") {
    const severity = payloadString(payload, "severity");
    const redoScope = payloadString(payload, "redo_scope", "scope");
    const target = payloadString(payload, "target_agent", "agent");
    if (severity) parts.push(`severity ${severity}`);
    if (redoScope) parts.push(`scope ${redoScope}`);
    if (target) parts.push(`target ${target}`);
  } else if (event.event_type === "benchmark.scored") {
    const quality = payloadNumber(payload, "report_quality_score", "target_score");
    const schema = payloadNumber(payload, "schema_pass_rate");
    if (quality !== null) parts.push(`quality ${quality}`);
    if (schema !== null) parts.push(`schema ${formatPercent(schema)}`);
  } else if (event.event_type === "tool.called") {
    const tool = payloadString(payload, "tool", "name");
    const failures = payloadNumber(payload, "online_failure_count");
    if (tool) parts.push(`tool ${tool}`);
    if (failures !== null) parts.push(`failures ${failures}`);
  } else if (event.event_type === "report.ready") {
    const versionId = payloadString(payload, "updated_report_version_id", "report_version_id");
    const releaseGate = payloadRecord(payload, "release_gate");
    if (versionId) parts.push(`version ${versionId}`);
    if (releaseGate) parts.push(`gate ${String(releaseGate.status ?? "unknown")}`);
  }

  if (parts.length === 0) {
    const payloadKeys = Object.keys(payload).slice(0, 4);
    return payloadKeys.length ? `payload ${payloadKeys.join(", ")}` : "No structured payload summary.";
  }
  return parts.join(" / ");
}

function payloadNumber(payload: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

function payloadString(payload: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return null;
}

function payloadListCount(payload: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = payload[key];
    if (Array.isArray(value)) return value.length;
  }
  return null;
}

function payloadRecord(payload: Record<string, unknown>, key: string) {
  const value = payload[key];
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function auditLogSummary(log: AuditLogRecord) {
  const beforeStatus = auditMetadataString(log.before, "status");
  const afterStatus = auditMetadataString(log.after, "status");
  if (beforeStatus || afterStatus) {
    return `${beforeStatus ?? "none"} -> ${afterStatus ?? "none"} / ${log.resource_id}`;
  }

  const afterKeys = Object.keys(log.after ?? {}).slice(0, 3);
  if (afterKeys.length > 0) {
    return `Changed ${afterKeys.join(", ")} on ${log.resource_id}.`;
  }

  return `${log.actor_type}${log.actor_id ? `:${log.actor_id}` : ""} touched ${log.resource_id}.`;
}

function auditMetadataString(
  metadata: Record<string, unknown> | null | undefined,
  key: string,
) {
  const value = metadata?.[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function metadataStringList(
  metadata: Record<string, unknown> | null | undefined,
  key: string,
) {
  const value = metadata?.[key];
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is string => typeof item === "string" && item.trim().length > 0,
  );
}

function qualityEntryPriority(entry: QualityAgentMatrixEntry) {
  if (entry.status === "blocker") {
    return "high";
  }
  if (entry.status === "warn") {
    return "medium";
  }
  return "low";
}

function qualityStatusRank(status: QualityAgentMatrixEntry["status"]) {
  return status === "blocker" ? 3 : status === "warn" ? 2 : 1;
}

function metricProgressPercent(metric: EvalOpsMetric) {
  if (metric.target === 0) {
    return metric.value >= metric.target ? 100 : 0;
  }
  return Math.max(0, Math.min(100, Math.round((metric.value / metric.target) * 100)));
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
