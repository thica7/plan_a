import type { FlowNodeId, SingleFlowNode } from "./types";

export const singleNodes: SingleFlowNode[] = [
  { id: "planner", label: "Planner", caption: "LLM + web search" },
  { id: "comparator", label: "Comparator", caption: "ComparisonMatrix" },
  { id: "reflector", label: "Reflector", caption: "coverage gaps" },
  { id: "writer", label: "Writer", caption: "markdown report" },
  { id: "qa", label: "QA", caption: "4-lane checks" },
];

export const plannerHitlNode: SingleFlowNode = {
  id: "planner_hitl",
  label: "Planner HITL",
  caption: "plan review interrupt",
};

export const qaHitlNode: SingleFlowNode = {
  id: "qa_hitl",
  label: "QA HITL",
  caption: "force pass / redo",
};

export const nodeIds = new Set<FlowNodeId>([
  "planner",
  "planner_hitl",
  "collector_dispatch",
  "collector",
  "collect_join",
  "collect_qa",
  "analyst_dispatch",
  "analyst",
  "analyst_join",
  "analyst_qa",
  "comparator",
  "reflector",
  "writer",
  "qa",
  "qa_hitl",
]);
