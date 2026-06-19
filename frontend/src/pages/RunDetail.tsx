import { AlertTriangle, Loader2 } from "lucide-react";
import { PlanReviewModal } from "../features/hitl/PlanReviewModal";
import { QaReviewModal } from "../features/hitl/QaReviewModal";
import { RunDetailContent } from "../features/run-detail/RunDetailContent";
import { RunDetailHeader } from "../features/run-detail/RunDetailHeader";
import { RunDetailTabs } from "../features/run-detail/RunDetailTabs";
import { RunSummaryStrip } from "../features/run-detail/RunSummaryStrip";
import { useRunDetailController } from "../features/run-detail/useRunDetailController";
import { useTranslation } from "../stores/i18n";

export function RunDetail() {
  const { t } = useTranslation();
  const {
    activeView,
    canApplyPlanReviewChanges,
    citedClaimRate,
    complianceExport,
    complianceReport,
    decisionReplay,
    detail,
    error,
    events,
    activeHitlDecision,
    handleExportCompliance,
    handleAddCompetitor,
    handleCompetitorDecisionChange,
    handleCompetitorNameChange,
    handleCompetitorNoteChange,
    handleDeleteCompetitor,
    handleHitl,
    handleRedo,
    interruptStage,
    isExportingCompliance,
    isHitlSubmitting,
    isRedoing,
    latestInterrupt,
    planDimensions,
    competitorRows,
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
    traceSpans,
    agentMessages,
    toolCallMessages,
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
          <p>{t('runDetail.loading')}</p>
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
            canApplyChanges={canApplyPlanReviewChanges}
            competitorRows={competitorRows}
            dimensions={planDimensions}
            message={latestInterrupt.message}
            onAddCompetitor={handleAddCompetitor}
            onAccept={() => handleHitl("accept")}
            onApply={() => handleHitl("modify_plan")}
            onCompetitorDecisionChange={handleCompetitorDecisionChange}
            onCompetitorNameChange={handleCompetitorNameChange}
            onCompetitorNoteChange={handleCompetitorNoteChange}
            onDeleteCompetitor={handleDeleteCompetitor}
            onDimensionsChange={setPlanDimensions}
          />
        ) : (
          <QaReviewModal
            activeDecision={
              activeHitlDecision === "accept" ||
              activeHitlDecision === "force_pass" ||
              activeHitlDecision === "redo"
                ? activeHitlDecision
                : null
            }
            isSubmitting={isHitlSubmitting}
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
        traceSpans={traceSpans}
        agentMessages={agentMessages}
        toolCallMessages={toolCallMessages}
      />
    </section>
  );
}
