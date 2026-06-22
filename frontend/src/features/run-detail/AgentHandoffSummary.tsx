import { FileText, GitBranch, ListChecks, ShieldCheck } from "lucide-react";

import type { AgentMessage, RunDetail as RunDetailRecord, TraceSpan } from "../../api/types";
import { Panel, StatusPill } from "../../components/ui";

interface AgentHandoffSummaryProps {
  detail: RunDetailRecord;
  messages: AgentMessage[];
  mode?: "compact" | "full";
}

const EXPECTED_HANDOFFS = [
  ["planner", "collector_dispatch", "plan"],
  ["collector", "collect_join", "sources"],
  ["collect_join", "qa", "collection QA"],
  ["analyst", "analyst_join", "knowledge"],
  ["comparator", "reflector", "matrix"],
  ["reflector", "writer", "constraints"],
  ["writer", "qa", "report"],
] as const;

export function AgentHandoffSummary({ detail, messages, mode = "full" }: AgentHandoffSummaryProps) {
  const latestReflection = detail.reflections[detail.reflections.length - 1];
  const writerReport = latestMessage(messages, (message) => (
    message.payload_schema === "MarkdownReport" || (message.from_agent === "writer" && message.to_agent === "qa")
  ));
  const writerSpan = latestSpan(detail.trace_spans, (span) => span.agent === "writer");
  const hasReport = detail.report_md.trim().length > 0;
  const writerRepairMode = payloadString(writerReport?.payload, "writer_repair_mode")
    ?? metadataString(writerSpan, "writer_repair_mode")
    ?? (hasReport ? "none" : "pending");
  const writerMode = payloadString(writerReport?.payload, "writer_mode") ?? (hasReport ? "report ready" : "pending");
  const writerSections = payloadStringList(writerReport?.payload, "writer_repair_sections");
  const handoffs = buildHandoffRows(detail, messages);
  const stageCounts = countPlanStages(detail);
  const taskReasons = detail.plan.task_decomposition
    .map((task) => task.reason)
    .filter(Boolean)
    .slice(0, 3);
  const compact = mode === "compact";

  return (
    <Panel
      className={`agent-handoff-summary ${compact ? "compact" : ""}`}
      title="Agent handoff"
      icon={<GitBranch size={16} aria-hidden />}
    >
      <div className="handoff-signal-grid">
        <SignalBlock
          label="Layer / scenario"
          tone="neutral"
          value={`${detail.plan.competitor_layer} / ${detail.plan.scenario_id ?? "auto"}`}
          detail={`${detail.plan.qa_rule_ids.length} QA rules / ${detail.plan.task_decomposition.length} tasks`}
        />
        <SignalBlock
          label="Reflector gate"
          tone={gateTone(latestReflection?.gate_status)}
          value={latestReflection?.gate_status ?? "pending"}
          detail={`${latestReflection?.writer_constraints.length ?? 0} writer constraints`}
        />
        <SignalBlock
          label="Writer mode"
          tone={writerRepairMode === "none" ? "good" : "warn"}
          value={writerRepairMode}
          detail={writerMode}
        />
      </div>

      <div className="agent-workload-grid">
        <article>
          <ListChecks size={15} aria-hidden />
          <strong>Task split</strong>
          <span>
            collector {stageCounts.collector} / analyst {stageCounts.analyst} / survey {stageCounts.survey_interview}
          </span>
        </article>
        <article>
          <ShieldCheck size={15} aria-hidden />
          <strong>Reflector input</strong>
          <span>
            {detail.comparison_matrix ? `${detail.comparison_matrix.cells.length} matrix cells` : "matrix pending"} /{" "}
            {detail.reflections.length} reviews
          </span>
        </article>
        <article>
          <FileText size={15} aria-hidden />
          <strong>Writer surface</strong>
          <span>{detail.report_md.length.toLocaleString()} chars / {writerSections.length || 0} repair sections</span>
        </article>
      </div>

      {latestReflection?.writer_constraints.length ? (
        <div className="handoff-constraint-list">
          {latestReflection.writer_constraints.slice(0, compact ? 2 : 5).map((constraint) => (
            <span key={constraint}>{constraint}</span>
          ))}
        </div>
      ) : null}

      {!compact && latestReflection?.blocking_gaps.length ? (
        <div className="handoff-gap-list">
          {latestReflection.blocking_gaps.slice(0, 4).map((gap) => (
            <span key={gap}>{gap}</span>
          ))}
        </div>
      ) : null}

      {!compact && taskReasons.length ? (
        <div className="handoff-rationale-list">
          {taskReasons.map((reason) => (
            <span key={reason}>{reason}</span>
          ))}
        </div>
      ) : null}

      <div className="handoff-route-list">
        {handoffs.map((handoff) => (
          <article key={`${handoff.from}-${handoff.to}`}>
            <strong>{handoff.from} -&gt; {handoff.to}</strong>
            <StatusPill tone={handoff.linked ? "good" : "neutral"}>{handoff.linked ? "linked" : "pending"}</StatusPill>
            <span>
              {handoff.label}
              {handoff.count > 1 ? ` / ${handoff.count} messages` : handoff.inferred ? " / inferred" : ""}
            </span>
          </article>
        ))}
      </div>
    </Panel>
  );
}

function SignalBlock({
  detail,
  label,
  tone,
  value,
}: {
  detail: string;
  label: string;
  tone: "good" | "neutral" | "warn" | "bad";
  value: string;
}) {
  return (
    <article className="handoff-signal-block">
      <span>{label}</span>
      <StatusPill tone={tone}>{value}</StatusPill>
      <em>{detail}</em>
    </article>
  );
}

function buildHandoffRows(detail: RunDetailRecord, messages: AgentMessage[]) {
  return EXPECTED_HANDOFFS.map(([from, to, label]) => {
    const count = messages.filter((message) => message.from_agent === from && message.to_agent === to).length;
    const inferred = inferHandoffFromRunState(detail, from, to);
    return {
      count,
      from,
      inferred,
      label,
      linked: count > 0 || inferred,
      to,
    };
  });
}

function inferHandoffFromRunState(detail: RunDetailRecord, from: string, to: string) {
  if (from === "comparator" && to === "reflector") {
    return Boolean(detail.comparison_matrix && detail.reflections.length);
  }
  if (from === "reflector" && to === "writer") {
    return detail.reflections.length > 0 && detail.report_md.trim().length > 0;
  }
  if (from === "writer" && to === "qa") {
    return detail.report_md.trim().length > 0 && ["completed", "completed_with_blockers"].includes(detail.status);
  }
  return false;
}

function countPlanStages(detail: RunDetailRecord) {
  return detail.plan.task_decomposition.reduce(
    (counts, task) => {
      counts[task.stage] += 1;
      return counts;
    },
    { analyst: 0, collector: 0, survey_interview: 0 },
  );
}

function latestMessage(messages: AgentMessage[], predicate: (message: AgentMessage) => boolean) {
  return [...messages].reverse().find(predicate);
}

function latestSpan(spans: TraceSpan[], predicate: (span: TraceSpan) => boolean) {
  return [...spans].reverse().find(predicate);
}

function payloadString(payload: Record<string, unknown> | undefined, key: string) {
  const value = payload?.[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function payloadStringList(payload: Record<string, unknown> | undefined, key: string) {
  const value = payload?.[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function metadataString(span: TraceSpan | undefined, key: string) {
  const value = span?.metadata[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function gateTone(gate: string | undefined) {
  if (gate === "block") return "bad";
  if (gate === "warn") return "warn";
  if (gate === "pass") return "good";
  return "neutral";
}