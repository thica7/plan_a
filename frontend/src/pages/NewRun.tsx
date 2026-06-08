import type { FormEvent } from "react";
import { CompetitorsSection } from "../features/new-run/CompetitorsSection";
import { DimensionsSection } from "../features/new-run/DimensionsSection";
import { LensSection } from "../features/new-run/LensSection";
import { RunLaunchRail } from "../features/new-run/RunLaunchRail";
import { ScopeSection } from "../features/new-run/ScopeSection";
import { useNewRunBuilder } from "../features/new-run/useNewRunBuilder";

export function NewRun() {
  const builder = useNewRunBuilder();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    await builder.submitRun();
  }

  return (
    <section className="work-surface new-run-page">
      <header className="page-header page-header-split">
        <div>
          <h1>New analysis run</h1>
          <p>Configure the market scope, research lens, execution mode, and quality controls before launch.</p>
        </div>
        <div className="header-stat">
          <strong>{builder.selected.length}</strong>
          <span>dimensions selected</span>
        </div>
      </header>

      <form className="run-builder" onSubmit={handleSubmit}>
        <div className="run-builder-main">
          <ScopeSection
            onPreset={builder.applyStarterPreset}
            scenarioId={builder.scenarioId}
            setTopic={builder.setTopic}
            topic={builder.topic}
          />
          <CompetitorsSection
            competitorMode={builder.competitorMode}
            competitors={builder.competitors}
            setCompetitorMode={builder.setCompetitorMode}
            setCompetitors={builder.setCompetitors}
            updateManualMode={builder.updateManualMode}
          />
          <LensSection
            applyScenario={builder.applyScenario}
            dynamicScenarioSelected={builder.dynamicScenarioSelected}
            scenarioId={builder.scenarioId}
            scenarioPacks={builder.scenarioPacks}
            selected={builder.selected}
            selectedLayer={builder.selectedLayer}
            selectedScenario={builder.selectedScenario}
            setScenarioId={builder.setScenarioId}
            updateSelectedLayer={builder.updateSelectedLayer}
          />
          <DimensionsSection
            lockedDimensions={builder.lockedDimensions}
            selected={builder.selected}
            selectedScenario={builder.selectedScenario}
            skills={builder.skills}
            toggleDimension={builder.toggleDimension}
          />
        </div>

        <RunLaunchRail
          autoRedoWarn={builder.autoRedoWarn}
          competitorList={builder.competitorList}
          competitorMode={builder.competitorMode}
          dynamicScenarioSelected={builder.dynamicScenarioSelected}
          error={builder.error}
          executionMode={builder.executionMode}
          hitlEnabled={builder.hitlEnabled}
          isSubmitting={builder.isSubmitting}
          quotaDecision={builder.quotaDecision}
          runBlockedByQuota={builder.runBlockedByQuota}
          runtime={builder.runtime}
          selected={builder.selected}
          selectedLayer={builder.selectedLayer}
          selectedScenario={builder.selectedScenario}
          setAutoRedoWarn={builder.setAutoRedoWarn}
          setExecutionMode={builder.setExecutionMode}
          toggleHitl={builder.toggleHitl}
        />
      </form>
    </section>
  );
}
