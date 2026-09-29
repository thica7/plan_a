import { AlertTriangle, CheckCircle2, Circle, GitBranch, Loader2, Merge, PauseCircle, RotateCcw } from "lucide-react";
import type { RunEvent } from "../../api/sse_types";
import type { RunStatus } from "../../api/types";
import { useTranslation } from '../../stores/i18n';
import { displayLabel } from "../../i18n/display";
import { SystemMessage } from "../../i18n/SystemMessage";
import {
  analystCaption,
  branchAttemptCount,
  branchLabel,
  branchState,
  collectorCaption,
} from "./graphModel";
import type { NodeState, ParallelAgent, ReturnItem, ScopedRedoItem, SingleFlowNode } from "./types";

interface ParallelGroupProps {
  active: string | null | undefined;
  agent: ParallelAgent;
  branches: string[];
  caption: string;
  events: RunEvent[];
  status: RunStatus;
}

export function ParallelGroup({ agent, branches, caption, events, status, active }: ParallelGroupProps) {
  const { locale, t } = useTranslation();
  return (
    <div className="parallel-group">
      {branches.map((branch) => {
        const state = branchState(agent, branch, events, status, active);
        return (
          <article className={`parallel-card ${state}`} key={`${agent}-${branch}`}>
            <div className="flow-icon">{renderStateIcon(state)}</div>
            <div>
              <strong>{displayLabel(agent, locale)}</strong>
              <span>{branchLabel(branch, locale)}</span>
            </div>
            <p>{agent === "collector" ? collectorCaption(branch, locale) : analystCaption(branch, locale)}</p>
            <em>
              {caption} · {branchAttemptCount(events, agent, branch)} {t('graph.runCount')}
            </em>
          </article>
        );
      })}
    </div>
  );
}

export function DispatchNode({ label, caption, state }: { label: string; caption: string; state: NodeState }) {
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

export function JoinNode({ label, caption, state }: { label: string; caption: string; state: NodeState }) {
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

export function QaNode({ label, caption, state }: { label: string; caption: string; state: NodeState }) {
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

export function ReturnGroup({ returns }: { returns: ReturnItem[] }) {
  const { locale, t } = useTranslation();
  return (
    <div className="return-group" aria-label={t('graph.qaReturnPath')}>
      {returns.map((item) => (
        <article className="return-card" key={`${item.from}-${item.id}`}>
          <div className="flow-icon">
            <RotateCcw size={17} aria-hidden />
          </div>
          <div>
            <strong>
              {displayLabel(item.from, locale)} {t('graph.returnedTo')} {displayLabel(item.to, locale)}
            </strong>
            <span>
              {displayLabel(item.severity, locale)}: <SystemMessage message={item.problem} />
            </span>
          </div>
        </article>
      ))}
    </div>
  );
}

export function ScopedRedoPanel({ loops }: { loops: ScopedRedoItem[] }) {
  const { locale, t } = useTranslation();
  return (
    <div className="scoped-redo-panel" aria-label={t('graph.finalQaReturns')}>
      {loops.map((loop) => (
        <article className="return-card scoped" key={`scoped-${loop.id}`}>
          <div className="flow-icon">
            <RotateCcw size={17} aria-hidden />
          </div>
          <div>
            <strong>
              {displayLabel(loop.from, locale)} {t('graph.returnedTo')} {loop.to}
            </strong>
            <span>
              {displayLabel(loop.severity, locale)}: <SystemMessage message={loop.problem} />
            </span>
            <em>{loop.scope}</em>
          </div>
        </article>
      ))}
    </div>
  );
}

export function Connector({ label }: { label: string }) {
  return (
    <div className="topology-connector" aria-hidden>
      <span />
      <em>{label}</em>
    </div>
  );
}

export function SingleNode({ node, state }: { node: SingleFlowNode; state: NodeState }) {
  const { locale, t } = useTranslation();
  return (
    <article className={`topology-node ${state}`}>
      <div className="flow-icon">{renderStateIcon(state)}</div>
      <div>
        <strong>{displayLabel(node.id, locale)}</strong>
        <span>{t(`graph.caption.${node.id}`)}</span>
      </div>
    </article>
  );
}

function renderStateIcon(state: NodeState) {
  if (state === "complete") return <CheckCircle2 size={17} aria-hidden />;
  if (state === "active") return <Loader2 className="spin" size={17} aria-hidden />;
  if (state === "interrupted") return <PauseCircle size={17} aria-hidden />;
  if (state === "failed") return <AlertTriangle size={17} aria-hidden />;
  return <Circle size={15} aria-hidden />;
}
