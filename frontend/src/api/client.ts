import type {
  AgentMessage,
  CompetitorKnowledge,
  RevisionRecord,
  RunCreateRequest,
  RunDetail,
  RunSummary,
  RuntimeConfig,
  SkillSpec,
  ToolCallMessage,
  TraceSpan,
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
  return request<RunDetail>("/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
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
