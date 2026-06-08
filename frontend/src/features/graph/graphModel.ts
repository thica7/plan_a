import type { RunEvent } from "../../api/sse_types";
import type { RunStatus } from "../../api/types";
import { nodeIds, singleNodes } from "./graphDefinition";
import type {
  FlowNodeId,
  NodeState,
  ParallelAgent,
  ReturnItem,
  ScopedRedoItem,
  SingleFlowNodeId,
} from "./types";

export function resolveActiveNode(events: RunEvent[], activeNode: string | null | undefined, status: RunStatus) {
  if (isFinished(status)) return null;
  const latestInterrupt = [...events].reverse().find((event) => event.type === "interrupt");
  if (latestInterrupt && status === "interrupted") {
    const interruptNode = latestInterrupt.payload.interrupt_node;
    if (typeof interruptNode === "string" && nodeIds.has(interruptNode as FlowNodeId)) return interruptNode;
    const stage = latestInterrupt.payload.stage;
    if (stage === "planner") return "planner_hitl";
    if (stage === "qa") return "qa_hitl";
    return typeof stage === "string" && nodeIds.has(stage as FlowNodeId) ? stage : activeNode;
  }
  const latestStarted = [...events]
    .reverse()
    .find(
      (event) =>
        event.type === "node_started" &&
        ((event.agent && nodeIds.has(event.agent as FlowNodeId)) || event.agent === "hitl"),
    );
  if (latestStarted?.agent === "hitl" && latestStarted.subagent === "planner") return "planner_hitl";
  if (latestStarted?.agent === "hitl" && latestStarted.subagent === "qa") return "qa_hitl";
  if (latestStarted?.agent === "qa" && latestStarted.subagent === "collect") return "collect_qa";
  if (latestStarted?.agent === "qa" && latestStarted.subagent === "analyst") return "analyst_qa";
  return latestStarted?.agent || activeNode || null;
}

export function resolveVisibleStages(events: RunEvent[], active: string | null | undefined, status: RunStatus) {
  const completed = isFinished(status);
  const plannerHitl =
    completed || active === "planner_hitl" || hasAgentEvent(events, "hitl", "planner") || nodeCompleted(events, "planner");
  const collector =
    completed ||
    active === "collector_dispatch" ||
    active === "collector" ||
    hasAgentEvent(events, "collector_dispatch") ||
    hasAgentEvent(events, "collector") ||
    nodeCompleted(events, "hitl", "planner") ||
    nodeCompleted(events, "planner");
  const collectJoin =
    completed || active === "collect_join" || hasAgentEvent(events, "collect_join") || branchCompleted(events, "collector");
  const collectQa = completed || active === "collect_qa" || hasPhaseQaEvent(events, "collect") || collectJoinCompleted(events);
  const analyst =
    completed ||
    active === "analyst_dispatch" ||
    active === "analyst" ||
    hasAgentEvent(events, "analyst_dispatch") ||
    hasAgentEvent(events, "analyst");
  const analystJoin =
    completed || active === "analyst_join" || hasAgentEvent(events, "analyst_join") || branchCompleted(events, "analyst");
  const analystQa = completed || active === "analyst_qa" || hasPhaseQaEvent(events, "analyst") || branchCompleted(events, "analyst");
  const tail = singleNodes
    .slice(1)
    .filter((node) => completed || active === node.id || hasAgentEvent(events, node.id) || previousTailCompleted(events, node.id))
    .map((node) => node.id);
  const qaHitl = completed || active === "qa_hitl" || hasAgentEvent(events, "hitl", "qa") || nodeCompleted(events, "qa");
  return { plannerHitl, collector, collectJoin, collectQa, analyst, analystJoin, analystQa, tail, qaHitl };
}

export function buildCollectorBranches(dimensions: string[], competitors: string[], events: RunEvent[]) {
  if (competitors.length === 0) {
    const eventBranches = unique(
      events
        .filter((event) => event.agent === "collector" && event.subagent && event.subagent.includes("::"))
        .map((event) => event.subagent as string),
    );
    return eventBranches.length > 0 ? eventBranches : dimensions;
  }
  return competitors.flatMap((competitor) =>
    dimensions.map((dimension) => branchId(dimension, competitor)),
  );
}

