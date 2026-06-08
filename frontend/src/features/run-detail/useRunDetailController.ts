import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  exportRunComplianceReport,
  getDecisionReplay,
  getRun,
  getRunComplianceReport,
  getRunQualityComparison,
  listRuns,
  redoRun,
  resumeRun,
  subscribeRun,
} from "../../api/client";
import type {
  ArtifactRecord,
  DecisionReplayReport,
  RunComplianceReport,
  RunQualityComparison,
  RunSummary,
} from "../../api/types";
import { buildReportSourceBundle } from "../report/sourceBundle";
import { useRunStore } from "../../stores/run";
import type { RunDetailView } from "./types";
import { flattenReflection } from "./utils";

export type HitlDecision = "accept" | "modify_plan" | "force_pass" | "redo";

export function useRunDetailController() {
  const { runId } = useParams();
  const { detail, events, setDetail, addEvent, reset } = useRunStore();
  const [activeView, setActiveView] = useState<RunDetailView>("overview");
  const [error, setError] = useState<string | null>(null);
  const [isRedoing, setRedoing] = useState(false);
  const [planDimensions, setPlanDimensions] = useState("");
  const [qualityComparison, setQualityComparison] = useState<RunQualityComparison | null>(null);
  const [qualityBaselineRunId, setQualityBaselineRunId] = useState("");
  const [runHistory, setRunHistory] = useState<RunSummary[]>([]);
  const [decisionReplay, setDecisionReplay] = useState<DecisionReplayReport | null>(null);
  const [complianceReport, setComplianceReport] = useState<RunComplianceReport | null>(null);
  const [complianceExport, setComplianceExport] = useState<ArtifactRecord | null>(null);
  const [isExportingCompliance, setExportingCompliance] = useState(false);

  const redoLimitReached = detail ? detail.revisions.length >= detail.max_iterations : false;
  const latestInterrupt = useMemo(
    () => [...events].reverse().find((event) => event.type === "interrupt"),
    [events],
  );
  const reportSources = useMemo(() => {
    const projection = detail?.enterprise_projection;
    if (!projection) {
      return { sources: detail?.raw_sources ?? [], aliases: {} };
    }
    return buildReportSourceBundle(projection.evidence_records, {
      scopedEvidenceIds: projection.report_version.evidence_ids,
    });
  }, [detail?.enterprise_projection, detail?.raw_sources]);
  const interruptStage = typeof latestInterrupt?.payload.stage === "string" ? latestInterrupt.payload.stage : null;

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    let retryTimer: number | undefined;
    let unsubscribe: (() => void) | undefined;
    reset();
    setQualityComparison(null);
    setQualityBaselineRunId("");
    setRunHistory([]);
    setDecisionReplay(null);
    setComplianceReport(null);
    setComplianceExport(null);

    const load = (attempt: number) => {
      getRun(runId)
        .then((loaded) => {
          if (cancelled) return;
          setError(null);
          setDetail(loaded);
          void listRuns()
            .then((items) => {
              if (!cancelled) {
                setRunHistory(items.filter((item) => item.id !== runId));
              }
            })
            .catch(() => {
              if (!cancelled) setRunHistory([]);
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
    let cancelled = false;
    setQualityComparison(null);
    getRunQualityComparison(runId, qualityBaselineRunId || undefined)
      .then((comparison) => {
        if (!cancelled) setQualityComparison(comparison);
      })
      .catch(() => {
        if (!cancelled) setQualityComparison(null);
      });
    return () => {
      cancelled = true;
    };
  }, [qualityBaselineRunId, runId]);

  useEffect(() => {
    if (!runId) return;
    if (events.some((event) => ["interrupt", "run_completed", "run_failed"].includes(event.type))) {
      getRun(runId).then(setDetail).catch((err: Error) => setError(err.message));
      getRunQualityComparison(runId, qualityBaselineRunId || undefined)
        .then(setQualityComparison)
        .catch(() => setQualityComparison(null));
      getDecisionReplay(runId)
        .then(setDecisionReplay)
        .catch(() => setDecisionReplay(null));
      getRunComplianceReport(runId)
        .then(setComplianceReport)
        .catch(() => setComplianceReport(null));
    }
  }, [events, qualityBaselineRunId, runId, setDetail]);

  useEffect(() => {
    if (detail) {
      setPlanDimensions(detail.plan.dimensions.join(", "));
    }
  }, [detail?.id, detail?.plan.dimensions]);

  const latestReflection = detail?.reflections.length ? detail.reflections[detail.reflections.length - 1] : null;
  const reflectionItems = latestReflection ? flattenReflection(latestReflection) : [];
  const recommendedDimensions = detail
    ? detail.plan.scenario_recommended_dimensions.filter((dimension) => !detail.plan.dimensions.includes(dimension))
    : [];
  const citedClaimRate = detail ? Math.round(detail.metrics.claim_citation_rate * 100) : 0;
  const verifiedSourceRate = detail ? Math.round(detail.metrics.verified_source_rate * 100) : 0;
  const sourceCoverageRate = detail ? Math.round(detail.metrics.source_coverage_rate * 100) : 0;

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

  async function handleHitl(decision: HitlDecision) {
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

  return {
    activeView,
    citedClaimRate,
    complianceExport,
    complianceReport,
    decisionReplay,
    detail,
    error,
    events,
    handleExportCompliance,
    handleHitl,
    handleRedo,
    interruptStage,
    isExportingCompliance,
    isRedoing,
    latestInterrupt,
    planDimensions,
    qualityBaselineRunId,
    qualityComparison,
    recommendedDimensions,
    redoLimitReached,
    reflectionItems,
    reportSources,
    runHistory,
    setActiveView,
    setPlanDimensions,
    setQualityBaselineRunId,
    sourceCoverageRate,
    verifiedSourceRate,
  };
}
