import { RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { EmptyState, LoadingState, PageHeader } from "../components/ui";
import { ActiveView } from "../features/workbench/ActiveView";
import { ContextInspector } from "../features/workbench/ContextInspector";
import { ProjectRail } from "../features/workbench/ProjectRail";
import { useEnterpriseWorkbenchData } from "../features/workbench/useEnterpriseWorkbenchData";
import { useWorkbenchInspector } from "../features/workbench/useWorkbenchInspector";
import { ViewSwitcher } from "../features/workbench/ViewSwitcher";
import { WorkbenchStatusStrip } from "../features/workbench/WorkbenchStatusStrip";
import { workbenchViewRoutes } from "../features/workbench/routes";
import type { EnterpriseView } from "../features/workbench/types";

export function EnterpriseWorkbench({ initialView = "overview" }: { initialView?: EnterpriseView }) {
  const navigate = useNavigate();
  const {
    activeView,
    competitorById,
    data,
    error,
    evidenceById,
    filteredEvidence,
    gapFillResult,
    handleEvidenceQuality,
    handleExport,
    handleGapFill,
    handleReportAction,
    isFillingGaps,
    isLoadingProject,
    isLoadingProjects,
    isReportActionPending,
    lastExport,
    projects,
    query,
    refreshProjects,
    releaseGate,
    reportSources,
    selectedProject,
    selectedProjectId,
    selectedVersion,
    selectedVersionId,
    setActiveView,
    setQuery,
    setSelectedProjectId,
    setSelectedVersionId,
  } = useEnterpriseWorkbenchData(initialView);
  const {
    inspectEvidence,
    inspectReport,
    selectedClaim,
    selectedEvidence,
    selectedTab,
    setSelectedTab,
  } = useWorkbenchInspector({ data, selectedVersion });

  function handleViewChange(view: EnterpriseView) {
    setActiveView(view);
    navigate(workbenchViewRoutes[view]);
  }

  return (
    <section className="work-surface enterprise-workbench">
      <PageHeader
        eyebrow="Enterprise workspace"
        title={selectedProject?.name ?? "Enterprise workbench"}
        meta={
          selectedProject
            ? `${selectedProject.topic} / ${selectedProject.competitor_layer} / ${data.versions.length} report version(s)`
            : "Projects, evidence, reports, governance, and review operations."
        }
        actions={
          <button className="icon-text-button" type="button" onClick={refreshProjects}>
            <RefreshCw size={16} aria-hidden />
            Refresh
          </button>
        }
      />

      {error ? <p className="error-line">{error}</p> : null}

      <WorkbenchStatusStrip
        competitorCount={data.competitors.length}
        evidence={data.evidence}
        project={selectedProject}
        releaseGate={releaseGate}
        report={selectedVersion}
      />

      <div className="enterprise-shell-grid">
        <ProjectRail
          isLoading={isLoadingProjects}
          notifications={data.notifications}
          onSelect={setSelectedProjectId}
          projects={projects}
          selectedProjectId={selectedProjectId}
        />

        <div className="enterprise-work-stack">
          <main className="enterprise-work-area">
            <ViewSwitcher activeView={activeView} onChange={handleViewChange} />

            {isLoadingProject ? <LoadingState label="Loading project workspace" /> : null}
            {!isLoadingProject && !selectedProject ? (
              <EmptyState title="No project selected">Run an analysis first, then return to the workbench.</EmptyState>
            ) : null}
            {!isLoadingProject && selectedProject ? (
              <ActiveView
                activeView={activeView}
                competitorById={competitorById}
                data={data}
                evidenceById={evidenceById}
                filteredEvidence={filteredEvidence}
                gapFillResult={gapFillResult}
                isFillingGaps={isFillingGaps}
                isReportActionPending={isReportActionPending}
                lastExport={lastExport}
                onEvidenceQuality={handleEvidenceQuality}
                onExport={handleExport}
                onFillGaps={handleGapFill}
                onReportAction={handleReportAction}
                onSelectEvidence={inspectEvidence}
                onSelectReport={inspectReport}
                query={query}
                releaseGate={releaseGate}
                reportSources={reportSources}
                selectedEvidenceId={selectedEvidence?.id ?? null}
                selectedProject={selectedProject}
                selectedVersion={selectedVersion}
                selectedVersionId={selectedVersionId}
                setQuery={setQuery}
                setSelectedVersionId={setSelectedVersionId}
              />
            ) : null}
          </main>

          <ContextInspector
            claim={selectedClaim}
            evidence={selectedEvidence}
            report={selectedVersion}
            selectedTab={selectedTab}
            setSelectedTab={setSelectedTab}
          />
        </div>
      </div>
    </section>
  );
}
