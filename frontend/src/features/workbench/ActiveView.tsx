import type {
  ArtifactRecord,
  CompetitorRecord,
  EvidenceGapFillResult,
  EvidenceQualityLabel,
  EvidenceRecord,
  ProjectRecord,
  ReportReleaseGate,
  ReportVersionRecord,
} from "../../api/types";
import type { ReportSourceBundle } from "../report/sourceBundle";
import { ActivityCenter } from "./ActivityCenter";
import { CompetitorLibrary } from "./CompetitorLibrary";
import { EvidenceCenter } from "./EvidenceCenter";
import { GovernanceCenter } from "./GovernanceCenter";
import { OverviewDashboard } from "./OverviewDashboard";
import { ReportStudio } from "./ReportStudio";
import type { ReportAction, ReportExportFormat } from "./reportOperations";
import type { EnterpriseView, ProjectData } from "./types";

interface ActiveViewProps {
  activeView: EnterpriseView;
  competitorById: Map<string, CompetitorRecord>;
  data: ProjectData;
  evidenceById: Map<string, EvidenceRecord>;
  filteredEvidence: EvidenceRecord[];
  gapFillResult: EvidenceGapFillResult | null;
  isFillingGaps: boolean;
  isReportActionPending: boolean;
  lastExport: ArtifactRecord | null;
  onEvidenceQuality: (evidenceId: string, qualityLabel: EvidenceQualityLabel) => void;
  onExport: (format: ReportExportFormat) => void;
  onFillGaps: () => void;
  onReportAction: (action: ReportAction) => void;
  onSelectEvidence: (evidence: EvidenceRecord) => void;
  onSelectReport: (report: ReportVersionRecord) => void;
  query: string;
  releaseGate: ReportReleaseGate | null;
  reportSources: ReportSourceBundle;
  selectedEvidenceId: string | null;
  selectedProject: ProjectRecord;
  selectedVersion: ReportVersionRecord | null;
  selectedVersionId: string | null;
  setQuery: (query: string) => void;
  setSelectedVersionId: (versionId: string) => void;
}

export function ActiveView({
  activeView,
  competitorById,
  data,
  evidenceById,
  filteredEvidence,
  gapFillResult,
  isFillingGaps,
  isReportActionPending,
  lastExport,
  onEvidenceQuality,
  onExport,
  onFillGaps,
  onReportAction,
  onSelectEvidence,
  onSelectReport,
  query,
  releaseGate,
  reportSources,
  selectedEvidenceId,
  selectedProject,
  selectedVersion,
  selectedVersionId,
  setQuery,
  setSelectedVersionId,
}: ActiveViewProps) {
  if (activeView === "evidence") {
    return (
      <EvidenceCenter
        competitorById={competitorById}
        evidence={filteredEvidence}
        evidenceGaps={data.evidenceGaps}
        gapFillResult={gapFillResult}
        isFillingGaps={isFillingGaps}
        onEvidenceQuality={onEvidenceQuality}
        onFillGaps={onFillGaps}
        onSelectEvidence={onSelectEvidence}
        query={query}
        selectedEvidenceId={selectedEvidenceId}
        setQuery={setQuery}
      />
    );
  }

  if (activeView === "reports") {
    return (
      <ReportStudio
        evidenceById={evidenceById}
        isPending={isReportActionPending}
        lastExport={lastExport}
        onExport={onExport}
        onSelectEvidence={onSelectEvidence}
        onSelectReport={onSelectReport}
        onReportAction={onReportAction}
        releaseGate={releaseGate}
        reportSources={reportSources}
        selectedVersion={selectedVersion}
        selectedVersionId={selectedVersionId}
        setSelectedVersionId={setSelectedVersionId}
        versions={data.versions}
      />
    );
  }

  if (activeView === "competitors") {
    return (
      <CompetitorLibrary
        competitors={data.competitors}
        evidence={data.evidence}
        scores={data.competitorScores}
      />
    );
  }

  if (activeView === "governance") {
    return (
      <GovernanceCenter
        auditLogs={data.auditLogs}
        matrix={data.matrix}
        modelPolicy={data.modelPolicy}
        modelRoute={data.modelRoute}
        quota={data.quota}
        registry={data.registry}
        retention={data.retention}
        usage={data.usage}
      />
    );
  }

  if (activeView === "activity") {
    return (
      <ActivityCenter
        auditLogs={data.auditLogs}
        evalOps={data.evalOps}
        notifications={data.notifications}
        project={selectedProject}
      />
    );
  }

  return (
    <OverviewDashboard
      auditLogs={data.auditLogs}
      claimValidation={data.claimValidation}
      claims={data.claims}
      competitorScores={data.competitorScores}
      competitors={data.competitors}
      evidence={data.evidence}
      evidenceGaps={data.evidenceGaps}
      evalOps={data.evalOps}
      matrix={data.matrix}
      qaEvaluation={data.qaEvaluation}
      readiness={data.readiness}
      redTeam={data.redTeam}
      selectedVersion={selectedVersion}
    />
  );
}
