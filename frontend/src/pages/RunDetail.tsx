import { AlertTriangle, Loader2 } from "lucide-react";
import { PlanReviewModal } from "../features/hitl/PlanReviewModal";
import { QaReviewModal } from "../features/hitl/QaReviewModal";
import { RunDetailContent } from "../features/run-detail/RunDetailContent";
import { RunDetailHeader } from "../features/run-detail/RunDetailHeader";
import { RunDetailTabs } from "../features/run-detail/RunDetailTabs";
import { RunSummaryStrip } from "../features/run-detail/RunSummaryStrip";
import { useRunDetailController } from "../features/run-detail/useRunDetailController";

export function RunDetail() {
  const {
    activeView,
    canApplyPlanDimensionChanges,
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
  } = useRunDetailController();

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

  return (
    <section className="run-detail">
      <RunDetailHeader detail={detail} recommendedDimensions={recommendedDimensions} />
      <RunSummaryStrip
        citedClaimRate={citedClaimRate}
        detail={detail}
        sourceCoverageRate={sourceCoverageRate}
        verifiedSourceRate={verifiedSourceRate}
      />

      {detail.status === "interrupted" && latestInterrupt ? (
        interruptStage === "planner" ? (
          <PlanReviewModal
            canApplyDimensions={canApplyPlanDimensionChanges}
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

      <RunDetailTabs activeView={activeView} onChange={setActiveView} />

      <RunDetailContent
        activeView={activeView}
        complianceExport={complianceExport}
        complianceReport={complianceReport}
        decisionReplay={decisionReplay}
        detail={detail}
        events={events}
        isExportingCompliance={isExportingCompliance}
        isRedoing={isRedoing}
        onBaselineRunChange={setQualityBaselineRunId}
        onExportCompliance={handleExportCompliance}
        onRedo={handleRedo}
        onViewChange={setActiveView}
        qualityBaselineRunId={qualityBaselineRunId}
        qualityComparison={qualityComparison}
        redoLimitReached={redoLimitReached}
        reflectionItems={reflectionItems}
        reportSources={reportSources}
        runHistory={runHistory}
      />
    </section>
  );
}
