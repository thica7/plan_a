import type { FormEvent } from "react";
import { CompetitorsSection } from "../features/new-run/CompetitorsSection";
import { CollaborationSection } from "../features/new-run/CollaborationSection";
import { DepthSection } from "../features/new-run/DepthSection";
import { DimensionsSection } from "../features/new-run/DimensionsSection";
import { scenarioPacksForProduct } from "../features/new-run/dimensions";
import { ExecutionModePanel } from "../features/new-run/ExecutionModePanel";
import { LensSection } from "../features/new-run/LensSection";
import { OutputLanguageSection } from "../features/new-run/OutputLanguageSection";
import { RunReadinessRail } from "../features/new-run/RunReadinessRail";
import { ResearchDepthSection } from "../features/new-run/ResearchDepthSection";
import { ScopeSection } from "../features/new-run/ScopeSection";
import { useNewRunBuilder } from "../features/new-run/useNewRunBuilder";
import { useTranslation } from "../stores/i18n";

export function NewRun() {
  const { t } = useTranslation();
  const builder = useNewRunBuilder();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    await builder.submitRun();
  }

  return (
    <section className="work-surface new-run-page">
      <header className="page-header new-run-header">
        <div>
          <h1>{t('newRun.title')}</h1>
          <p>{t('newRun.description')}</p>
        </div>
      </header>

      <form className="run-builder" onSubmit={handleSubmit}>
        <div className="run-builder-main" aria-label={t('newRun.builder')}>
          <ScopeSection
            setTopic={builder.setTopic}
            topic={builder.topic}
            targetName={builder.targetName}
            setTargetName={builder.setTargetName}
            targetUrl={builder.targetUrl}
            setTargetUrl={builder.setTargetUrl}
            productCategory={builder.productCategory}
            setProductCategory={builder.setProductCategory}
            productAudience={builder.productAudience}
            setProductAudience={builder.setProductAudience}
            productUseCases={builder.productUseCases}
            setProductUseCases={builder.setProductUseCases}
            productMarket={builder.productMarket}
            setProductMarket={builder.setProductMarket}
            decisionQuestion={builder.decisionQuestion}
            setDecisionQuestion={builder.setDecisionQuestion}
            primaryJob={builder.primaryJob}
            setPrimaryJob={builder.setPrimaryJob}
            successMetric={builder.successMetric}
            setSuccessMetric={builder.setSuccessMetric}
          />
          <LensSection
            applyScenario={builder.applyScenario}
            dynamicScenarioSelected={builder.dynamicScenarioSelected}
            scenarioId={builder.scenarioId}
            scenarioPacks={scenarioPacksForProduct(builder.scenarioPacks, builder.productCategory)}
            selected={builder.selected}
            selectedLayer={builder.selectedLayer}
            selectedScenario={builder.selectedScenario}
            setScenarioId={builder.setScenarioId}
          />
          <CompetitorsSection
            competitorMode={builder.competitorMode}
            competitors={builder.competitors}
            setCompetitorMode={builder.setCompetitorMode}
            setCompetitors={builder.setCompetitors}
            updateManualMode={builder.updateManualMode}
          />
          <DimensionsSection
            lockedDimensions={builder.lockedDimensions}
            selected={builder.selected}
            selectedScenario={builder.selectedScenario}
            skills={builder.skills}
            toggleDimension={builder.toggleDimension}
          />
          <DepthSection
            selectedLayer={builder.selectedLayer}
            updateSelectedLayer={builder.updateSelectedLayer}
          />
          <ResearchDepthSection
            researchDepth={builder.researchDepth}
            setResearchDepth={builder.setResearchDepth}
          />
          <OutputLanguageSection
            outputLanguage={builder.outputLanguage}
            setOutputLanguage={builder.setOutputLanguage}
          />
          <ExecutionModePanel
            executionMode={builder.executionMode}
            setExecutionMode={builder.setExecutionMode}
          />
          <CollaborationSection
            collaborationMode={builder.collaborationMode}
            setCollaborationMode={builder.setCollaborationMode}
          />
          <details className="advanced-options-row">
            <summary>{t('newRun.advancedOptions')}</summary>
            <p>{t('newRun.advancedDesc')}</p>
          </details>
        </div>

        <RunReadinessRail
          autoRedoWarn={builder.autoRedoWarn}
          competitorList={builder.competitorList}
          competitorMode={builder.competitorMode}
          collaborationMode={builder.collaborationMode}
          dynamicScenarioSelected={builder.dynamicScenarioSelected}
          error={builder.error}
          executionMode={builder.executionMode}
          manualScopeError={builder.manualScopeError}
          isSubmitting={builder.isSubmitting}
          quotaDecision={builder.quotaDecision}
          runBlockedByQuota={builder.runBlockedByQuota}
          runtime={builder.runtime}
          targetName={builder.targetName}
          selected={builder.selected}
          selectedLayer={builder.selectedLayer}
          researchDepth={builder.researchDepth}
          selectedScenario={builder.selectedScenario}
          setAutoRedoWarn={builder.setAutoRedoWarn}
        />
      </form>
    </section>
  );
}
