import { AlertTriangle, CheckCircle2, Circle, GitBranch, Loader2, Merge, PauseCircle, RotateCcw } from "lucide-react";
import type { RunEvent } from "../../api/sse_types";
import type { RunStatus } from "../../api/types";
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
            <em>
              {caption} · {branchAttemptCount(events, agent, branch)} run(s)
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
  return (
    <div className="return-group" aria-label="QA return path">
      {returns.map((item) => (
        <article className="return-card" key={`${item.from}-${item.id}`}>
          <div className="flow-icon">
            <RotateCcw size={17} aria-hidden />
          </div>
          <div>
            <strong>
              {item.from} returned to {item.to}
            </strong>
            <span>
              {item.severity}: {item.problem}
            </span>
          </div>
        </article>
      ))}
    </div>
  );
}

export function ScopedRedoPanel({ loops }: { loops: ScopedRedoItem[] }) {
  return (
    <div className="scoped-redo-panel" aria-label="Final QA scoped redo returns">
      {loops.map((loop) => (
        <article className="return-card scoped" key={`scoped-${loop.id}`}>
          <div className="flow-icon">
            <RotateCcw size={17} aria-hidden />
          </div>
          <div>
            <strong>
              {loop.from} returned to {loop.to}
            </strong>
            <span>
              {loop.severity}: {loop.problem}
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
  return (
    <article className={`topology-node ${state}`}>
      <div className="flow-icon">{renderStateIcon(state)}</div>
      <div>
        <strong>{node.label}</strong>
        <span>{node.caption}</span>
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
