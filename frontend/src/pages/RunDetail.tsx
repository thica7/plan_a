import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Loader2, RotateCcw } from "lucide-react";
import { getRun, redoRun, resumeRun, subscribeRun } from "../api/client";
import { CompetitorDiscoveryView } from "../features/discovery/CompetitorDiscoveryView";
import { CostPanel } from "../features/cost/CostPanel";
import { StaticGraphView } from "../features/graph/StaticGraphView";
import { PlanReviewModal } from "../features/hitl/PlanReviewModal";
import { QaReviewModal } from "../features/hitl/QaReviewModal";
import { KbMatrixView } from "../features/kb/KbMatrixView";
import { AgentMessagesView } from "../features/messages/AgentMessagesView";
import { ReportView } from "../features/report/ReportView";
import { RevisionDiff } from "../features/revisions/RevisionDiff";
import { SwimlaneView } from "../features/swimlane/SwimlaneView";
import { TraceList } from "../features/trace/TraceList";
import { TracePlayback } from "../features/trace/TracePlayback";
import { useRunStore } from "../stores/run";
import type { ReflectionRecord } from "../api/types";

export function RunDetail() {
  const { runId } = useParams();
  const { detail, events, setDetail, addEvent, reset } = useRunStore();
  const [error, setError] = useState<string | null>(null);
  const [isRedoing, setRedoing] = useState(false);
  const [planDimensions, setPlanDimensions] = useState("");
  const redoLimitReached = detail ? detail.revisions.length >= detail.max_iterations : false;
  const latestInterrupt = useMemo(
    () => [...events].reverse().find((event) => event.type === "interrupt"),
    [events],
  );
  const interruptStage = typeof latestInterrupt?.payload.stage === "string" ? latestInterrupt.payload.stage : null;

  useEffect(() => {
    if (!runId) return;
    reset();
    getRun(runId).then(setDetail).catch((err: Error) => setError(err.message));
    const unsubscribe = subscribeRun(runId, addEvent);
    return unsubscribe;
  }, [addEvent, reset, runId, setDetail]);

  useEffect(() => {
    if (!runId) return;
    if (events.some((event) => ["interrupt", "run_completed", "run_failed"].includes(event.type))) {
      getRun(runId).then(setDetail).catch((err: Error) => setError(err.message));
    }
  }, [events, runId, setDetail]);

  useEffect(() => {
    if (detail) {
      setPlanDimensions(detail.plan.dimensions.join(", "));
    }
  }, [detail?.id, detail?.plan.dimensions]);

  if (error) {
    return (
      <section className="work-surface">
        <div className="empty-state">
          <AlertTriangle aria-hidden />
          <p>{error}</p>
        </div>
      </section>
    );
  }

  if (!detail) {
    return (
      <section className="work-surface">
        <div className="empty-state">
          <Loader2 className="spin" aria-hidden />
          <p>Loading run</p>
        </div>
      </section>
    );
  }

  const latestReflection = detail.reflections.length > 0 ? detail.reflections[detail.reflections.length - 1] : null;
  const reflectionItems = latestReflection ? flattenReflection(latestReflection) : [];

  async function handleRedo() {
    if (!runId) return;
    setRedoing(true);
    setError(null);
    try {
      const updated = await redoRun(runId);
      setDetail(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to trigger scoped redo");
    } finally {
      setRedoing(false);
    }
  }

  async function handleHitl(decision: "accept" | "modify_plan" | "force_pass" | "redo") {
    if (!runId) return;
    setRedoing(decision === "redo");
    setError(null);
    try {
      const payload =
        decision === "modify_plan"
          ? {
              decision,
              note: "Plan reviewed in HITL panel",
              dimensions: planDimensions
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean),
            }
          : { decision, note: "Reviewed in HITL panel" };
      const updated = await resumeRun(runId, payload);
      setDetail(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to resume run");
    } finally {
      setRedoing(false);
    }
  }

  return (
    <section className="run-detail">
      <header className="page-header">
        <div>
          <h1>{detail.topic}</h1>
          <p>
            {detail.plan.competitors.join(" vs ")} · {detail.plan.dimensions.join(", ")} ·{" "}
            {detail.execution_mode}
          </p>
        </div>
        <div className={`status-chip ${detail.status}`}>
          {detail.status === "completed" ? <CheckCircle2 size={16} aria-hidden /> : <Loader2 size={16} aria-hidden />}
          {detail.status}
        </div>
      </header>

      {detail.status === "interrupted" && latestInterrupt ? (
        interruptStage === "planner" ? (
          <PlanReviewModal
            dimensions={planDimensions}
            message={latestInterrupt.message}
            onAccept={() => handleHitl("accept")}
            onApply={() => handleHitl("modify_plan")}
            onDimensionsChange={setPlanDimensions}
          />
        ) : (
          <QaReviewModal
            isRedoing={isRedoing}
            message={latestInterrupt.message}
            onAccept={() => handleHitl("accept")}
            onForcePass={() => handleHitl("force_pass")}
            onRedo={() => handleHitl("redo")}
            redoDisabled={redoLimitReached}
          />
        )
      ) : null}

      <div className="detail-grid">
        <SwimlaneView events={events} currentNode={detail.current_node} />
        <StaticGraphView
          activeNode={detail.current_node}
          competitors={detail.plan.competitors}
          dimensions={detail.plan.dimensions}
          events={events}
          revisionCount={detail.revisions.length}
          status={detail.status}
        />
        <CompetitorDiscoveryView discovery={detail.competitor_discovery} />
        <ReportView markdown={detail.report_md} sources={detail.raw_sources} />
        <KbMatrixView
          kbs={detail.competitor_kbs}
          knowledge={detail.competitor_knowledge}
          matrix={detail.comparison_matrix}
          sources={detail.raw_sources}
        />
        <AgentMessagesView messages={detail.agent_messages} toolCalls={detail.tool_call_messages} />
        <TracePlayback spans={detail.trace_spans} />
        <RevisionDiff revisions={detail.revisions} />
        <CostPanel metrics={detail.metrics} spans={detail.trace_spans} />
        <aside className="qa-panel">
          <div className="panel-heading-row">
            <h2>QA findings</h2>
            {detail.qa_findings.length > 0 ? (
              <button
                className="icon-text-button"
                disabled={isRedoing || redoLimitReached}
                onClick={handleRedo}
                title={redoLimitReached ? "Maximum redo iterations reached" : "Redo scoped issue"}
                type="button"
              >
                <RotateCcw size={15} aria-hidden />
                {redoLimitReached ? "Limit reached" : "Redo"}
              </button>
            ) : null}
          </div>
          {detail.qa_findings.length > 0 ? (
            <p className="muted-text">
              Redo rounds {detail.revisions.length}/{detail.max_iterations}
            </p>
          ) : null}
          {detail.qa_findings.length === 0 ? (
            <p>No findings yet.</p>
          ) : (
            detail.qa_findings.map((issue) => (
              <article key={issue.id} className="issue-row">
                <strong>{issue.severity}</strong>
                <span>{issue.problem}</span>
                <code>
                  {issue.redo_scope.kind}:
                  {issue.redo_scope.target_competitors?.length
                    ? `${issue.redo_scope.target_competitors.join(", ")}/`
                    : issue.redo_scope.target_competitor
                      ? `${issue.redo_scope.target_competitor}/`
                      : ""}
                  {issue.redo_scope.target_subagent || "all"}
                </code>
              </article>
            ))
          )}
          {reflectionItems.length > 0 ? (
            <div className="reflection-review">
              <h3>Reflector review</h3>
              {reflectionItems.map((item) => (
                <article key={`${item.kind}-${item.index}`} className="issue-row reflection-row">
                  <strong>{item.kind}</strong>
                  <span>{item.text}</span>
                </article>
              ))}
            </div>
          ) : null}
        </aside>
        <TraceList events={events} metrics={detail.metrics} spans={detail.trace_spans} />
      </div>
    </section>
  );
}

function flattenReflection(reflection: ReflectionRecord) {
  return [
    ...reflection.coverage_gaps.map((text, index) => ({ kind: "coverage", text, index })),
    ...reflection.confidence_outliers.map((text, index) => ({ kind: "confidence", text, index })),
    ...reflection.cross_competitor_gaps.map((text, index) => ({ kind: "cross", text, index })),
  ].filter((item) => item.text.trim());
}
