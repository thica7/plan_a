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
  | "report.ready"
  | "runtime.command"
  | "writer_preflight"
  | "writer_segment_preflight"
  | "writer_segment_validated"
  | "writer_assembly_completed"
  | "writer_assemble_repair_completed"
  | "writer_quality_preflight"
  | "writer_quality_preflight_repair"
  | "writer_structured_repair_selected"
  | "writer_structured_section_started"
  | "writer_structured_section_completed"
  | "writer_structured_section_failed"
  | "writer_structured_report_validated"
  | "writer_publication_contract_validated"
  | "writer_structured_repair_failed_preserved_previous"
  | "writer_schema_first_failed_closed"
  | "writer_markdown_fallback_used";

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
