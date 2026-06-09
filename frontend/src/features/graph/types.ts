export type FlowNodeId =
  | "planner"
  | "planner_hitl"
  | "collector_dispatch"
  | "collector"
  | "collect_join"
  | "collect_qa"
  | "analyst_dispatch"
  | "analyst"
  | "analyst_join"
  | "analyst_qa"
  | "comparator"
  | "reflector"
  | "writer"
  | "qa"
  | "qa_hitl";

export type NodeState = "pending" | "active" | "complete" | "interrupted" | "failed";
export type ParallelAgent = "collector" | "analyst";

export type SingleFlowNodeId = Exclude<
  FlowNodeId,
  | "collector_dispatch"
  | "collector"
  | "collect_join"
  | "collect_qa"
  | "analyst_dispatch"
  | "analyst"
  | "analyst_join"
  | "analyst_qa"
>;

export interface SingleFlowNode {
  id: SingleFlowNodeId;
  label: string;
  caption: string;
}

export interface ReturnItem {
  id: number;
  from: string;
  to: string;
  severity: string;
  problem: string;
}

export interface ScopedRedoItem {
  id: number;
  from: string;
  to: string;
  severity: string;
  problem: string;
  scope: string;
}
