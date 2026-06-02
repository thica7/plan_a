import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Loader2, RotateCcw } from "lucide-react";
import { getRun, getRunQualityComparison, redoRun, resumeRun, subscribeRun } from "../api/client";
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
import type { ReflectionRecord, RunQualityComparison } from "../api/types";

export function RunDetail() {
  const { runId } = useParams();
  const { detail, events, setDetail, addEvent, reset } = useRunStore();
  const [error, setError] = useState<string | null>(null);
  const [isRedoing, setRedoing] = useState(false);
  const [planDimensions, setPlanDimensions] = useState("");
  const [qualityComparison, setQualityComparison] = useState<RunQualityComparison | null>(null);
  const redoLimitReached = detail ? detail.revisions.length >= detail.max_iterations : false;
  const latestInterrupt = useMemo(
    () => [...events].reverse().find((event) => event.type === "interrupt"),
    [events],
  );
  const interruptStage = typeof latestInterrupt?.payload.stage === "string" ? latestInterrupt.payload.stage : null;

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    let retryTimer: number | undefined;
    let unsubscribe: (() => void) | undefined;
    reset();
    setQualityComparison(null);

    const load = (attempt: number) => {
      getRun(runId)
        .then((loaded) => {
          if (cancelled) return;
          setError(null);
          setDetail(loaded);
          void getRunQualityComparison(runId)
            .then((comparison) => {
              if (!cancelled) setQualityComparison(comparison);
            })
            .catch(() => {
              if (!cancelled) setQualityComparison(null);
            });
          unsubscribe = subscribeRun(runId, addEvent);
        })
        .catch((err: Error) => {
          if (cancelled) return;
          if (err.message.includes("Run not found") && attempt < 120) {
            retryTimer = window.setTimeout(() => load(attempt + 1), 1000);
            return;
          }
          setError(err.message);
        });
    };

    load(0);
    return () => {
      cancelled = true;
      if (retryTimer !== undefined) {
        window.clearTimeout(retryTimer);
      }
      if (unsubscribe) {
        unsubscribe();
      }
    };
  }, [addEvent, reset, runId, setDetail]);

  useEffect(() => {
    if (!runId) return;
    if (events.some((event) => ["interrupt", "run_completed", "run_failed"].includes(event.type))) {
      getRun(runId).then(setDetail).catch((err: Error) => setError(err.message));
      getRunQualityComparison(runId)
        .then(setQualityComparison)
        .catch(() => setQualityComparison(null));
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
          <div className="run-meta-row">
            <span>Layer {detail.plan.competitor_layer}</span>
            <span>Scenario {detail.plan.scenario_id ?? "auto"}</span>
            {detail.plan.qa_rule_ids.slice(0, 4).map((ruleId) => (
              <span key={ruleId}>{ruleId}</span>
            ))}
          </div>
        </div>
        <div className={`status-chip ${detail.status}`}>
          {detail.status === "completed" ? (
            <CheckCircle2 size={16} aria-hidden />
          ) : detail.status === "completed_with_blockers" ? (
            <AlertTriangle size={16} aria-hidden />
          ) : (
            <Loader2 size={16} aria-hidden />
          )}
          {detail.status === "completed_with_blockers" ? "completed, blocked" : detail.status}
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
        <RunQualityPanel comparison={qualityComparison} />
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

function RunQualityPanel({ comparison }: { comparison: RunQualityComparison | null }) {
  if (!comparison) {
    return (
      <aside className="qa-panel run-quality-panel">
        <div className="panel-heading-row">
          <h2>Run quality</h2>
          <Loader2 className="spin" size={16} aria-hidden />
        </div>
        <p className="muted-text">Loading quality comparison.</p>
      </aside>
    );
  }

  const signalRows = [
    ["Real collection", comparison.real_collection_signal],
    ["Real LLM", comparison.real_llm_signal],
    ["Report quality", comparison.report_quality_signal],
  ] as const;
  const highlightedMetrics = comparison.metrics
    .filter((metric) => metric.status === "regressed" || metric.status === "baseline_missing")
    .slice(0, 5);

  return (
    <aside className={`qa-panel run-quality-panel ${comparison.verdict}`}>
      <div className="panel-heading-row">
        <h2>Run quality</h2>
        {comparison.verdict === "pass" ? (
          <CheckCircle2 size={16} aria-hidden />
        ) : (
          <AlertTriangle size={16} aria-hidden />
        )}
      </div>
      <div className="metric-grid compact">
        <MetricValue label="Score" value={`${comparison.target_score}/100`} />
        <MetricValue label="Verdict" value={comparison.verdict} />
        <MetricValue
          label="Baseline"
          value={comparison.baseline_score === null || comparison.baseline_score === undefined ? "none" : `${comparison.baseline_score}/100`}
        />
        <MetricValue
          label="Delta"
          value={comparison.delta_score === null || comparison.delta_score === undefined ? "n/a" : String(comparison.delta_score)}
        />
      </div>
      <div className="run-quality-signals">
        {signalRows.map(([label, enabled]) => (
          <span className={enabled ? "on" : "off"} key={label}>
            {enabled ? <CheckCircle2 size={13} aria-hidden /> : <AlertTriangle size={13} aria-hidden />}
            {label}
          </span>
        ))}
      </div>
      {highlightedMetrics.length > 0 ? (
        <div className="reflection-review">
          <h3>Watch metrics</h3>
          {highlightedMetrics.map((metric) => (
            <article className="issue-row reflection-row" key={metric.name}>
              <strong>{metric.status.replace(/_/g, " ")}</strong>
              <span>
                {metric.name}: {formatQualityValue(metric.target_value)}
                {metric.baseline_value !== null && metric.baseline_value !== undefined
                  ? ` / baseline ${formatQualityValue(metric.baseline_value)}`
                  : ""}
              </span>
            </article>
          ))}
        </div>
      ) : null}
      {comparison.recommendations.length > 0 ? (
        <div className="reflection-review">
          <h3>Recommendations</h3>
          {comparison.recommendations.slice(0, 3).map((item) => (
            <article className="issue-row reflection-row" key={item}>
              <strong>next</strong>
              <span>{item}</span>
            </article>
          ))}
        </div>
      ) : null}
    </aside>
  );
}

function MetricValue({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <i aria-hidden />
      <strong>{value}</strong>
      <em>{label}</em>
    </span>
  );
}

function formatQualityValue(value: number) {
  if (Number.isInteger(value)) return String(value);
  return Math.abs(value) < 1 ? value.toFixed(2) : value.toFixed(1);
}

function flattenReflection(reflection: ReflectionRecord) {
  return [
    ...reflection.coverage_gaps.map((text, index) => ({ kind: "coverage", text, index })),
    ...reflection.confidence_outliers.map((text, index) => ({ kind: "confidence", text, index })),
    ...reflection.cross_competitor_gaps.map((text, index) => ({ kind: "cross", text, index })),
  ].filter((item) => item.text.trim());
}
