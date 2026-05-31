import type {
  AgentMessage,
  BusinessIntelPlan,
  BusinessQAEvaluation,
  CompetitorScoreReport,
  CompetitorKnowledge,
  ClaimRecord,
  CompetitorRecord,
  EvidenceQualityLabel,
  EvidenceGapReport,
  EvidenceRecord,
  MonitorStartRequest,
  MonitorStartResponse,
  NotificationRecord,
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
  RunSummary,
  RuntimeConfig,
  ScheduledScanStartRequest,
  ScheduledScanStartResponse,
  SkillSpec,
  ToolCallMessage,
  TraceSpan,
  WorkflowStartResponse,
  WorkflowStateResponse,
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

export function getRunKb(runId: string) {
  return request<Record<string, CompetitorKnowledge>>(`/runs/${runId}/kb`);
}

export function getRunRevisions(runId: string) {
  return request<RevisionRecord[]>(`/runs/${runId}/revisions`);
}

export function getTraceSpans(runId: string) {
  return request<TraceSpan[]>(`/runs/${runId}/trace/spans`);
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
  ];
  for (const type of eventTypes) {
    source.addEventListener(type, (message) => {
      onEvent(JSON.parse((message as MessageEvent).data) as RunEvent);
    });
  }
  return () => source.close();
}
