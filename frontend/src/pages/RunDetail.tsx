import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Loader2, RotateCcw } from "lucide-react";
import { getRun, resumeRun, subscribeRun } from "../api/client";
import { CompetitorDiscoveryView } from "../features/discovery/CompetitorDiscoveryView";
import { StaticGraphView } from "../features/graph/StaticGraphView";
import { KbMatrixView } from "../features/kb/KbMatrixView";
import { ReportView } from "../features/report/ReportView";
import { RevisionDiff } from "../features/revisions/RevisionDiff";
import { SwimlaneView } from "../features/swimlane/SwimlaneView";
import { TraceList } from "../features/trace/TraceList";
import { useRunStore } from "../stores/run";

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

  async function handleRedo() {
    if (!runId) return;
    setRedoing(true);
    setError(null);
    try {
      const updated = await resumeRun(runId, { decision: "redo", note: "Redo from QA panel" });
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
        <section className="hitl-panel">
          <div>
            <h2>{interruptStage === "qa" ? "QA review" : "Plan review"}</h2>
            <p>{latestInterrupt.message}</p>
          </div>
          {interruptStage === "planner" ? (
            <label>
              Dimensions
              <input value={planDimensions} onChange={(event) => setPlanDimensions(event.target.value)} />
            </label>
          ) : null}
          <div className="hitl-actions">
            {interruptStage === "planner" ? (
              <>
                <button className="icon-text-button" onClick={() => handleHitl("accept")} type="button">
                  <CheckCircle2 size={15} aria-hidden />
                  Continue
                </button>
                <button className="icon-text-button" onClick={() => handleHitl("modify_plan")} type="button">
                  Apply dimensions
                </button>
              </>
            ) : (
              <>
                <button className="icon-text-button" onClick={() => handleHitl("accept")} type="button">
                  <CheckCircle2 size={15} aria-hidden />
                  Accept
                </button>
                <button className="icon-text-button" onClick={() => handleHitl("force_pass")} type="button">
                  Force pass
                </button>
                <button
                  className="icon-text-button"
                  disabled={isRedoing || redoLimitReached}
                  onClick={() => handleHitl("redo")}
                  type="button"
                >
                  <RotateCcw size={15} aria-hidden />
                  Redo
                </button>
              </>
            )}
          </div>
        </section>
      ) : null}

      <div className="detail-grid">
        <SwimlaneView events={events} currentNode={detail.current_node} />
        <StaticGraphView
          activeNode={detail.current_node}
          dimensions={detail.plan.dimensions}
          events={events}
          revisionCount={detail.revisions.length}
          status={detail.status}
        />
        <CompetitorDiscoveryView discovery={detail.competitor_discovery} />
        <ReportView markdown={detail.report_md} sources={detail.raw_sources} />
        <KbMatrixView kbs={detail.competitor_kbs} matrix={detail.comparison_matrix} />
        <RevisionDiff revisions={detail.revisions} />
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
                <code>{issue.redo_scope.kind}:{issue.redo_scope.target_subagent || "all"}</code>
              </article>
            ))
          )}
        </aside>
        <TraceList events={events} metrics={detail.metrics} spans={detail.trace_spans} />
      </div>
    </section>
  );
}