export function buildAnalystBranches(dimensions: string[], competitors: string[], events: RunEvent[]) {
  if (competitors.length === 0) {
    const eventBranches = unique(
      events
        .filter((event) => event.agent === "analyst" && event.subagent && event.subagent.includes("::"))
        .map((event) => event.subagent as string),
    );
    return eventBranches.length > 0 ? eventBranches : dimensions;
  }
  return competitors.flatMap((competitor) =>
    dimensions.map((dimension) => branchId(dimension, competitor)),
  );
}

export function buildPhaseReturns(events: RunEvent[]) {
  return {
    collect: buildPhaseReturnItems(events, "collect", "Collect QA", "Collector"),
    analyst: buildPhaseReturnItems(events, "analyst", "Analyst QA", "Analyst"),
  };
}

export function buildScopedRedoLoops(events: RunEvent[]): ScopedRedoItem[] {
  return events
    .filter((event) => event.type === "node_started" && event.agent === "orchestrator" && event.message.startsWith("Scoped redo started"))
    .map((event) => {
      const issue = readIssue(event);
      const scope = readRedoScope(event);
      const target = formatRedoTarget(scope.kind, scope.targetSubagent, scope.targetCompetitor);
      return {
        id: event.id,
        from: "Final QA",
        to: target,
        severity: issue.severity,
        problem: issue.problem,
        scope: [scope.kind, scope.targetCompetitor, scope.targetSubagent].filter(Boolean).join(" / "),
      };
    });
}

export function resolveNodeState(
  node: SingleFlowNodeId,
  active: string | null | undefined,
  events: RunEvent[],
  status: RunStatus,
): NodeState {
  if (status === "failed" && active === node) return "failed";
  if (status === "interrupted" && active === node) return "interrupted";
  if (active === node) return "active";
  if (node === "planner_hitl") {
    return nodeCompleted(events, "hitl", "planner") || isFinished(status) ? "complete" : "pending";
  }
  if (node === "qa_hitl") {
    return nodeCompleted(events, "hitl", "qa") || isFinished(status) ? "complete" : "pending";
  }
  const completed = events.some((event) => event.type === "node_completed" && event.agent === node);
  return completed || isFinished(status) ? "complete" : "pending";
}

export function phaseQaState(
  phase: "collect" | "analyst",
  active: string | null | undefined,
  events: RunEvent[],
  status: RunStatus,
): NodeState {
  const node = phase === "collect" ? "collect_qa" : "analyst_qa";
  if (status === "failed" && active === node) return "failed";
  if (status === "interrupted" && active === node) return "interrupted";
  if (active === node) return "active";
  const phaseEvents = events.filter((event) => event.agent === "qa" && event.subagent === phase);
  if (phaseEvents.some((event) => event.type === "node_completed")) return "complete";
  return isFinished(status) ? "complete" : "pending";
}

export function branchState(
  agent: ParallelAgent,
  branch: string,
  events: RunEvent[],
  status: RunStatus,
  active: string | null | undefined,
): NodeState {
  const branchEvents = events.filter((event) => event.agent === agent && event.subagent === branch);
  const latest = branchEvents[branchEvents.length - 1];
  if (status === "failed" && active === agent && latest?.type === "node_started") return "failed";
  if (status === "interrupted" && active === agent && latest?.type === "node_started") return "interrupted";
  if (latest?.type === "node_started") return "active";
  if (branchEvents.some((event) => event.type === "node_completed")) return "complete";
  return isFinished(status) ? "complete" : "pending";
}

export function dispatchState(
  agent: "collector_dispatch" | "analyst_dispatch",
  active: string | null | undefined,
  events: RunEvent[],
  status: RunStatus,
): NodeState {
  if (status === "failed" && active === agent) return "failed";
  if (status === "interrupted" && active === agent) return "interrupted";
  if (active === agent) return "active";
  if (nodeCompleted(events, agent)) return "complete";
  return isFinished(status) ? "complete" : "pending";
}

