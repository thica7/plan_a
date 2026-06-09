import type { RunEvent } from "../../api/sse_types";
import type { RunStatus } from "../../api/types";
import {
  Connector,
  DispatchNode,
  JoinNode,
  ParallelGroup,
  QaNode,
  ReturnGroup,
  ScopedRedoPanel,
  SingleNode,
} from "./GraphNodes";
import { plannerHitlNode, qaHitlNode, singleNodes } from "./graphDefinition";
import {
  buildAnalystBranches,
  buildCollectorBranches,
  buildPhaseReturns,
  buildScopedRedoLoops,
  dispatchState,
  formatRunStatus,
  joinAttemptCount,
  joinState,
  phaseQaState,
  qaCaption,
  resolveActiveNode,
  resolveNodeState,
  resolveVisibleStages,
  stageWaveCount,
} from "./graphModel";

interface Props {
  activeNode?: string | null;
  competitors: string[];
  dimensions: string[];
  events: RunEvent[];
  revisionCount: number;
  status: RunStatus;
}

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
        <SingleNode node={singleNodes[0]} state={resolveNodeState("planner", active, events, status)} />
        {visible.plannerHitl ? (
          <SingleNode node={plannerHitlNode} state={resolveNodeState("planner_hitl", active, events, status)} />
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
          <QaNode
            label="Collect QA"
            caption={qaCaption(events, "collect", "source coverage gate")}
            state={phaseQaState("collect", active, events, status)}
          />
        ) : null}
        {phaseReturns.collect.length > 0 ? <ReturnGroup returns={phaseReturns.collect} /> : null}

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
          <QaNode
            label="Analyst QA"
            caption={qaCaption(events, "analyst", "KB citation gate")}
            state={phaseQaState("analyst", active, events, status)}
          />
        ) : null}
        {phaseReturns.analyst.length > 0 ? <ReturnGroup returns={phaseReturns.analyst} /> : null}

        {visible.tail.length > 0 ? (
          <div className="topology-tail">
            {singleNodes
              .slice(1)
              .filter((node) => visible.tail.includes(node.id))
              .map((node) => (
                <SingleNode key={node.id} node={node} state={resolveNodeState(node.id, active, events, status)} />
              ))}
          </div>
        ) : null}
        {visible.qaHitl ? (
          <SingleNode node={qaHitlNode} state={resolveNodeState("qa_hitl", active, events, status)} />
        ) : null}
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
