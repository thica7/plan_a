import type { RunDetail, QCIssue } from "./types";

export type RunEventType =
  | "run_created"
  | "node_started"
  | "node_completed"
  | "interrupt"
  | "qa_issue"
  | "report_updated"
  | "revision_recorded"
  | "run_completed"
  | "run_failed"
  | "agent.started"
  | "agent.finished"
  | "tool.called"
  | "rag.retrieved"
  | "self_consistency.sampled"
  | "memory.recalled"
  | "memory.feedback_captured"
  | "hitl.reviewed"
  | "claim.validated"
  | "qa.blocked"
  | "redo.routed"
  | "benchmark.scored"
  | "report.ready";

export interface RunEvent {
  id: number;
  run_id: string;
  type: RunEventType;
  agent?: string | null;
  subagent?: string | null;
  swimlane?: string | null;
  message: string;
  payload: {
    run?: RunDetail;
    issue?: QCIssue;
    report_md?: string;
    [key: string]: unknown;
  };
  created_at: string;
}
