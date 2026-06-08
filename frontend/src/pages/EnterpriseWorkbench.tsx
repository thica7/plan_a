import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Bell,
  CalendarClock,
  CheckCircle2,
  Database,
  Download,
  ExternalLink,
  FileText,
  Gauge,
  GitCompare,
  Layers,
  RefreshCw,
  Search,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import {
  approveReportWorkflow,
  exportReportVersion,
  fillProjectEvidenceGaps,
  getEnterpriseEvalOps,
  getModelPolicy,
  getModelRouteDecision,
  getProjectBusinessPlan,
  getProjectClaimValidation,
  getProjectCompetitorScores,
  getProjectEvidenceGaps,
  getProjectQAEvaluation,
  getProjectQualityMatrix,
  getProjectReadinessScore,
  getProjectRedTeam,
  getReportReleaseGate,
  getWorkspaceQuotaDecision,
  getWorkspaceRetentionReport,
  getWorkspaceUsage,
  listArtifacts,
  listEnterpriseAuditLogs,
  listEnterpriseCompetitors,
  listEnterpriseNotifications,
  listEnterpriseProjects,
  listProjectClaims,
  listProjectEvidence,
  listProjectReportVersions,
  listSourceRegistry,
  publishReportVersion,
  rejectReportWorkflow,
  startReportApprovalWorkflow,
  updateEvidenceQuality,
} from "../api/client";
import type {
  ArtifactRecord,
  AuditLogRecord,
  BusinessIntelPlan,
  BusinessQAEvaluation,
  ClaimRecord,
  ClaimValidationReport,
  CompetitorRecord,
  CompetitorScoreReport,
  DataRetentionReport,
  EvidenceGapFillResult,
  EvidenceGapReport,
  EvidenceQualityLabel,
  EvidenceRecord,
  EvalOpsReport,
  ModelPolicyReport,
  ModelRouteDecision,
  NotificationRecord,
  ProjectReadinessScore,
  ProjectRecord,
  QualityAgentMatrix,
  RedTeamReport,
  ReportReleaseGate,
  ReportVersionRecord,
  SourceRegistryRecord,
  WorkspaceQuotaDecision,
  WorkspaceUsageSummary,
} from "../api/types";
import { EmptyState, LoadingState, MetricCard, PageHeader, Panel, StatusPill } from "../components/ui";
import { ReportView } from "../features/report/ReportView";
import { buildReportSourceBundle } from "../features/report/sourceBundle";
import { formatDate, formatPercent, reportStatusTone } from "../features/workbench/format";
import { ProjectRail } from "../features/workbench/ProjectRail";
import { ViewSwitcher } from "../features/workbench/ViewSwitcher";
import { emptyProjectData, type EnterpriseView, type ProjectData } from "../features/workbench/types";

