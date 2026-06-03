import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Download, Loader2, RotateCcw } from "lucide-react";
import {
  exportRunComplianceReport,
  getDecisionReplay,
  getRun,
  getRunComplianceReport,
  getRunQualityComparison,
  redoRun,
  resumeRun,
  subscribeRun,
} from "../api/client";
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
import type {
  ArtifactRecord,
  AnalysisPlanTask,
  DecisionReplayReport,
  ReflectionRecord,
  RunComplianceReport,
  RunQualityComparison,
} from "../api/types";

export function RunDetail() {
  const { runId } = useParams();
  const { detail, events, setDetail, addEvent, reset } = useRunStore();
  const [error, setError] = useState<string | null>(null);
  const [isRedoing, setRedoing] = useState(false);
  const [planDimensions, setPlanDimensions] = useState("");
  const [qualityComparison, setQualityComparison] = useState<RunQualityComparison | null>(null);
  const [decisionReplay, setDecisionReplay] = useState<DecisionReplayReport | null>(null);
  const [complianceReport, setComplianceReport] = useState<RunComplianceReport | null>(null);
  const [complianceExport, setComplianceExport] = useState<ArtifactRecord | null>(null);
  const [isExportingCompliance, setExportingCompliance] = useState(false);
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
    setDecisionReplay(null);
    setComplianceReport(null);
    setComplianceExport(null);

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
          void getDecisionReplay(runId)
            .then((replay) => {
              if (!cancelled) setDecisionReplay(replay);
            })
            .catch(() => {
              if (!cancelled) setDecisionReplay(null);
            });
          void getRunComplianceReport(runId)
            .then((report) => {
              if (!cancelled) setComplianceReport(report);
            })
            .catch(() => {
              if (!cancelled) setComplianceReport(null);
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
      getDecisionReplay(runId)
        .then(setDecisionReplay)
        .catch(() => setDecisionReplay(null));
      getRunComplianceReport(runId)
        .then(setComplianceReport)
        .catch(() => setComplianceReport(null));
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
  const recommendedDimensions = detail.plan.scenario_recommended_dimensions.filter(
    (dimension) => !detail.plan.dimensions.includes(dimension),
  );

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

  async function handleExportCompliance() {
    if (!runId) return;
    setExportingCompliance(true);
    setError(null);
    try {
      const result = await exportRunComplianceReport(runId);
      setComplianceExport(result.artifact);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to export compliance report");
    } finally {
      setExportingCompliance(false);
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
            <span>QA rules {detail.plan.qa_rule_ids.length}</span>
            <span>Tasks {detail.plan.task_decomposition.length}</span>
            {detail.plan.qa_rule_ids.slice(0, 4).map((ruleId) => (
              <span key={ruleId}>{ruleId}</span>
            ))}
            {recommendedDimensions.length > 0 ? (
              <span>Recommended {recommendedDimensions.join(", ")}</span>
            ) : null}
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
        <TaskDecompositionPanel tasks={detail.plan.task_decomposition} />
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
        <CompliancePanel
          exportArtifact={complianceExport}
          isExporting={isExportingCompliance}
          onExport={handleExportCompliance}
          report={complianceReport}
        />
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
        <TraceList
          events={events}
          metrics={detail.metrics}
          replay={decisionReplay}
          spans={detail.trace_spans}
        />
      </div>
    </section>
  );
}

function TaskDecompositionPanel({ tasks }: { tasks: AnalysisPlanTask[] }) {
  const stageCounts = summarizeTaskStages(tasks);
  const watchTasks = [...tasks]
    .sort((left, right) => {
      const priorityDelta = taskPriorityRank(right.priority) - taskPriorityRank(left.priority);
      if (priorityDelta !== 0) return priorityDelta;
      if (right.max_turns !== left.max_turns) return right.max_turns - left.max_turns;
      return left.id.localeCompare(right.id);
    })
    .slice(0, 8);
  const highPriorityCount = tasks.filter((task) => task.priority === "high").length;
  const maxTurnBudget = tasks.reduce((total, task) => total + task.max_turns, 0);

  return (
    <aside className="qa-panel run-quality-panel">
      <div className="panel-heading-row">
        <h2>Task decomposition</h2>
        <span className="muted-text">{tasks.length} tasks</span>
      </div>
      <div className="metric-grid compact">
        <MetricValue label="Collector" value={String(stageCounts.collector ?? 0)} />
        <MetricValue label="Analyst" value={String(stageCounts.analyst ?? 0)} />
        <MetricValue label="Research" value={String(stageCounts.survey_interview ?? 0)} />
        <MetricValue label="High priority" value={String(highPriorityCount)} />
      </div>
      <div className="project-meta-row">
        <span>Max turns {maxTurnBudget}</span>
        <span>Stages {Object.keys(stageCounts).length}</span>
      </div>
      {watchTasks.length > 0 ? (
        <div className="recommendation-list compact">
          {watchTasks.map((task) => (
            <article className={`recommendation-card ${taskPriorityClass(task.priority)}`} key={task.id}>
              <strong>{task.stage}</strong>
              <span>
                {task.competitor ?? "all competitors"} / {task.dimension} / {task.priority}
              </span>
              <p>{task.reason}</p>
              <div className="project-meta-row">
                <span>Turns {task.max_turns}</span>
                <span>Deps {task.depends_on.length}</span>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted-text">No adaptive tasks have been planned yet.</p>
      )}
    </aside>
  );
}

function CompliancePanel({
  exportArtifact,
  isExporting,
  onExport,
  report,
}: {
  exportArtifact: ArtifactRecord | null;
  isExporting: boolean;
  onExport: () => void;
  report: RunComplianceReport | null;
}) {
  if (!report) {
    return (
      <aside className="qa-panel run-quality-panel">
        <div className="panel-heading-row">
          <h2>Compliance</h2>
          <Loader2 className="spin" size={16} aria-hidden />
        </div>
        <p className="muted-text">Loading compliance report.</p>
      </aside>
    );
  }

  const topFindings = report.findings.slice(0, 5);
  return (
    <aside className={`qa-panel run-quality-panel ${report.status}`}>
      <div className="panel-heading-row">
        <h2>Compliance</h2>
        <button
          className="icon-text-button"
          disabled={isExporting}
          onClick={onExport}
          type="button"
        >
          <Download size={15} aria-hidden />
          {isExporting ? "Exporting" : "Export"}
        </button>
      </div>
      <div className="metric-grid compact">
        <MetricValue label="Status" value={report.status} />
        <MetricValue label="Findings" value={String(report.finding_count)} />
        <MetricValue label="Blockers" value={String(report.blocker_count)} />
        <MetricValue label="Redactions" value={String(report.redaction_count)} />
      </div>
      <div className="run-quality-signals">
        <span className={report.policy.redaction_enabled ? "on" : "off"}>
          {report.policy.redaction_enabled ? (
            <CheckCircle2 size={13} aria-hidden />
          ) : (
            <AlertTriangle size={13} aria-hidden />
          )}
          Redaction
        </span>
        <span className={report.policy.require_trace_context ? "on" : "off"}>
          {report.policy.require_trace_context ? (
            <CheckCircle2 size={13} aria-hidden />
          ) : (
            <AlertTriangle size={13} aria-hidden />
          )}
          Trace context
        </span>
        <span className={report.policy.require_source_urls ? "on" : "off"}>
          {report.policy.require_source_urls ? (
            <CheckCircle2 size={13} aria-hidden />
          ) : (
            <AlertTriangle size={13} aria-hidden />
          )}
          Source URLs
        </span>
      </div>
      {topFindings.length > 0 ? (
        <div className="reflection-review">
          <h3>Findings</h3>
          {topFindings.map((finding) => (
            <article className="issue-row reflection-row" key={finding.id}>
              <strong>{finding.severity}</strong>
              <span>
                {finding.category}: {finding.message}
              </span>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted-text">No compliance findings.</p>
      )}
      {exportArtifact ? (
        <p className="muted-text">
          {exportArtifact.filename} / {exportArtifact.uri}
        </p>
      ) : null}
    </aside>
  );
}

function summarizeTaskStages(tasks: AnalysisPlanTask[]) {
  return tasks.reduce<Record<AnalysisPlanTask["stage"], number>>(
    (counts, task) => {
      counts[task.stage] += 1;
      return counts;
    },
    { collector: 0, analyst: 0, survey_interview: 0 },
  );
}

function taskPriorityRank(priority: AnalysisPlanTask["priority"]) {
  if (priority === "high") return 3;
  if (priority === "medium") return 2;
  return 1;
}

function taskPriorityClass(priority: AnalysisPlanTask["priority"]) {
  if (priority === "high") return "high";
  if (priority === "medium") return "medium";
  return "low";
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
  const signalChecks =
    comparison.signal_checks.length > 0
      ? comparison.signal_checks
      : signalRows.map(([label, enabled]) => ({
          signal: label.toLowerCase().replace(/\s+/g, "_"),
          label,
          passed: enabled,
          reason: enabled ? "Signal passed." : "Signal did not pass.",
          blocking_metric_names: [],
        }));
  const failedSignalChecks = signalChecks.filter((check) => !check.passed);
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
        {signalChecks.map((check) => (
          <span className={check.passed ? "on" : "off"} key={check.signal} title={check.reason}>
            {check.passed ? <CheckCircle2 size={13} aria-hidden /> : <AlertTriangle size={13} aria-hidden />}
            {check.label}
          </span>
        ))}
      </div>
      {failedSignalChecks.length > 0 ? (
        <div className="reflection-review">
          <h3>Signal blockers</h3>
          {failedSignalChecks.map((check) => (
            <article className="issue-row reflection-row" key={check.signal}>
              <strong>{check.label}</strong>
              <span>
                {check.reason}
                {check.blocking_metric_names.length > 0
                  ? ` Blocked by ${check.blocking_metric_names.join(", ")}.`
                  : ""}
              </span>
            </article>
          ))}
        </div>
      ) : null}
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
