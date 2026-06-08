import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  GitBranch,
  Loader2,
  Merge,
  PauseCircle,
  RotateCcw,
} from "lucide-react";
import type { RunEvent } from "../../api/sse_types";
import type { RunStatus } from "../../api/types";

interface Props {
  activeNode?: string | null;
  competitors: string[];
  dimensions: string[];
  events: RunEvent[];
  revisionCount: number;
  status: RunStatus;
}

type FlowNodeId =
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
type NodeState = "pending" | "active" | "complete" | "interrupted" | "failed";

const singleNodes: Array<{
  id: Exclude<
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
  label: string;
  caption: string;
}> = [
  { id: "planner", label: "Planner", caption: "LLM + web search" },
  { id: "comparator", label: "Comparator", caption: "ComparisonMatrix" },
  { id: "reflector", label: "Reflector", caption: "coverage gaps" },
  { id: "writer", label: "Writer", caption: "markdown report" },
  { id: "qa", label: "QA", caption: "4-lane checks" },
];

const plannerHitlNode = { id: "planner_hitl" as const, label: "Planner HITL", caption: "plan review interrupt" };
const qaHitlNode = { id: "qa_hitl" as const, label: "QA HITL", caption: "force pass / redo" };

const nodeIds = new Set<FlowNodeId>([
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

export function StaticGraphView({ activeNode, competitors, dimensions, events, revisionCount, status }: Props) {
  const active = resolveActiveNode(events, activeNode, status);
  const latestRedo = [...events].reverse().find((event) => event.message.startsWith("Scoped redo started"));
  const branchDimensions = dimensions.length > 0 ? dimensions : ["pricing", "feature"];
  const collectorBranches = buildCollectorBranches(branchDimensions, competitors, events);
  const analystBranches = buildAnalystBranches(branchDimensions, competitors, events);
  const visible = resolveVisibleStages(events, active, status);
  const phaseReturns = buildPhaseReturns(events);
  const scopedRedoLoops = buildScopedRedoLoops(events);

  return (
    <section className="panel graph-panel">
      <div className="panel-heading-row">
        <h2>Flow graph</h2>
        <span className={`flow-status ${status}`}>{formatRunStatus(status)}</span>
      </div>

      <div className="topology-graph" aria-label="Live LangGraph topology with parallel branches">
        {renderSingleNode(singleNodes[0], resolveNodeState("planner", active, events, status))}
        {visible.plannerHitl ? (
          renderSingleNode(plannerHitlNode, resolveNodeState("planner_hitl", active, events, status))
        ) : null}
        {visible.collector ? (
          <>
            <Connector label="collector gate" />
            <DispatchNode
              label="Collector dispatch"
              caption={`Send(competitor x dim) · attempt ${stageWaveCount(events, "collector", collectorBranches)}`}
              state={dispatchState("collector_dispatch", active, events, status)}
            />
            <ParallelGroup
              agent="collector"
              branches={collectorBranches}
              caption="RawSource[] + message"
              events={events}
              status={status}
              active={active}
            />
          </>
        ) : null}
        {visible.collectJoin ? (
          <JoinNode
            label="Collect join"
            caption={`normalize + dedupe sources · ${joinAttemptCount(events, "collector")} run(s)`}
            state={joinState("collector", "collect_join", collectorBranches, events, status)}
          />
        ) : null}
        {visible.collectQa ? (
          <QaNode label="Collect QA" caption={qaCaption(events, "collect", "source coverage gate")} state={phaseQaState("collect", active, events, status)} />
        ) : null}
        {phaseReturns.collect.length > 0 ? (
          <ReturnGroup returns={phaseReturns.collect} />
        ) : null}

        {visible.analyst ? (
          <>
            <Connector label="analyst gate" />
            <DispatchNode
              label="Analyst dispatch"
              caption={`Send(competitor x slice) · attempt ${stageWaveCount(events, "analyst", analystBranches)}`}
              state={dispatchState("analyst_dispatch", active, events, status)}
            />
            <ParallelGroup
              agent="analyst"
              branches={analystBranches}
              caption="CompetitorKnowledge"
              events={events}
              status={status}
              active={active}
            />
          </>
        ) : null}
        {visible.analystJoin ? (
          <JoinNode
            label="Analyst join"
            caption={`reducer: merge_kbs · ${stageWaveCount(events, "analyst", analystBranches)} run(s)`}
            state={joinState("analyst", "analyst_join", analystBranches, events, status)}
          />
        ) : null}
        {visible.analystQa ? (
          <QaNode label="Analyst QA" caption={qaCaption(events, "analyst", "KB citation gate")} state={phaseQaState("analyst", active, events, status)} />
        ) : null}
        {phaseReturns.analyst.length > 0 ? (
          <ReturnGroup returns={phaseReturns.analyst} />
        ) : null}

        {visible.tail.length > 0 ? (
          <div className="topology-tail">
            {singleNodes
              .slice(1)
              .filter((node) => visible.tail.includes(node.id))
              .map((node) => renderSingleNode(node, resolveNodeState(node.id, active, events, status)))}
          </div>
        ) : null}
        {visible.qaHitl ? renderSingleNode(qaHitlNode, resolveNodeState("qa_hitl", active, events, status)) : null}
        {scopedRedoLoops.length > 0 ? <ScopedRedoPanel loops={scopedRedoLoops} /> : null}
      </div>

      <div className="flow-meta">
        <span>Events {events.length}</span>
        <span>Revisions {revisionCount}</span>
        <span>Parallel branches {collectorBranches.length + analystBranches.length}</span>
        {latestRedo ? <span>{latestRedo.message}</span> : null}
      </div>
    </section>
  );
}

function ParallelGroup({
  agent,
  branches,
  caption,
  events,
  status,
  active,
}: {
  agent: "collector" | "analyst";
  branches: string[];
  caption: string;
  events: RunEvent[];
  status: RunStatus;
  active: string | null | undefined;
}) {
  return (
    <div className="parallel-group">
      {branches.map((branch) => {
        const state = branchState(agent, branch, events, status, active);
        return (
          <article className={`parallel-card ${state}`} key={`${agent}-${branch}`}>
            <div className="flow-icon">{renderStateIcon(state)}</div>
            <div>
              <strong>{agent}</strong>
              <span>{branchLabel(branch)}</span>
            </div>
            <p>{agent === "collector" ? collectorCaption(branch) : analystCaption(branch)}</p>
            <em>{caption} · {branchAttemptCount(events, agent, branch)} run(s)</em>
          </article>
        );
      })}
    </div>
  );
}

function DispatchNode({ label, caption, state }: { label: string; caption: string; state: NodeState }) {
  return (
    <article className={`topology-dispatch ${state}`}>
      <div className="flow-icon">
        <GitBranch size={17} aria-hidden />
      </div>
      <div>
        <strong>{label}</strong>
        <span>{caption}</span>
      </div>
    </article>
  );
}

function JoinNode({ label, caption, state }: { label: string; caption: string; state: NodeState }) {
  return (
    <article className={`topology-join ${state}`}>
      <div className="flow-icon">
        <Merge size={17} aria-hidden />
      </div>
      <div>
        <strong>{label}</strong>
        <span>{caption}</span>
      </div>
    </article>
  );
}

function QaNode({ label, caption, state }: { label: string; caption: string; state: NodeState }) {
  return (
    <article className={`topology-node phase-qa ${state}`}>
      <div className="flow-icon">{renderStateIcon(state)}</div>
      <div>
        <strong>{label}</strong>
        <span>{caption}</span>
      </div>
    </article>
  );
}

interface ReturnItem {
  id: number;
  from: string;
  to: string;
  severity: string;
  problem: string;
}

interface ScopedRedoItem {
  id: number;
  from: string;
  to: string;
  severity: string;
  problem: string;
  scope: string;
}

function ReturnGroup({ returns }: { returns: ReturnItem[] }) {
  return (
    <div className="return-group" aria-label="QA return path">
      {returns.map((item) => (
        <article className="return-card" key={`${item.from}-${item.id}`}>
          <div className="flow-icon">
            <RotateCcw size={17} aria-hidden />
          </div>
          <div>
            <strong>{item.from} returned to {item.to}</strong>
            <span>{item.severity}: {item.problem}</span>
          </div>
        </article>
      ))}
    </div>
  );
}

function ScopedRedoPanel({ loops }: { loops: ScopedRedoItem[] }) {
  return (
    <div className="scoped-redo-panel" aria-label="Final QA scoped redo returns">
      {loops.map((loop) => (
        <article className="return-card scoped" key={`scoped-${loop.id}`}>
          <div className="flow-icon">
            <RotateCcw size={17} aria-hidden />
          </div>
          <div>
            <strong>{loop.from} returned to {loop.to}</strong>
            <span>{loop.severity}: {loop.problem}</span>
            <em>{loop.scope}</em>
          </div>
        </article>
      ))}
    </div>
  );
}

function Connector({ label }: { label: string }) {
  return (
    <div className="topology-connector" aria-hidden>
      <span />
      <em>{label}</em>
    </div>
  );
}

function renderSingleNode(
  node: {
    id: Exclude<
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
    label: string;
    caption: string;
  },
  state: NodeState,
) {
  return (
    <article className={`topology-node ${state}`} key={node.id}>
      <div className="flow-icon">{renderStateIcon(state)}</div>
      <div>
        <strong>{node.label}</strong>
        <span>{node.caption}</span>
      </div>
    </article>
  );
}

function resolveActiveNode(events: RunEvent[], activeNode: string | null | undefined, status: RunStatus) {
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

function resolveVisibleStages(events: RunEvent[], active: string | null | undefined, status: RunStatus) {
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

function branchCompleted(events: RunEvent[], agent: "collector" | "analyst") {
  return events.some((event) => event.type === "node_completed" && event.agent === agent && event.subagent);
}

function collectJoinCompleted(events: RunEvent[]) {
  return nodeCompleted(events, "collect_join");
}

function hasPhaseQaEvent(events: RunEvent[], phase: "collect" | "analyst") {
  return events.some((event) => event.agent === "qa" && event.subagent === phase);
}

function previousTailCompleted(
  events: RunEvent[],
  node: Exclude<
    FlowNodeId,
    | "collector_dispatch"
    | "collector"
    | "collect_join"
    | "collect_qa"
    | "analyst_dispatch"
    | "analyst"
    | "analyst_join"
    | "analyst_qa"
  >,
) {
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

function buildCollectorBranches(dimensions: string[], competitors: string[], events: RunEvent[]) {
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

function buildAnalystBranches(dimensions: string[], competitors: string[], events: RunEvent[]) {
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

function branchLabel(branch: string) {
  const parsed = parseBranch(branch);
  return parsed.competitor ? `${parsed.competitor} / ${parsed.dimension}` : `slice=${branch}`;
}

function unique(values: string[]) {
  return Array.from(new Set(values));
}

function buildPhaseReturns(events: RunEvent[]) {
  return {
    collect: buildPhaseReturnItems(events, "collect", "Collect QA", "Collector"),
    analyst: buildPhaseReturnItems(events, "analyst", "Analyst QA", "Analyst"),
  };
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

function buildScopedRedoLoops(events: RunEvent[]): ScopedRedoItem[] {
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

function stageWaveCount(events: RunEvent[], agent: "collector" | "analyst", branches: string[]) {
  return Math.max(...branches.map((branch) => branchAttemptCount(events, agent, branch)), 1);
}

function branchAttemptCount(events: RunEvent[], agent: "collector" | "analyst", branch: string) {
  return Math.max(
    1,
    events.filter((event) => event.type === "node_started" && event.agent === agent && event.subagent === branch).length,
  );
}

function joinAttemptCount(events: RunEvent[], agent: "collector" | "analyst") {
  const joinAgent = agent === "collector" ? "collect_join" : "analyst_join";
  return Math.max(
    1,
    events.filter((event) => event.type === "node_started" && event.agent === joinAgent).length,
  );
}

function qaCaption(events: RunEvent[], phase: "collect" | "analyst", base: string) {
  const checks = events.filter((event) => event.type === "node_started" && event.agent === "qa" && event.subagent === phase).length;
  const issues = events.filter((event) => event.type === "qa_issue" && event.subagent === phase).map(readIssue);
  const blockerCount = issues.filter((issue) => issue.severity === "blocker").length;
  const warnCount = issues.filter((issue) => issue.severity === "warn").length;
  const suffix = [
    `${Math.max(1, checks)} check(s)`,
    blockerCount > 0 ? `${blockerCount} blocker` : null,
    warnCount > 0 ? `${warnCount} warn` : null,
  ].filter(Boolean).join(" · ");
  return `${base} · ${suffix}`;
}

function resolveNodeState(
  node: Exclude<
    FlowNodeId,
    | "collector_dispatch"
    | "collector"
    | "collect_join"
    | "collect_qa"
    | "analyst_dispatch"
    | "analyst"
    | "analyst_join"
    | "analyst_qa"
  >,
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

function phaseQaState(
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

function branchState(
  agent: "collector" | "analyst",
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

function groupState(
  agent: "collector" | "analyst",
  branches: string[],
  events: RunEvent[],
  status: RunStatus,
  active: string | null | undefined,
): NodeState {
  const states = branches.map((branch) => branchState(agent, branch, events, status, active));
  if (states.includes("active")) return "active";
  if (states.includes("interrupted")) return "interrupted";
  if (states.includes("failed")) return "failed";
  if (states.some((state) => state === "complete")) return "complete";
  return "pending";
}

function dispatchState(
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

function joinState(
  agent: "collector" | "analyst",
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

function collectorCaption(branch: string) {
  const dimension = parseBranch(branch).dimension;
  if (dimension === "pricing") return "search -> fetch -> extract";
  if (dimension === "review") return "review site -> fetch -> extract";
  if (dimension === "persona") return "survey sim + interview";
  return "search -> fetch docs -> extract";
}

function analystCaption(branch: string) {
  const dimension = parseBranch(branch).dimension;
  if (dimension === "pricing") return "normalize units + citations";
  if (dimension === "persona") return "sentiment aggregation";
  if (dimension === "swot") return "cross-competitor view";
  return "citation-checked findings";
}

function isFinished(status: RunStatus) {
  return status === "completed" || status === "completed_with_blockers";
}

function formatRunStatus(status: RunStatus) {
  return status === "completed_with_blockers" ? "completed, blocked" : status;
}

function renderStateIcon(state: NodeState) {
  if (state === "complete") return <CheckCircle2 size={17} aria-hidden />;
  if (state === "active") return <Loader2 className="spin" size={17} aria-hidden />;
  if (state === "interrupted") return <PauseCircle size={17} aria-hidden />;
  if (state === "failed") return <AlertTriangle size={17} aria-hidden />;
  if (state === "pending") return <Circle size={17} aria-hidden />;
  return <RotateCcw size={17} aria-hidden />;
}