export function EnterpriseWorkbench({ initialView = "overview" }: { initialView?: EnterpriseView }) {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<EnterpriseView>(initialView);
  const [data, setData] = useState<ProjectData>(emptyProjectData);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [releaseGate, setReleaseGate] = useState<ReportReleaseGate | null>(null);
  const [gapFillResult, setGapFillResult] = useState<EvidenceGapFillResult | null>(null);
  const [query, setQuery] = useState("");
  const [isLoadingProjects, setLoadingProjects] = useState(true);
  const [isLoadingProject, setLoadingProject] = useState(false);
  const [isFillingGaps, setFillingGaps] = useState(false);
  const [isReportActionPending, setReportActionPending] = useState(false);
  const [lastExport, setLastExport] = useState<ArtifactRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setActiveView(initialView), [initialView]);

  useEffect(() => {
    refreshProjects();
  }, []);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );

  const selectedVersion = useMemo(
    () => data.versions.find((version) => version.id === selectedVersionId) ?? data.versions[0] ?? null,
    [data.versions, selectedVersionId],
  );

  const competitorById = useMemo(
    () => new Map(data.competitors.map((competitor) => [competitor.id, competitor])),
    [data.competitors],
  );

  const evidenceById = useMemo(
    () => new Map(data.evidence.map((item) => [item.id, item])),
    [data.evidence],
  );

  const reportSources = useMemo(
    () =>
      buildReportSourceBundle(data.evidence, {
        competitorById,
        scopedEvidenceIds: selectedVersion?.evidence_ids ?? null,
      }),
    [competitorById, data.evidence, selectedVersion?.evidence_ids],
  );

  const filteredEvidence = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return data.evidence;
    return data.evidence.filter((item) => {
      const competitor = competitorById.get(item.competitor_id)?.name ?? item.competitor_id;
      return [item.title, item.dimension, item.source_type, item.snippet, competitor]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [competitorById, data.evidence, query]);

  useEffect(() => {
    if (!selectedProject) {
      setData(emptyProjectData);
      setSelectedVersionId(null);
      setReleaseGate(null);
      return;
    }
    void refreshProject(selectedProject);
  }, [selectedProject?.id]);

  useEffect(() => {
    if (!selectedVersion) {
      setReleaseGate(null);
      return;
    }
    let active = true;
    setLastExport(null);
    getReportReleaseGate(selectedVersion.id)
      .then((gate) => {
        if (active) setReleaseGate(gate);
      })
      .catch(() => {
        if (active) setReleaseGate(null);
      });
    return () => {
      active = false;
    };
  }, [selectedVersion?.id]);

  function refreshProjects() {
    setLoadingProjects(true);
    setError(null);
    Promise.all([listEnterpriseProjects(), listEnterpriseNotifications({ limit: 8 })])
      .then(([items, notifications]) => {
        setProjects(items);
        setData((current) => ({ ...current, notifications }));
        setSelectedProjectId((current) => current ?? items[0]?.id ?? null);
      })
      .catch((err: Error) => {
        setError(err.message);
        setProjects([]);
      })
      .finally(() => setLoadingProjects(false));
  }

  async function refreshProject(project: ProjectRecord) {
    setLoadingProject(true);
    setError(null);
    setGapFillResult(null);
    try {
      const [competitors, artifacts, evidence, claims, versions, notifications] = await Promise.all([
        listEnterpriseCompetitors({ projectId: project.id }),
        listArtifacts({ projectId: project.id }),
        listProjectEvidence(project.id),
        listProjectClaims(project.id),
        listProjectReportVersions(project.id),
        listEnterpriseNotifications({ workspaceId: project.workspace_id, limit: 8 }).catch(() => []),
      ]);
      setData({
        ...emptyProjectData,
        artifacts,
        claims,
        competitors,
        evidence,
        notifications,
        versions,
      });
      setSelectedVersionId((current) =>
        current && versions.some((version) => version.id === current) ? current : versions[0]?.id ?? null,
      );
      setLoadingProject(false);
      void refreshProjectSignals(project);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load enterprise project");
      setData(emptyProjectData);
      setSelectedVersionId(null);
      setLoadingProject(false);
    }
  }

  async function refreshProjectSignals(project: ProjectRecord) {
    try {
      const [
        businessPlan,
        qaEvaluation,
        claimValidation,
        readiness,
        competitorScores,
        evidenceGaps,
        redTeam,
        matrix,
        evalOps,
        registry,
        modelPolicy,
        modelRoute,
        usage,
        quota,
        retention,
        auditLogs,
      ] = await Promise.all([
        getProjectBusinessPlan(project.id).catch(() => null),
        getProjectQAEvaluation(project.id).catch(() => null),
        getProjectClaimValidation(project.id).catch(() => null),
        getProjectReadinessScore(project.id).catch(() => null),
        getProjectCompetitorScores(project.id).catch(() => null),
        getProjectEvidenceGaps(project.id).catch(() => null),
        getProjectRedTeam(project.id).catch(() => null),
        getProjectQualityMatrix(project.id).catch(() => null),
        getEnterpriseEvalOps({ projectId: project.id }).catch(() => null),
        listSourceRegistry(project.workspace_id).catch(() => []),
        getModelPolicy().catch(() => null),
        getModelRouteDecision().catch(() => null),
        getWorkspaceUsage(project.workspace_id).catch(() => null),
        getWorkspaceQuotaDecision(project.workspace_id).catch(() => null),
        getWorkspaceRetentionReport(project.workspace_id).catch(() => null),
        listEnterpriseAuditLogs({ workspaceId: project.workspace_id, limit: 50 }).catch(() => []),
      ]);
      setData((current) => ({
        ...current,
        auditLogs,
        businessPlan,
        claimValidation,
        competitorScores,
        evidenceGaps,
        evalOps,
        matrix,
        modelPolicy,
        modelRoute,
        qaEvaluation,
        readiness,
        redTeam,
        registry,
        retention,
        usage,
        quota,
      }));
    } catch (err) {
      console.warn("Unable to refresh project signals", err);
    } finally {
      setLoadingProject(false);
    }
  }

  async function handleGapFill() {
    if (!selectedProject) return;
    setFillingGaps(true);
    setError(null);
    try {
      const result = await fillProjectEvidenceGaps(selectedProject.id);
      setGapFillResult(result);
      await refreshProject(selectedProject);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to fill evidence gaps");
    } finally {
      setFillingGaps(false);
    }
  }

  async function handleEvidenceQuality(evidenceId: string, qualityLabel: EvidenceQualityLabel) {
    try {
      const result = await updateEvidenceQuality(evidenceId, { quality_label: qualityLabel });
      setData((current) => ({
        ...current,
        evidence: current.evidence.map((item) => (item.id === evidenceId ? result.evidence : item)),
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update evidence quality");
    }
  }

  async function handleReportAction(action: "start_review" | "approve" | "reject" | "publish") {
    if (!selectedVersion) return;
    setReportActionPending(true);
    setError(null);
    try {
      if (action === "start_review") {
        await startReportApprovalWorkflow({
          report_version_id: selectedVersion.id,
          requested_by: "ui-reviewer",
          approver_ids: ["ui-reviewer"],
          timeout_seconds: 3600,
        });
      } else if (action === "approve") {
        await approveReportWorkflow(selectedVersion.id, {
          approver_id: "ui-reviewer",
          note: "Approved in report studio",
        });
      } else if (action === "reject") {
        await rejectReportWorkflow(selectedVersion.id, {
          approver_id: "ui-reviewer",
          note: "Rejected in report studio",
        });
      } else {
        await publishReportVersion(selectedVersion.id);
      }
      if (selectedProject) await refreshProject(selectedProject);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Report action failed");
    } finally {
      setReportActionPending(false);
    }
  }

  async function handleExport(format: "markdown" | "html" | "csv") {
    if (!selectedVersion) return;
    setReportActionPending(true);
    setError(null);
    try {
      const result = await exportReportVersion(selectedVersion.id, format);
      setLastExport(result.artifact);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to export report");
    } finally {
      setReportActionPending(false);
    }
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

      <div className="enterprise-shell-grid">
        <ProjectRail
          isLoading={isLoadingProjects}
          notifications={data.notifications}
          onSelect={setSelectedProjectId}
          projects={projects}
          selectedProjectId={selectedProjectId}
        />

        <main className="enterprise-work-area">
          <ViewSwitcher activeView={activeView} onChange={setActiveView} />

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
              query={query}
              releaseGate={releaseGate}
              reportSources={reportSources}
              selectedProject={selectedProject}
              selectedVersion={selectedVersion}
              selectedVersionId={selectedVersionId}
              setQuery={setQuery}
              setSelectedVersionId={setSelectedVersionId}
            />
          ) : null}
        </main>
      </div>
    </section>
  );
}

function ActiveView({
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
  query,
  releaseGate,
  reportSources,
  selectedProject,
  selectedVersion,
  selectedVersionId,
  setQuery,
  setSelectedVersionId,
}: {
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
  onExport: (format: "markdown" | "html" | "csv") => void;
  onFillGaps: () => void;
  onReportAction: (action: "start_review" | "approve" | "reject" | "publish") => void;
  query: string;
  releaseGate: ReportReleaseGate | null;
  reportSources: ReturnType<typeof buildReportSourceBundle>;
  selectedProject: ProjectRecord;
  selectedVersion: ReportVersionRecord | null;
  selectedVersionId: string | null;
  setQuery: (query: string) => void;
  setSelectedVersionId: (versionId: string) => void;
}) {
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
        query={query}
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
    <Overview
      claimValidation={data.claimValidation}
      claims={data.claims}
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

function Overview({
  claimValidation,
  claims,
  competitors,
  evidence,
  evidenceGaps,
  evalOps,
  matrix,
  qaEvaluation,
  readiness,
  redTeam,
  selectedVersion,
}: {
  claimValidation: ClaimValidationReport | null;
  claims: ClaimRecord[];
  competitors: CompetitorRecord[];
  evidence: EvidenceRecord[];
  evidenceGaps: EvidenceGapReport | null;
  evalOps: EvalOpsReport | null;
  matrix: QualityAgentMatrix | null;
  qaEvaluation: BusinessQAEvaluation | null;
  readiness: ProjectReadinessScore | null;
  redTeam: RedTeamReport | null;
  selectedVersion: ReportVersionRecord | null;
}) {
  const verifiedRate = evidence.length
    ? evidence.filter((item) => item.source_type.includes("verified") || item.reliability_score >= 0.72).length /
      evidence.length
    : 0;
  const acceptedRate = evidence.length
    ? evidence.filter((item) => item.quality_label === "accepted").length / evidence.length
    : 0;
  return (
    <div className="dashboard-grid">
      <Panel className="overview-hero" title="Project readiness">
        <div className="readiness-score">
          <strong>{readiness?.score ?? "n/a"}</strong>
          <span>{readiness?.risk_level ?? "not scored"}</span>
        </div>
        <p>{readiness?.summary ?? "Readiness is generated after project evidence and QA are projected."}</p>
        <div className="metric-grid compact">
          <MetricCard label="Competitors" value={competitors.length} />
          <MetricCard label="Evidence" value={evidence.length} />
          <MetricCard label="Claims" value={claims.length} />
          <MetricCard label="Verified rate" value={formatPercent(verifiedRate)} tone={verifiedRate >= 0.8 ? "good" : "warn"} />
          <MetricCard label="Accepted rate" value={formatPercent(acceptedRate)} tone={acceptedRate >= 0.6 ? "good" : "warn"} />
          <MetricCard label="QA blockers" value={qaEvaluation?.blocker_count ?? 0} tone={qaEvaluation?.blocker_count ? "warn" : "good"} />
        </div>
      </Panel>

      <Panel title="Quality chain" icon={<ShieldCheck size={16} aria-hidden />}>
        <div className="quality-chain">
          <QualityStep label="Evidence gaps" value={evidenceGaps?.gap_count ?? 0} ok={(evidenceGaps?.critical_count ?? 0) === 0} />
          <QualityStep label="Red team" value={redTeam?.finding_count ?? 0} ok={(redTeam?.high_severity_count ?? 0) === 0} />
          <QualityStep label="Claim validation" value={claimValidation?.issue_count ?? 0} ok={(claimValidation?.blocker_count ?? 0) === 0} />
          <QualityStep label="Agent matrix" value={matrix?.overall_score ?? "n/a"} ok={matrix?.status !== "blocker"} />
          <QualityStep label="EvalOps" value={evalOps?.regression_gate_status ?? "n/a"} ok={evalOps?.regression_gate_status === "pass"} />
        </div>
      </Panel>

      <Panel title="Active report" icon={<FileText size={16} aria-hidden />}>
        {selectedVersion ? (
          <div className="report-version-summary">
            <StatusPill tone={reportStatusTone(selectedVersion.status)}>{selectedVersion.status}</StatusPill>
            <strong>Version {selectedVersion.version_number}</strong>
            <span>{selectedVersion.report_md.length.toLocaleString()} characters</span>
            <span>{selectedVersion.claim_ids.length} claims / {selectedVersion.evidence_ids.length} evidence links</span>
            <time dateTime={selectedVersion.created_at}>{formatDate(selectedVersion.created_at)}</time>
          </div>
        ) : (
          <EmptyState title="No report version yet" />
        )}
      </Panel>

      <Panel title="Recommended next actions" icon={<CalendarClock size={16} aria-hidden />}>
        <div className="recommendation-list compact">
          {(readiness?.recommendations ?? []).slice(0, 5).map((item) => (
            <article className={`recommendation-card ${item.priority}`} key={item.id}>
              <strong>{item.title}</strong>
              <span>{item.action_type} / {item.target_type}</span>
              <p>{item.detail}</p>
            </article>
          ))}
          {!readiness?.recommendations.length ? <p className="muted-line">No readiness recommendations.</p> : null}
        </div>
      </Panel>
    </div>
  );
}

function EvidenceCenter({
  competitorById,
  evidence,
  evidenceGaps,
  gapFillResult,
  isFillingGaps,
  onEvidenceQuality,
  onFillGaps,
  query,
  setQuery,
}: {
  competitorById: Map<string, CompetitorRecord>;
  evidence: EvidenceRecord[];
  evidenceGaps: EvidenceGapReport | null;
  gapFillResult: EvidenceGapFillResult | null;
  isFillingGaps: boolean;
  onEvidenceQuality: (evidenceId: string, qualityLabel: EvidenceQualityLabel) => void;
  onFillGaps: () => void;
  query: string;
  setQuery: (query: string) => void;
}) {
  const verifiedCount = evidence.filter((item) => item.source_type.includes("verified") || item.reliability_score >= 0.72).length;
  return (
    <div className="workspace-two-column">
      <Panel
        className="evidence-table-panel"
        title="Evidence center"
        icon={<Database size={16} aria-hidden />}
        actions={
          <label className="search-control">
            <Search size={15} aria-hidden />
            <input
              aria-label="Search evidence"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search source, dimension, competitor"
            />
          </label>
        }
      >
        <div className="metric-grid compact">
          <MetricCard label="Visible evidence" value={evidence.length} />
          <MetricCard label="Verified-like" value={verifiedCount} tone={verifiedCount >= evidence.length * 0.7 ? "good" : "warn"} />
          <MetricCard label="Accepted" value={evidence.filter((item) => item.quality_label === "accepted").length} />
        </div>
        <div className="data-table evidence-table">
          <div className="data-table-head">
            <span>Source</span>
            <span>Competitor</span>
            <span>Dimension</span>
            <span>Quality</span>
            <span>Reliability</span>
          </div>
          {evidence.slice(0, 80).map((item) => (
            <article className="data-row" id={`evidence-${item.id}`} key={item.id}>
              <span>
                <strong>{item.title}</strong>
                <em>{item.url ?? item.raw_source_id}</em>
              </span>
              <span>{competitorById.get(item.competitor_id)?.name ?? item.competitor_id}</span>
              <span>{item.dimension}</span>
              <span>
                <select
                  aria-label={`Quality for ${item.title}`}
                  value={item.quality_label}
                  onChange={(event) => onEvidenceQuality(item.id, event.target.value as EvidenceQualityLabel)}
                >
                  <option value="unreviewed">unreviewed</option>
                  <option value="accepted">accepted</option>
                  <option value="rejected">rejected</option>
                  <option value="stale">stale</option>
                </select>
              </span>
              <span>{formatPercent(item.reliability_score)}</span>
            </article>
          ))}
        </div>
      </Panel>

      <Panel
        className="inspector-panel"
        title="Gap repair"
        icon={<GitCompare size={16} aria-hidden />}
        actions={
          <button className="icon-text-button" disabled={isFillingGaps} type="button" onClick={onFillGaps}>
            <RefreshCw size={15} aria-hidden />
            {isFillingGaps ? "Filling" : "Fill gaps"}
          </button>
        }
      >
        <div className="metric-grid compact">
          <MetricCard label="Gaps" value={evidenceGaps?.gap_count ?? 0} tone={evidenceGaps?.critical_count ? "warn" : "neutral"} />
          <MetricCard label="Critical" value={evidenceGaps?.critical_count ?? 0} tone={evidenceGaps?.critical_count ? "warn" : "good"} />
          <MetricCard label="High" value={evidenceGaps?.high_count ?? 0} />
        </div>
        {gapFillResult ? (
          <div className="gap-fill-result">
            <strong>{formatPercent(gapFillResult.gap_closure_rate)} closure</strong>
            <span>{gapFillResult.added_evidence_count} evidence added</span>
            <span>{gapFillResult.online_failure_count} online failures</span>
          </div>
        ) : null}
        <div className="recommendation-list compact">
          {(evidenceGaps?.gaps ?? []).slice(0, 8).map((gap) => (
            <article className={`recommendation-card ${gap.severity}`} key={gap.id}>
              <strong>{gap.dimension ?? gap.gap_type}</strong>
              <span>{gap.competitor_name ?? "project"} / {gap.gap_type}</span>
              <p>{gap.message}</p>
            </article>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function ReportStudio({
  evidenceById,
  isPending,
  lastExport,
  onExport,
  onReportAction,
  releaseGate,
  reportSources,
  selectedVersion,
  selectedVersionId,
  setSelectedVersionId,
  versions,
}: {
  evidenceById: Map<string, EvidenceRecord>;
  isPending: boolean;
  lastExport: ArtifactRecord | null;
  onExport: (format: "markdown" | "html" | "csv") => void;
  onReportAction: (action: "start_review" | "approve" | "reject" | "publish") => void;
  releaseGate: ReportReleaseGate | null;
  reportSources: ReturnType<typeof buildReportSourceBundle>;
  selectedVersion: ReportVersionRecord | null;
  selectedVersionId: string | null;
  setSelectedVersionId: (versionId: string) => void;
  versions: ReportVersionRecord[];
}) {
  return (
    <div className="report-studio-layout">
      <Panel className="version-rail" title="Versions">
        {versions.map((version) => (
          <button
            className={version.id === selectedVersionId ? "version-item active" : "version-item"}
            key={version.id}
            type="button"
            onClick={() => setSelectedVersionId(version.id)}
          >
            <strong>v{version.version_number}</strong>
            <span>{version.status}</span>
            <em>{formatDate(version.created_at)}</em>
          </button>
        ))}
        {versions.length === 0 ? <EmptyState title="No report versions" /> : null}
      </Panel>

      <Panel className="report-reader-panel" title="Report reader" icon={<FileText size={16} aria-hidden />}>
        {selectedVersion ? (
          <ReportView
            markdown={selectedVersion.report_md}
            sourceAliases={reportSources.aliases}
            sources={reportSources.sources}
          />
        ) : (
          <EmptyState title="Select a version" />
        )}
      </Panel>

      <aside className="report-inspector">
        <Panel title="Release gate" icon={<ShieldCheck size={16} aria-hidden />}>
          {releaseGate ? (
            <div className="release-gate-summary">
              <StatusPill tone={releaseGate.allowed ? "good" : "bad"}>
                {releaseGate.status}
              </StatusPill>
              <strong>{releaseGate.readiness.score} readiness</strong>
              <span>{releaseGate.blocker_count} blocker(s) / {releaseGate.warn_count} warning(s)</span>
              <div className="recommendation-list compact">
                {releaseGate.issues.slice(0, 4).map((issue) => (
                  <article className={`recommendation-card ${issue.severity}`} key={issue.id}>
                    <strong>{issue.rule_name}</strong>
                    <p>{issue.message}</p>
                  </article>
                ))}
              </div>
            </div>
          ) : (
            <LoadingState label="Loading release gate" />
          )}
        </Panel>

        <Panel title="Review controls" icon={<CheckCircle2 size={16} aria-hidden />}>
          <div className="action-grid">
            <button className="icon-text-button" disabled={isPending || !selectedVersion} onClick={() => onReportAction("start_review")} type="button">
              <ShieldCheck size={15} aria-hidden />
              Start review
            </button>
            <button className="icon-text-button" disabled={isPending || selectedVersion?.status !== "in_review"} onClick={() => onReportAction("approve")} type="button">
              <CheckCircle2 size={15} aria-hidden />
              Approve
            </button>
            <button className="icon-text-button" disabled={isPending || selectedVersion?.status !== "in_review"} onClick={() => onReportAction("reject")} type="button">
              <XCircle size={15} aria-hidden />
              Reject
            </button>
            <button className="icon-text-button" disabled={isPending || selectedVersion?.status !== "approved"} onClick={() => onReportAction("publish")} type="button">
              <FileText size={15} aria-hidden />
              Publish
            </button>
          </div>
          <div className="action-grid">
            {(["markdown", "html", "csv"] as const).map((format) => (
              <button className="icon-text-button" disabled={isPending || !selectedVersion} key={format} type="button" onClick={() => onExport(format)}>
                <Download size={15} aria-hidden />
                {format.toUpperCase()}
              </button>
            ))}
          </div>
          {lastExport ? <p className="muted-line">{lastExport.filename} / {lastExport.uri}</p> : null}
        </Panel>

        <Panel title="Evidence scope" icon={<Database size={16} aria-hidden />}>
          {selectedVersion ? (
            <div className="source-scope-list">
              {selectedVersion.evidence_ids.slice(0, 8).map((id) => {
                const evidence = evidenceById.get(id);
                return (
                  <a href={`#evidence-${id}`} key={id}>
                    <strong>{evidence?.title ?? id}</strong>
                    <span>{evidence?.dimension ?? "unknown"}</span>
                  </a>
                );
              })}
            </div>
          ) : null}
        </Panel>
      </aside>
    </div>
  );
}

function CompetitorLibrary({
  competitors,
  evidence,
  scores,
}: {
  competitors: CompetitorRecord[];
  evidence: EvidenceRecord[];
  scores: CompetitorScoreReport | null;
}) {
  const evidenceCounts = useMemo(() => {
    const counts = new Map<string, number>();
    evidence.forEach((item) => counts.set(item.competitor_id, (counts.get(item.competitor_id) ?? 0) + 1));
    return counts;
  }, [evidence]);
  const scoreByCompetitor = new Map(scores?.scores.map((score) => [score.competitor_id, score]) ?? []);
  return (
    <Panel title="Competitor library" icon={<Layers size={16} aria-hidden />}>
      <div className="competitor-catalog-grid">
        {competitors.map((competitor) => {
          const score = scoreByCompetitor.get(competitor.id);
          return (
            <article className="competitor-library-card" key={competitor.id}>
              <div>
                <strong>{competitor.name}</strong>
                <span>{competitor.layer} / {competitor.normalized_name}</span>
              </div>
              <div className="metric-grid compact">
                <MetricCard label="Score" value={score?.total_score ?? "n/a"} />
                <MetricCard label="Evidence" value={evidenceCounts.get(competitor.id) ?? 0} />
                <MetricCard label="Coverage" value={score ? formatPercent(score.coverage_score) : "n/a"} />
              </div>
              {competitor.homepage_url ? (
                <a href={competitor.homepage_url} target="_blank" rel="noreferrer">
                  <ExternalLink size={14} aria-hidden />
                  Homepage
                </a>
              ) : null}
              {score?.recommendation ? <p>{score.recommendation}</p> : null}
            </article>
          );
        })}
      </div>
    </Panel>
  );
}

function GovernanceCenter({
  auditLogs,
  matrix,
  modelPolicy,
  modelRoute,
  quota,
  registry,
  retention,
  usage,
}: {
  auditLogs: AuditLogRecord[];
  matrix: QualityAgentMatrix | null;
  modelPolicy: ModelPolicyReport | null;
  modelRoute: ModelRouteDecision | null;
  quota: WorkspaceQuotaDecision | null;
  registry: SourceRegistryRecord[];
  retention: DataRetentionReport | null;
  usage: WorkspaceUsageSummary | null;
}) {
  return (
    <div className="dashboard-grid">
      <Panel title="Runtime policy" icon={<ShieldCheck size={16} aria-hidden />}>
        <div className="metric-grid compact">
          <MetricCard label="Model policy" value={modelPolicy?.status ?? "n/a"} tone={modelPolicy?.status === "pass" ? "good" : "warn"} />
          <MetricCard label="Route" value={modelRoute?.status ?? "n/a"} />
          <MetricCard label="Agent matrix" value={matrix?.status ?? "n/a"} tone={matrix?.status === "blocker" ? "warn" : "good"} />
          <MetricCard label="Quota" value={quota?.status ?? "n/a"} tone={quota?.allowed === false ? "warn" : "good"} />
        </div>
        <div className="recommendation-list compact">
          {(modelPolicy?.findings ?? []).slice(0, 4).map((finding) => (
            <article className={`recommendation-card ${finding.severity}`} key={finding.id}>
              <strong>{finding.category}</strong>
              <p>{finding.message}</p>
            </article>
          ))}
        </div>
      </Panel>

      <Panel title="Workspace usage" icon={<Gauge size={16} aria-hidden />}>
        <div className="metric-grid compact">
          <MetricCard label="Runs" value={`${usage?.run_count ?? 0}/${usage?.monthly_run_quota ?? 0}`} />
          <MetricCard label="Tokens" value={formatPercent(usage?.token_usage_ratio ?? 0)} tone={(usage?.token_usage_ratio ?? 0) > 1 ? "warn" : "neutral"} />
          <MetricCard label="Cost" value={`$${(usage?.cost_estimate_usd ?? 0).toFixed(2)}`} />
          <MetricCard label="Retention" value={retention?.status ?? "n/a"} tone={retention?.status === "fail" ? "warn" : "good"} />
        </div>
      </Panel>

      <Panel title="Source registry" icon={<Database size={16} aria-hidden />}>
        <div className="data-table source-registry-table">
          <div className="data-table-head">
            <span>Domain</span>
            <span>Trust</span>
            <span>Robots</span>
            <span>Review</span>
          </div>
          {registry.slice(0, 40).map((source) => (
            <article className="data-row" key={source.id}>
              <span>
                <strong>{source.display_name}</strong>
                <em>{source.domain}</em>
              </span>
              <span>{source.trust_level}</span>
              <span>{source.robots_status}</span>
              <span>{source.policy_review_status}</span>
            </article>
          ))}
        </div>
      </Panel>

      <Panel title="Audit trail" icon={<CalendarClock size={16} aria-hidden />}>
        <AuditTrail logs={auditLogs} />
      </Panel>
    </div>
  );
}

function ActivityCenter({
  auditLogs,
  evalOps,
  notifications,
  project,
}: {
  auditLogs: AuditLogRecord[];
  evalOps: EvalOpsReport | null;
  notifications: NotificationRecord[];
  project: ProjectRecord;
}) {
  return (
    <div className="workspace-two-column">
      <Panel title="Notification stream" icon={<Bell size={16} aria-hidden />}>
        <div className="notification-list">
          {notifications.map((notification) => (
            <article className={`notification-item ${notification.severity}`} key={notification.id}>
              <strong>{notification.title}</strong>
              <span>{notification.body}</span>
              <em>{notification.status} / {formatDate(notification.created_at)}</em>
            </article>
          ))}
          {notifications.length === 0 ? <p className="muted-line">No notifications for {project.name}.</p> : null}
        </div>
      </Panel>

      <Panel title="Benchmark panel" icon={<Gauge size={16} aria-hidden />}>
        <div className="metric-grid compact">
          <MetricCard label="Runs evaluated" value={evalOps?.run_count ?? "n/a"} />
          <MetricCard label="Golden pass" value={evalOps ? formatPercent(evalOps.golden_set_pass_rate) : "n/a"} />
          <MetricCard label="Report quality" value={evalOps?.report_quality_score ?? "n/a"} />
          <MetricCard label="Time saved" value={evalOps ? `${evalOps.manual_time_saved_hours.toFixed(1)}h` : "n/a"} />
          <MetricCard label="Gate" value={evalOps?.regression_gate_status ?? "n/a"} tone={evalOps?.regression_gate_status === "fail" ? "warn" : "good"} />
        </div>
        <div className="recommendation-list compact">
          {(evalOps?.recommendations ?? []).slice(0, 5).map((item) => (
            <article className="recommendation-card medium" key={item}>
              <strong>Next</strong>
              <p>{item}</p>
            </article>
          ))}
        </div>
      </Panel>

      <Panel title="Audit trail" icon={<CalendarClock size={16} aria-hidden />}>
        <AuditTrail logs={auditLogs} />
      </Panel>
    </div>
  );
}

function AuditTrail({ logs }: { logs: AuditLogRecord[] }) {
  return (
    <div className="audit-timeline">
      {logs.slice(0, 24).map((log) => (
        <article key={log.id}>
          <strong>{log.action}</strong>
          <span>{log.resource_type} / {log.resource_id}</span>
          <em>{log.actor_type}{log.actor_id ? `:${log.actor_id}` : ""} / {formatDate(log.created_at)}</em>
        </article>
      ))}
      {logs.length === 0 ? <p className="muted-line">No audit records returned.</p> : null}
    </div>
  );
}

function QualityStep({
  label,
  ok,
  value,
}: {
  label: string;
  ok: boolean;
  value: ReactNode;
}) {
  return (
    <div className={ok ? "quality-step pass" : "quality-step warn"}>
      {ok ? <CheckCircle2 size={16} aria-hidden /> : <AlertTriangle size={16} aria-hidden />}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