export function joinState(
  agent: ParallelAgent,
  joinAgent: "collect_join" | "analyst_join",
  branches: string[],
  events: RunEvent[],
  status: RunStatus,
): NodeState {
  if (nodeCompleted(events, joinAgent) || isFinished(status)) return "complete";
  if (hasAgentEvent(events, joinAgent)) return "active";
  const completeCount = branches.filter((branch) =>
    events.some((event) => event.type === "node_completed" && event.agent === agent && event.subagent === branch),
  ).length;
  if (completeCount === branches.length) return "complete";
  if (completeCount > 0) return "active";
  return "pending";
}

export function stageWaveCount(events: RunEvent[], agent: ParallelAgent, branches: string[]) {
  return Math.max(...branches.map((branch) => branchAttemptCount(events, agent, branch)), 1);
}

export function branchAttemptCount(events: RunEvent[], agent: ParallelAgent, branch: string) {
  return Math.max(
    1,
    events.filter((event) => event.type === "node_started" && event.agent === agent && event.subagent === branch).length,
  );
}

export function joinAttemptCount(events: RunEvent[], agent: ParallelAgent) {
  const joinAgent = agent === "collector" ? "collect_join" : "analyst_join";
  return Math.max(
    1,
    events.filter((event) => event.type === "node_started" && event.agent === joinAgent).length,
  );
}

export function qaCaption(events: RunEvent[], phase: "collect" | "analyst", base: string) {
  const checks = events.filter((event) => event.type === "node_started" && event.agent === "qa" && event.subagent === phase).length;
  const issues = events.filter((event) => event.type === "qa_issue" && event.subagent === phase).map(readIssue);
  const blockerCount = issues.filter((issue) => issue.severity === "blocker").length;
  const warnCount = issues.filter((issue) => issue.severity === "warn").length;
  const suffix = [
    `${Math.max(1, checks)} check(s)`,
    blockerCount > 0 ? `${blockerCount} blocker` : null,
    warnCount > 0 ? `${warnCount} warn` : null,
  ].filter(Boolean).join(" / ");
  return `${base} / ${suffix}`;
}

export function branchLabel(branch: string) {
  const parsed = parseBranch(branch);
  return parsed.competitor ? `${parsed.competitor} / ${parsed.dimension}` : `slice=${branch}`;
}

export function collectorCaption(branch: string) {
  const dimension = parseBranch(branch).dimension;
  if (dimension === "pricing") return "search -> fetch -> extract";
  if (dimension === "review") return "review site -> fetch -> extract";
  if (dimension === "persona") return "survey sim + interview";
  return "search -> fetch docs -> extract";
}

export function analystCaption(branch: string) {
  const dimension = parseBranch(branch).dimension;
  if (dimension === "pricing") return "normalize units + citations";
  if (dimension === "persona") return "sentiment aggregation";
  if (dimension === "swot") return "cross-competitor view";
  return "citation-checked findings";
}

export function formatRunStatus(status: RunStatus) {
  return status === "completed_with_blockers" ? "completed, blocked" : status;
}

function hasAgentEvent(events: RunEvent[], agent: string, subagent?: string) {
  return events.some((event) => event.agent === agent && (subagent === undefined || event.subagent === subagent));
}

function nodeCompleted(events: RunEvent[], agent: string, subagent?: string) {
  return events.some(
    (event) =>
      event.type === "node_completed" &&
      event.agent === agent &&
      (subagent === undefined || event.subagent === subagent),
  );
}

function branchCompleted(events: RunEvent[], agent: ParallelAgent) {
  return events.some((event) => event.type === "node_completed" && event.agent === agent && event.subagent);
}

function collectJoinCompleted(events: RunEvent[]) {
  return nodeCompleted(events, "collect_join");
}

function hasPhaseQaEvent(events: RunEvent[], phase: "collect" | "analyst") {
  return events.some((event) => event.agent === "qa" && event.subagent === phase);
}

