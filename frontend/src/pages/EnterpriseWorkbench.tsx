import { MoreHorizontal, Plus, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { ActionButton } from "../components/interaction/ActionButton";
import { ActionLink } from "../components/interaction/ActionLink";
import { useTranslation } from "../stores/i18n";
import { ProjectHeader, WorkspaceLayout } from "../components/product-shell";
import { EmptyState, LoadingState } from "../components/ui";
import { ActiveView } from "../features/workbench/ActiveView";
import { ContextInspector } from "../features/workbench/ContextInspector";
import { formatDate } from "../features/workbench/format";
import { ProjectRail } from "../features/workbench/ProjectRail";
import { useEnterpriseWorkbenchData } from "../features/workbench/useEnterpriseWorkbenchData";
import { useWorkbenchInspector } from "../features/workbench/useWorkbenchInspector";
import { ViewSwitcher } from "../features/workbench/ViewSwitcher";
import { WorkbenchStatusStrip } from "../features/workbench/WorkbenchStatusStrip";
import { workbenchViewRoutes } from "../features/workbench/routes";
import type { EnterpriseView } from "../features/workbench/types";

export function EnterpriseWorkbench({ initialView = "overview" }: { initialView?: EnterpriseView }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
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
    inspectClaim,
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

  const projectMeta = selectedProject
    ? `${selectedProject.topic} / ${selectedProject.competitor_layer.toUpperCase()} / ${data.competitors.length} competitors / updated ${formatDate(selectedProject.updated_at)}`
    : "Projects, evidence, reports, governance, and review operations.";

  return (
    <WorkspaceLayout
      className="enterprise-workbench"
      error={error ? <p className="error-line">{error}</p> : null}
      header={
        <ProjectHeader
          title={selectedProject?.name ?? "Enterprise workbench"}
          meta={projectMeta}
          status={selectedProject ? "Active" : "No project"}
          actions={
            <>
              <ActionLink
                className="primary-action"
                to="/"
                authenticity={{
                  actionId: 'workbench.new-run.navigate',
                  kind: 'route',
                  description: 'navigates to new research run page'
                }}
              >
                <Plus size={16} aria-hidden />
                {t('workbench.newRun')}
              </ActionLink>
              <ActionButton
                className="icon-button"
                onClick={refreshProjects}
                aria-label={t('workbench.refresh')}
                authenticity={{
                  actionId: 'workbench.refresh',
                  kind: 'local',
                  description: 'refreshes project list'
                }}
              >
                <RefreshCw size={16} aria-hidden />
              </ActionButton>
              <ActionButton
                className="icon-button"
                aria-label={t('workbench.moreActions')}
                authenticity={{
                  actionId: 'workbench.more-actions.disabled',
                  kind: 'disabled',
                  description: 'workspace action menu not available in demo'
                }}
                disabled
                disabledReason={t('workbench.moreActions.disabled')}
              >
                <MoreHorizontal size={16} aria-hidden />
              </ActionButton>
            </>
          }
        />
      }
      statusStrip={
        <WorkbenchStatusStrip
          competitorCount={data.competitors.length}
          evidence={data.evidence}
          project={selectedProject}
          releaseGate={releaseGate}
          report={selectedVersion}
        />
      }
      projectRail={
        <ProjectRail
          isLoading={isLoadingProjects}
          notifications={data.notifications}
          onSelect={setSelectedProjectId}
          projects={projects}
          selectedProjectId={selectedProjectId}
        />
      }
      inspector={
        <ContextInspector
          claim={selectedClaim}
          evidence={selectedEvidence}
          report={selectedVersion}
          selectedTab={selectedTab}
          setSelectedTab={setSelectedTab}
        />
      }
    >
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
          onSelectClaim={inspectClaim}
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
    </WorkspaceLayout>
  );
}
