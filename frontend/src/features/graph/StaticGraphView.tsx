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
  joinAttemptCount,
  joinState,
  phaseQaState,
  qaCaption,
  resolveActiveNode,
  resolveNodeState,
  resolveVisibleStages,
  stageWaveCount,
} from "./graphModel";
import { useTranslation } from '../../stores/i18n';
import { displayLabel } from "../../i18n/display";
import { SystemMessage } from "../../i18n/SystemMessage";

interface Props {
  activeNode?: string | null;
  competitors: string[];
  dimensions: string[];
  events: RunEvent[];
  revisionCount: number;
  status: RunStatus;
}

export function StaticGraphView({ activeNode, competitors, dimensions, events, revisionCount, status }: Props) {
  const { locale, t } = useTranslation();
  const active = resolveActiveNode(events, activeNode, status);
  const latestRedo = [...events].reverse().find((event) => event.message.startsWith("Scoped redo started"));
  const branchDimensions = dimensions.length > 0 ? dimensions : ["pricing", "feature"];
  const collectorBranches = buildCollectorBranches(branchDimensions, competitors, events);
  const analystBranches = buildAnalystBranches(branchDimensions, competitors, events);
  const visible = resolveVisibleStages(events, active, status);
  const phaseReturns = buildPhaseReturns(events);
  const scopedRedoLoops = buildScopedRedoLoops(events, locale);

  return (
    <section className="panel graph-panel">
      <div className="panel-heading-row">
        <h2>{t('graph.flowGraph')}</h2>
        <span className={`flow-status ${status}`}>{displayLabel(status, locale)}</span>
      </div>

      <div className="topology-graph" aria-label={t('graph.topology')}>
        <SingleNode node={singleNodes[0]} state={resolveNodeState("planner", active, events, status)} />
        {visible.plannerHitl ? (
          <SingleNode node={plannerHitlNode} state={resolveNodeState("planner_hitl", active, events, status)} />
        ) : null}

        {visible.collector ? (
          <>
            <Connector label={t('graph.collectorGate')} />
            <DispatchNode
              label={t('graph.collectorDispatch')}
              caption={`${t('graph.collectorDispatchCaption')} · ${t('graph.attempt')} ${stageWaveCount(events, "collector", collectorBranches)}`}
              state={dispatchState("collector_dispatch", active, events, status)}
            />
            <ParallelGroup
              agent="collector"
              branches={collectorBranches}
              caption={t('graph.sourceOutput')}
              events={events}
              status={status}
              active={active}
            />
          </>
        ) : null}
        {visible.collectJoin ? (
          <JoinNode
            label={t('graph.collectJoin')}
            caption={`${t('graph.collectJoinCaption')} · ${joinAttemptCount(events, "collector")} ${t('graph.runCount')}`}
            state={joinState("collector", "collect_join", collectorBranches, events, status)}
          />
        ) : null}
        {visible.collectQa ? (
          <QaNode
            label={t('graph.collectQa')}
            caption={qaCaption(events, "collect", t('graph.sourceGate'), locale)}
            state={phaseQaState("collect", active, events, status)}
          />
        ) : null}
        {phaseReturns.collect.length > 0 ? <ReturnGroup returns={phaseReturns.collect} /> : null}

        {visible.analyst ? (
          <>
            <Connector label={t('graph.analystGate')} />
            <DispatchNode
              label={t('graph.analystDispatch')}
              caption={`${t('graph.analystDispatchCaption')} · ${t('graph.attempt')} ${stageWaveCount(events, "analyst", analystBranches)}`}
              state={dispatchState("analyst_dispatch", active, events, status)}
            />
            <ParallelGroup
              agent="analyst"
              branches={analystBranches}
              caption={t('graph.knowledgeOutput')}
              events={events}
              status={status}
              active={active}
            />
          </>
        ) : null}
        {visible.analystJoin ? (
          <JoinNode
            label={t('graph.analystJoin')}
            caption={`${t('graph.analystJoinCaption')} · ${stageWaveCount(events, "analyst", analystBranches)} ${t('graph.runCount')}`}
            state={joinState("analyst", "analyst_join", analystBranches, events, status)}
          />
        ) : null}
        {visible.analystQa ? (
          <QaNode
            label={t('graph.analystQa')}
            caption={qaCaption(events, "analyst", t('graph.citationGate'), locale)}
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
        <span>{t('graph.events')} {events.length}</span>
        <span>{t('graph.revisions')} {revisionCount}</span>
        <span>{t('graph.parallelBranches')} {collectorBranches.length + analystBranches.length}</span>
        {latestRedo ? <SystemMessage message={latestRedo.message} /> : null}
      </div>
    </section>
  );
}