function previousTailCompleted(events: RunEvent[], node: SingleFlowNodeId) {
  if (node === "comparator") return phaseCompletedWithoutBlocker(events, "analyst");
  if (node === "reflector") return nodeCompleted(events, "comparator");
  if (node === "writer") return nodeCompleted(events, "reflector");
  if (node === "qa") return nodeCompleted(events, "writer");
  return false;
}

function phaseCompletedWithoutBlocker(events: RunEvent[], phase: "collect" | "analyst") {
  const completed = nodeCompleted(events, "qa", phase);
  if (!completed) return false;
  return !events.some((event) => {
    if (event.type !== "qa_issue" || event.subagent !== phase) return false;
    const issue = event.payload.issue;
    return typeof issue === "object" && issue !== null && "severity" in issue && issue.severity === "blocker";
  });
}

function buildPhaseReturnItems(
  events: RunEvent[],
  phase: "collect" | "analyst",
  from: string,
  to: string,
): ReturnItem[] {
  return events
    .filter((event) => event.type === "qa_issue" && event.subagent === phase)
    .map((event) => {
      const issue = readIssue(event);
      return {
        id: event.id,
        from,
        to,
        severity: issue.severity,
        problem: issue.problem,
      };
    })
    .filter((item) => item.severity === "blocker");
}

function readIssue(event: RunEvent) {
  const raw = event.payload.issue;
  if (typeof raw === "object" && raw !== null) {
    const maybe = raw as { severity?: unknown; problem?: unknown; id?: unknown };
    return {
      id: typeof maybe.id === "string" ? maybe.id : `event-${event.id}`,
      severity: typeof maybe.severity === "string" ? maybe.severity : "info",
      problem: typeof maybe.problem === "string" ? maybe.problem : event.message,
    };
  }
  const rawIssues = event.payload.issues;
  if (Array.isArray(rawIssues) && rawIssues.length > 0) {
    const first = rawIssues[0] as { severity?: unknown; problem?: unknown; id?: unknown };
    return {
      id: typeof first.id === "string" ? first.id : `event-${event.id}`,
      severity: typeof first.severity === "string" ? first.severity : "info",
      problem:
        typeof first.problem === "string"
          ? rawIssues.length > 1
            ? `${first.problem} (+${rawIssues.length - 1} more)`
            : first.problem
          : event.message,
    };
  }
  return { id: `event-${event.id}`, severity: "info", problem: event.message };
}

function readRedoScope(event: RunEvent) {
  const raw = event.payload.redo_scope;
  if (typeof raw === "object" && raw !== null) {
    const maybe = raw as {
      kind?: unknown;
      target_subagent?: unknown;
      target_competitor?: unknown;
      target_competitors?: unknown;
    };
    const targetCompetitors = Array.isArray(maybe.target_competitors)
      ? maybe.target_competitors.filter((item): item is string => typeof item === "string")
      : [];
    return {
      kind: typeof maybe.kind === "string" ? maybe.kind : "full",
      targetSubagent: typeof maybe.target_subagent === "string" ? maybe.target_subagent : null,
      targetCompetitor:
        targetCompetitors.length > 0
          ? targetCompetitors.join(", ")
          : typeof maybe.target_competitor === "string"
            ? maybe.target_competitor
            : null,
    };
  }
  return { kind: "full", targetSubagent: null, targetCompetitor: null };
}

function formatRedoTarget(kind: string, targetSubagent: string | null, targetCompetitor: string | null) {
  const target = [targetCompetitor, targetSubagent].filter(Boolean).join(" / ");
  if (kind === "collector") return target ? `Collector / ${target}` : "Collector";
  if (kind === "analyst") return target ? `Analyst / ${target}` : "Analyst";
  if (kind === "comparator") return "Comparator";
  if (kind === "writer_only") return "Writer";
  return "Planner";
}

function branchId(dimension: string, competitor: string) {
  return `${dimension}::${competitor}`;
}

function parseBranch(branch: string) {
  const [dimension, ...competitorParts] = branch.split("::");
  return {
    dimension,
    competitor: competitorParts.join("::"),
  };
}

function unique(values: string[]) {
  return Array.from(new Set(values));
}

function isFinished(status: RunStatus) {
  return status === "completed" || status === "completed_with_blockers";
}
