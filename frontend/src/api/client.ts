import type {
  AgentMessage,
  ArtifactCreateRequest,
  ArtifactCreateResult,
  ArtifactRecord,
  BusinessIntelPlan,
  BusinessQAEvaluation,
  CompetitorScoreReport,
  CompetitorKnowledge,
  ClaimRecord,
  CompetitorRecord,
  DecisionReplayReport,
  EvalOpsReport,
  EvidenceQualityLabel,
  EvidenceGapFillResult,
  EvidenceGapReport,
  EvidenceRecord,
  KnowledgeGraphReadModel,
  MemoryCandidate,
  MemoryCandidateStatus,
  MemoryFeedbackIngestResult,
  MemoryRecallContext,
  MemoryStats,
  ModelRouteDecision,
  ModelPolicyReport,
  MonitorStartRequest,
  MonitorStartResponse,
  NotificationRecord,
  OtelTraceExport,
  PolicyDecision,
  PolicyEvaluationRequest,
  ProjectReadinessScore,
  ProjectRecord,
  ReportApprovalSignalRequest,
  ReportApprovalSignalResponse,
  ReportApprovalStartRequest,
  ReportApprovalStartResponse,
  ReportReleaseGate,
  RevisionRecord,
  RedTeamReport,
  ReportVersionDiff,
  ReportVersionRecord,
  RunCreateRequest,
  RunDetail,
  RunQualityComparison,
  RunSummary,
  RuntimeConfig,
  ScheduledScanStartRequest,
  ScheduledScanStartResponse,
  ScenarioPack,
  SkillSpec,
  SourceSnapshotCreateRequest,
  SourceSnapshotResult,
  SourceRegistryRecord,
  ToolRegistryReport,
  ToolCallMessage,
  TraceObservabilityReport,
  TraceSpan,
  UserFeedbackCreateRequest,
  UserFeedbackRecord,
  WorkflowStartResponse,
  WorkflowStateResponse,
  RunComplianceReport,
  WorkspaceQuotaDecision,
  WorkspaceQuotaUpdateRequest,
  WorkspaceRecord,
  WorkspaceUsageSummary,
} from "./types";
import type { RunEvent } from "./sse_types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
    ...init,
  });

  if (!response.ok) {
    const text = await response.text();
    let detail: unknown;
    try {
      const payload = JSON.parse(text) as { detail?: unknown };
      detail = payload.detail;
    } catch {
      detail = undefined;
    }
    if (typeof detail === "string") {
      throw new Error(detail);
    }
    throw new Error(text || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function listSkills() {
  return request<SkillSpec[]>("/skills");
}

export function getRuntime() {
  return request<RuntimeConfig>("/runtime");
}

export function createRun(payload: RunCreateRequest) {
  return request<RunDetail | WorkflowStartResponse>("/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function startCompetitiveIntelWorkflow(payload: RunCreateRequest) {
  return request<WorkflowStartResponse>("/workflows/competitive-intel", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getWorkflowState(workflowId: string) {
  return request<WorkflowStateResponse>(`/workflows/${workflowId}`);
}

export function startScheduledScanWorkflow(payload: ScheduledScanStartRequest) {
  return request<ScheduledScanStartResponse>("/workflows/scheduled-scan", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function startMonitorWorkflow(payload: MonitorStartRequest) {
  return request<MonitorStartResponse>("/workflows/monitor", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function startReportApprovalWorkflow(payload: ReportApprovalStartRequest) {
  return request<ReportApprovalStartResponse>("/workflows/report-approval", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function approveReportWorkflow(
  reportVersionId: string,
  payload: ReportApprovalSignalRequest,
) {
  return request<ReportApprovalSignalResponse>(
    `/workflows/report-approval/${reportVersionId}/approve`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function rejectReportWorkflow(
  reportVersionId: string,
  payload: ReportApprovalSignalRequest,
) {
  return request<ReportApprovalSignalResponse>(
    `/workflows/report-approval/${reportVersionId}/reject`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function getRun(runId: string) {
  return request<RunDetail>(`/runs/${runId}`);
}

export function getRunQualityComparison(runId: string, baselineRunId?: string) {
  const params = baselineRunId ? `?baseline_run_id=${encodeURIComponent(baselineRunId)}` : "";
  return request<RunQualityComparison>(`/runs/${runId}/quality-comparison${params}`);
}

export function getEnterpriseEvalOps(options: { projectId?: string; baselineRunId?: string } = {}) {
  const params = new URLSearchParams();
  if (options.projectId) params.set("project_id", options.projectId);
  if (options.baselineRunId) params.set("baseline_run_id", options.baselineRunId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return request<EvalOpsReport>(`/evals/enterprise${suffix}`);
}

export function getRunKb(runId: string) {
  return request<Record<string, CompetitorKnowledge>>(`/runs/${runId}/kb`);
}

export function getRunRevisions(runId: string) {
  return request<RevisionRecord[]>(`/runs/${runId}/revisions`);
}

export function getTraceSpans(runId: string) {
  return request<TraceSpan[]>(`/runs/${runId}/trace/spans`);
}

export function getOtelTraceExport(runId: string) {
  return request<OtelTraceExport>(`/runs/${runId}/trace/otel`);
}

export function getTraceObservabilityReport(runId: string) {
  return request<TraceObservabilityReport>(`/runs/${runId}/trace/observability`);
}

export function getDecisionReplay(runId: string) {
  return request<DecisionReplayReport>(`/runs/${runId}/decision-replay`);
}

export function getRunComplianceReport(runId: string) {
  return request<RunComplianceReport>(`/runs/${runId}/compliance`);
}

export function getAgentMessages(runId: string) {
  return request<AgentMessage[]>(`/runs/${runId}/trace/agent-messages`);
}

export function getToolCallMessages(runId: string) {
  return request<ToolCallMessage[]>(`/runs/${runId}/trace/tool-calls`);
}

export function resumeRun(
  runId: string,
  payload: {
    decision: "accept" | "modify_plan" | "force_pass" | "redo";
    note?: string;
    dimensions?: string[];
  },
) {
  return request<RunDetail>(`/runs/${runId}/resume`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function redoRun(runId: string) {
  return request<RunDetail>(`/runs/${runId}/redo`, {
    method: "POST",
  });
}

export function listRuns() {
  return request<RunSummary[]>("/runs");
}

export function listEnterpriseProjects(workspaceId?: string) {
  const params = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  return request<ProjectRecord[]>(`/enterprise/projects${params}`);
}

export function listScenarioPacks() {
  return request<ScenarioPack[]>("/enterprise/scenario-packs");
}

export function getPolicyActions() {
  return request<Record<string, string>>("/enterprise/policy/actions");
}

export function evaluatePolicy(payload: PolicyEvaluationRequest) {
  return request<PolicyDecision>("/enterprise/policy/evaluate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getModelPolicy() {
  return request<ModelPolicyReport>("/enterprise/model-policy");
}

export function getModelRouteDecision() {
  return request<ModelRouteDecision>("/enterprise/model-route");
}

export function getToolRegistry() {
  return request<ToolRegistryReport>("/enterprise/tool-registry");
}

export function getWorkspaceUsage(workspaceId: string) {
  return request<WorkspaceUsageSummary>(
    `/enterprise/workspaces/${encodeURIComponent(workspaceId)}/usage`,
  );
}

export function getWorkspaceQuotaDecision(workspaceId: string) {
  return request<WorkspaceQuotaDecision>(
    `/enterprise/workspaces/${encodeURIComponent(workspaceId)}/quota-decision`,
  );
}

export function updateWorkspaceQuota(
  workspaceId: string,
  payload: WorkspaceQuotaUpdateRequest,
) {
  return request<WorkspaceRecord>(
    `/enterprise/workspaces/${encodeURIComponent(workspaceId)}/quota`,
    {
      method: "PATCH",
      body: JSON.stringify(payload),
    },
  );
}

export function listEnterpriseNotifications(params: {
  workspaceId?: string;
  status?: string;
  limit?: number;
} = {}) {
  const search = new URLSearchParams();
  if (params.workspaceId) search.set("workspace_id", params.workspaceId);
  if (params.status) search.set("status", params.status);
  if (params.limit) search.set("limit", String(params.limit));
  const query = search.toString();
  return request<NotificationRecord[]>(`/enterprise/notifications${query ? `?${query}` : ""}`);
}

export function listEnterpriseCompetitors(params: {
  workspaceId?: string;
  projectId?: string;
} = {}) {
  const search = new URLSearchParams();
  if (params.workspaceId) search.set("workspace_id", params.workspaceId);
  if (params.projectId) search.set("project_id", params.projectId);
  const query = search.toString();
  return request<CompetitorRecord[]>(`/enterprise/competitors${query ? `?${query}` : ""}`);
}

export function listProjectEvidence(projectId: string) {
  return request<EvidenceRecord[]>(`/enterprise/projects/${projectId}/evidence`);
}

export function listArtifacts(params: {
  workspaceId?: string;
  projectId?: string;
  evidenceId?: string;
} = {}) {
  const search = new URLSearchParams();
  if (params.workspaceId) search.set("workspace_id", params.workspaceId);
  if (params.projectId) search.set("project_id", params.projectId);
  if (params.evidenceId) search.set("evidence_id", params.evidenceId);
  const query = search.toString();
  return request<ArtifactRecord[]>(`/enterprise/artifacts${query ? `?${query}` : ""}`);
}

export function createArtifact(payload: ArtifactCreateRequest) {
  return request<ArtifactCreateResult>("/enterprise/artifacts", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function createSourceSnapshot(payload: SourceSnapshotCreateRequest) {
  return request<SourceSnapshotResult>("/enterprise/source-snapshots", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listSourceRegistry(workspaceId?: string) {
  const params = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
  return request<SourceRegistryRecord[]>(`/enterprise/source-registry${params}`);
}

export function getArtifact(artifactId: string) {
  return request<ArtifactRecord>(`/enterprise/artifacts/${encodeURIComponent(artifactId)}`);
}

export function getProjectKnowledgeGraph(projectId: string) {
  return request<KnowledgeGraphReadModel>(
    `/enterprise/projects/${encodeURIComponent(projectId)}/kg-read-model`,
  );
}

export function ingestProjectMemoryFeedback(projectId: string, payload: UserFeedbackCreateRequest) {
  return request<MemoryFeedbackIngestResult>(
    `/enterprise/projects/${encodeURIComponent(projectId)}/memory/feedback`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function listProjectMemoryFeedback(projectId: string, limit = 20) {
  return request<UserFeedbackRecord[]>(
    `/enterprise/projects/${encodeURIComponent(projectId)}/memory/feedback?limit=${limit}`,
  );
}

export function recallProjectMemory(
  projectId: string,
  options: { query?: string; limit?: number; includeUnconfirmed?: boolean } = {},
) {
  const search = new URLSearchParams();
  if (options.query) search.set("query", options.query);
  if (options.limit !== undefined) search.set("limit", String(options.limit));
  if (options.includeUnconfirmed !== undefined) {
    search.set("include_unconfirmed", String(options.includeUnconfirmed));
  }
  const query = search.toString();
  return request<MemoryRecallContext>(
    `/enterprise/projects/${encodeURIComponent(projectId)}/memory/recall${query ? `?${query}` : ""}`,
  );
}

export function updateProjectMemoryCandidate(
  projectId: string,
  candidateId: string,
  status: MemoryCandidateStatus,
) {
  return request<MemoryCandidate>(
    `/enterprise/projects/${encodeURIComponent(projectId)}/memory/candidates/${encodeURIComponent(candidateId)}?status=${status}`,
    { method: "PATCH" },
  );
}

export function getProjectMemoryStats(projectId: string) {
  return request<MemoryStats>(
    `/enterprise/projects/${encodeURIComponent(projectId)}/memory/stats`,
  );
}

export function getProjectBusinessPlan(projectId: string) {
  return request<BusinessIntelPlan>(`/enterprise/projects/${projectId}/business-plan`);
}

export function getProjectQAEvaluation(projectId: string) {
  return request<BusinessQAEvaluation>(`/enterprise/projects/${projectId}/qa-evaluation`);
}

export function getProjectReadinessScore(projectId: string) {
  return request<ProjectReadinessScore>(`/enterprise/projects/${projectId}/readiness-score`);
}

export function getProjectCompetitorScores(projectId: string) {
  return request<CompetitorScoreReport>(`/enterprise/projects/${projectId}/competitor-scores`);
}

export function getProjectEvidenceGaps(projectId: string) {
  return request<EvidenceGapReport>(`/enterprise/projects/${projectId}/evidence-gaps`);
}

export function fillProjectEvidenceGaps(projectId: string) {
  return request<EvidenceGapFillResult>(`/enterprise/projects/${projectId}/evidence-gaps/fill`, {
    method: "POST",
  });
}

export function getProjectRedTeam(projectId: string) {
  return request<RedTeamReport>(`/enterprise/projects/${projectId}/red-team`);
}

export function updateEvidenceQuality(
  evidenceId: string,
  payload: { quality_label: EvidenceQualityLabel; note?: string },
) {
  return request<{ evidence: EvidenceRecord }>(`/enterprise/evidence/${evidenceId}/quality`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function listProjectClaims(projectId: string) {
  return request<ClaimRecord[]>(`/enterprise/projects/${projectId}/claims`);
}

export function listProjectReportVersions(projectId: string) {
  return request<ReportVersionRecord[]>(`/enterprise/projects/${projectId}/report-versions`);
}

export function getReportVersionDiff(versionId: string, baseVersionId?: string) {
  const params = baseVersionId ? `?base_version_id=${encodeURIComponent(baseVersionId)}` : "";
  return request<ReportVersionDiff>(`/enterprise/report-versions/${versionId}/diff${params}`);
}

export function getReportReleaseGate(versionId: string) {
  return request<ReportReleaseGate>(`/enterprise/report-versions/${versionId}/release-gate`);
}

export function publishReportVersion(versionId: string) {
  return request<ReportVersionRecord>(`/enterprise/report-versions/${versionId}/publish`, {
    method: "POST",
  });
}

export function subscribeRun(runId: string, onEvent: (event: RunEvent) => void) {
  const source = new EventSource(`/api/runs/${runId}/stream`);
  source.onmessage = (message) => {
    onEvent(JSON.parse(message.data) as RunEvent);
  };
  const eventTypes = [
    "run_created",
    "node_started",
    "node_completed",
    "interrupt",
    "qa_issue",
    "report_updated",
    "revision_recorded",
    "run_completed",
    "run_failed",
    "agent.started",
    "agent.finished",
    "tool.called",
    "rag.retrieved",
    "self_consistency.sampled",
    "memory.recalled",
    "claim.validated",
    "qa.blocked",
    "redo.routed",
    "benchmark.scored",
    "report.ready",
  ];
  for (const type of eventTypes) {
    source.addEventListener(type, (message) => {
      onEvent(JSON.parse((message as MessageEvent).data) as RunEvent);
    });
  }
  return () => source.close();
}
