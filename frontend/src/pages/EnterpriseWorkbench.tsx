import { useEffect, useMemo, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertTriangle,
  Bell,
  Briefcase,
  CalendarClock,
  CheckCircle2,
  Database,
  ExternalLink,
  FileText,
  Gauge,
  GitCompare,
  Layers,
  ListChecks,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import {
  getProjectEvidenceGaps,
  getProjectBusinessPlan,
  getProjectCompetitorScores,
  getProjectQAEvaluation,
  getProjectReadinessScore,
  getReportReleaseGate,
  getReportVersionDiff,
  getProjectRedTeam,
  getWorkspaceUsage,
  listEnterpriseCompetitors,
  listEnterpriseNotifications,
  listEnterpriseProjects,
  listProjectClaims,
  listProjectEvidence,
  listProjectReportVersions,
  startMonitorWorkflow,
  startScheduledScanWorkflow,
  updateEvidenceQuality,
} from "../api/client";
import type {
  BusinessIntelPlan,
  BusinessQAEvaluation,
  BusinessQAFinding,
  ClaimRecord,
  CompetitorScoreReport,
  CompetitorRecord,
  EvidenceGapItem,
  EvidenceGapReport,
  EvidenceQualityLabel,
  EvidenceRecord,
  NotificationRecord,
  ProjectReadinessScore,
  ProjectRecord,
  RedTeamFinding,
  RedTeamReport,
  ReportReleaseGate,
  ReportVersionDiff,
  ReportVersionRecord,
  WorkspaceUsageSummary,
} from "../api/types";

type EnterpriseTab = "competitors" | "evidence" | "claims" | "reports";

export function EnterpriseWorkbench({
  initialTab = "evidence",
}: {
  initialTab?: EnterpriseTab;
}) {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorRecord[]>([]);
  const [evidence, setEvidence] = useState<EvidenceRecord[]>([]);
  const [claims, setClaims] = useState<ClaimRecord[]>([]);
  const [versions, setVersions] = useState<ReportVersionRecord[]>([]);
  const [businessPlan, setBusinessPlan] = useState<BusinessIntelPlan | null>(null);
  const [qaEvaluation, setQaEvaluation] = useState<BusinessQAEvaluation | null>(null);
  const [readinessScore, setReadinessScore] = useState<ProjectReadinessScore | null>(null);
  const [competitorScores, setCompetitorScores] = useState<CompetitorScoreReport | null>(null);
  const [evidenceGaps, setEvidenceGaps] = useState<EvidenceGapReport | null>(null);
  const [redTeam, setRedTeam] = useState<RedTeamReport | null>(null);
  const [workspaceUsage, setWorkspaceUsage] = useState<WorkspaceUsageSummary | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [diff, setDiff] = useState<ReportVersionDiff | null>(null);
  const [releaseGate, setReleaseGate] = useState<ReportReleaseGate | null>(null);
  const [activeTab, setActiveTab] = useState<EnterpriseTab>(initialTab);
  const [query, setQuery] = useState("");
  const [isLoadingProjects, setLoadingProjects] = useState(true);
  const [isLoadingProject, setLoadingProject] = useState(false);
  const [isStartingScan, setStartingScan] = useState(false);
  const [isStartingMonitor, setStartingMonitor] = useState(false);
  const [scanMessage, setScanMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function refreshProjects() {
    setLoadingProjects(true);
    setError(null);
    Promise.all([listEnterpriseProjects(), listEnterpriseNotifications({ limit: 8 })])
      .then(([items, notificationItems]) => {
        setProjects(items);
        setNotifications(notificationItems);
        setSelectedProjectId((current) => current ?? items[0]?.id ?? null);
      })
      .catch((err: Error) => {
        setError(err.message);
        setProjects([]);
        setNotifications([]);
      })
      .finally(() => setLoadingProjects(false));
  }

  useEffect(() => {
    refreshProjects();
  }, []);

  useEffect(() => {
    setActiveTab(initialTab);
  }, [initialTab]);

  useEffect(() => {
    const projectForLoad = projects.find((project) => project.id === selectedProjectId) ?? null;
    if (!selectedProjectId || !projectForLoad) {
      setCompetitors([]);
      setEvidence([]);
      setClaims([]);
      setVersions([]);
      setBusinessPlan(null);
      setQaEvaluation(null);
      setReadinessScore(null);
      setCompetitorScores(null);
      setEvidenceGaps(null);
      setRedTeam(null);
      setWorkspaceUsage(null);
      setSelectedVersionId(null);
      return;
    }

    let active = true;
    setLoadingProject(true);
    setError(null);
    Promise.all([
      listEnterpriseCompetitors({ projectId: selectedProjectId }),
      listProjectEvidence(selectedProjectId),
      listProjectClaims(selectedProjectId),
      listProjectReportVersions(selectedProjectId),
      getProjectBusinessPlan(selectedProjectId),
      getProjectQAEvaluation(selectedProjectId),
      getProjectReadinessScore(selectedProjectId),
      getProjectCompetitorScores(selectedProjectId),
      getProjectEvidenceGaps(selectedProjectId),
      getProjectRedTeam(selectedProjectId),
      getWorkspaceUsage(projectForLoad.workspace_id),
    ])
      .then(
        ([
          competitorItems,
          evidenceItems,
          claimItems,
          versionItems,
          businessPlanValue,
          qaEvaluationValue,
          readinessScoreValue,
          competitorScoresValue,
          evidenceGapsValue,
          redTeamValue,
          workspaceUsageValue,
        ]) => {
          if (!active) return;
          setCompetitors(competitorItems);
          setEvidence(evidenceItems);
          setClaims(claimItems);
          setVersions(versionItems);
          setBusinessPlan(businessPlanValue);
          setQaEvaluation(qaEvaluationValue);
          setReadinessScore(readinessScoreValue);
          setCompetitorScores(competitorScoresValue);
          setEvidenceGaps(evidenceGapsValue);
          setRedTeam(redTeamValue);
          setWorkspaceUsage(workspaceUsageValue);
          setSelectedVersionId(versionItems[0]?.id ?? null);
        },
      )
      .catch((err: Error) => {
        if (!active) return;
        setError(err.message);
        setCompetitors([]);
        setEvidence([]);
        setClaims([]);
        setVersions([]);
        setBusinessPlan(null);
        setQaEvaluation(null);
        setReadinessScore(null);
        setCompetitorScores(null);
        setEvidenceGaps(null);
        setRedTeam(null);
        setWorkspaceUsage(null);
        setSelectedVersionId(null);
      })
      .finally(() => {
        if (active) setLoadingProject(false);
      });

    return () => {
      active = false;
    };
  }, [projects, selectedProjectId]);

  useEffect(() => {
    if (!selectedVersionId) {
      setDiff(null);
      setReleaseGate(null);
      return;
    }

    let active = true;
    Promise.all([getReportVersionDiff(selectedVersionId), getReportReleaseGate(selectedVersionId)])
      .then(([diffValue, releaseGateValue]) => {
        if (!active) return;
        setDiff(diffValue);
        setReleaseGate(releaseGateValue);
      })
      .catch(() => {
        if (!active) return;
        setDiff(null);
        setReleaseGate(null);
      });
    return () => {
      active = false;
    };
  }, [selectedVersionId]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );
  const selectedVersion = useMemo(
    () => versions.find((version) => version.id === selectedVersionId) ?? null,
    [versions, selectedVersionId],
  );
  const competitorById = useMemo(
    () => new Map(competitors.map((competitor) => [competitor.id, competitor])),
    [competitors],
  );
  const evidenceById = useMemo(
    () => new Map(evidence.map((item) => [item.id, item])),
    [evidence],
  );
  const filteredEvidence = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return evidence;
    return evidence.filter((item) => {
      const competitor = competitorById.get(item.competitor_id)?.name ?? item.competitor_id;
      return [item.title, item.snippet, item.dimension, item.source_type, competitor]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [competitorById, evidence, query]);
  const latestVersion = versions[0] ?? null;
  const averageReliability =
    evidence.length > 0
      ? evidence.reduce((total, item) => total + item.reliability_score, 0) / evidence.length
      : 0;

  function handleStartScheduledScan() {
    if (!selectedProject) return;
    setStartingScan(true);
    setScanMessage(null);
    setError(null);
    startScheduledScanWorkflow({
      workspace_id: selectedProject.workspace_id,
      schedule_id: "manual-workbench-scan",
      requested_by: "workbench-user",
      project_ids: [selectedProject.id],
      dimensions: (businessPlan?.recommended_dimensions ?? ["pricing", "feature", "persona"]).slice(
        0,
        8,
      ),
      execution_mode: "auto",
      max_projects: 1,
    })
      .then((response) => {
        setScanMessage(`${response.status}: ${response.workflow_id}`);
        return listEnterpriseNotifications({
          workspaceId: selectedProject.workspace_id,
          limit: 8,
        });
      })
      .then(setNotifications)
      .catch((err: Error) => {
        setError(err.message);
      })
      .finally(() => setStartingScan(false));
  }

  function handleStartMonitor() {
    if (!selectedProject) return;
    setStartingMonitor(true);
    setScanMessage(null);
    setError(null);
    startMonitorWorkflow({
      workspace_id: selectedProject.workspace_id,
      project_id: selectedProject.id,
      monitor_id: "manual-workbench-monitor",
      requested_by: "workbench-user",
      dimensions: (businessPlan?.recommended_dimensions ?? ["pricing", "feature", "persona"]).slice(0, 8),
      execution_mode: "auto",
      interval_seconds: 604800,
      max_cycles: 1,
    })
      .then((response) => {
        setScanMessage(`${response.status}: ${response.workflow_id}`);
        return listEnterpriseNotifications({
          workspaceId: selectedProject.workspace_id,
          limit: 8,
        });
      })
      .then(setNotifications)
      .catch((err: Error) => {
        setError(err.message);
      })
      .finally(() => setStartingMonitor(false));
  }

  function handleQualityChange(evidenceId: string, qualityLabel: EvidenceQualityLabel) {
    setEvidence((items) =>
      items.map((item) =>
        item.id === evidenceId ? { ...item, quality_label: qualityLabel } : item,
      ),
    );
    updateEvidenceQuality(evidenceId, { quality_label: qualityLabel })
      .then(({ evidence: updated }) => {
        setEvidence((items) => items.map((item) => (item.id === updated.id ? updated : item)));
        if (selectedProjectId) {
          void Promise.all([
            getProjectQAEvaluation(selectedProjectId),
            getProjectReadinessScore(selectedProjectId),
            getProjectCompetitorScores(selectedProjectId),
            getProjectEvidenceGaps(selectedProjectId),
            getProjectRedTeam(selectedProjectId),
          ]).then(([qaValue, readinessValue, competitorScoresValue, evidenceGapsValue, redTeamValue]) => {
            setQaEvaluation(qaValue);
            setReadinessScore(readinessValue);
            setCompetitorScores(competitorScoresValue);
            setEvidenceGaps(evidenceGapsValue);
            setRedTeam(redTeamValue);
          });
        }
      })
      .catch((err: Error) => {
        setError(err.message);
        void listProjectEvidence(selectedProjectId ?? "").then(setEvidence);
      });
  }

  return (
    <section className="work-surface enterprise-workbench">
      <header className="page-header">
        <div>
          <h1>Enterprise workbench</h1>
          <p>Projects, evidence, claims, and report versions from the enterprise projection store.</p>
        </div>
        <button className="icon-text-button" type="button" onClick={refreshProjects}>
          <RefreshCw size={16} aria-hidden />
          Refresh
        </button>
      </header>

      {error ? <p className="error-line">{error}</p> : null}

      <div className="enterprise-layout">
        <aside className="panel project-rail">
          <div className="panel-heading-row">
            <h2>Projects</h2>
            <Briefcase size={17} aria-hidden />
          </div>
          {isLoadingProjects ? <p className="muted-line">Loading projects...</p> : null}
          {!isLoadingProjects && projects.length === 0 ? (
            <div className="empty-state">
              <Database size={18} aria-hidden />
              <span>No enterprise projects yet.</span>
            </div>
          ) : null}
          <div className="project-list">
            {projects.map((project) => (
              <button
                className={project.id === selectedProjectId ? "project-card active" : "project-card"}
                key={project.id}
                type="button"
                onClick={() => setSelectedProjectId(project.id)}
              >
                <strong>{project.name}</strong>
                <span>{project.competitor_layer} / v{project.competitor_set_hash.slice(0, 8)}</span>
                <em>{formatDate(project.updated_at)}</em>
              </button>
            ))}
          </div>
          <div className="operations-panel">
            <div className="panel-heading-row">
              <h2>Operations</h2>
              <CalendarClock size={17} aria-hidden />
            </div>
            <button
              className="icon-text-button full-width"
              disabled={!selectedProject || isStartingScan}
              type="button"
              onClick={handleStartScheduledScan}
            >
              <RefreshCw size={16} aria-hidden />
              {isStartingScan ? "Starting scan" : "Scan selected"}
            </button>
            <button
              className="icon-text-button full-width"
              disabled={!selectedProject || isStartingMonitor}
              type="button"
              onClick={handleStartMonitor}
            >
              <CalendarClock size={16} aria-hidden />
              {isStartingMonitor ? "Starting monitor" : "Monitor selected"}
            </button>
            {scanMessage ? <p className="muted-line">{scanMessage}</p> : null}
            {workspaceUsage ? <WorkspaceUsagePanel usage={workspaceUsage} /> : null}
            <div className="notification-list">
              {notifications.slice(0, 5).map((notification) => (
                <article className={`notification-item ${notification.severity}`} key={notification.id}>
                  <div>
                    <Bell size={14} aria-hidden />
                    <strong>{notification.title}</strong>
                  </div>
                  <span>{notification.status} / {formatDate(notification.created_at)}</span>
                </article>
              ))}
            </div>
            {notifications.length === 0 ? <p className="muted-line">No notifications yet.</p> : null}
          </div>
        </aside>

        <div className="enterprise-main">
          {selectedProject ? (
            <>
              <section className="panel project-summary">
                <div>
                  <span className="eyebrow">Project</span>
                  <h2>{selectedProject.name}</h2>
                  <p>{selectedProject.topic}</p>
                </div>
                <div className="metric-grid compact">
                  <Metric icon={<Layers size={17} aria-hidden />} label="Competitors" value={competitors.length} />
                  <Metric icon={<Database size={17} aria-hidden />} label="Evidence" value={evidence.length} />
                  <Metric icon={<ShieldCheck size={17} aria-hidden />} label="Claims" value={claims.length} />
                  <Metric icon={<FileText size={17} aria-hidden />} label="Versions" value={versions.length} />
                </div>
                <div className="project-meta-row">
                  <span>Layer {businessPlan?.competitor_layer.layer ?? selectedProject.competitor_layer}</span>
                  <span>Scenario {businessPlan?.scenario_pack.name ?? selectedProject.scenario_id ?? "none"}</span>
                  <span>Reliability {formatPercent(averageReliability)}</span>
                  <span>Latest {latestVersion ? `v${latestVersion.version_number}` : "none"}</span>
                </div>
              </section>

              {businessPlan ? (
                <section className="panel scenario-panel">
                  <div className="panel-heading-row">
                    <h2>{businessPlan.scenario_pack.name}</h2>
                    <CheckCircle2 size={17} aria-hidden />
                  </div>
                  <p>{businessPlan.scenario_pack.description}</p>
                  <div className="scenario-chip-row">
                    {businessPlan.recommended_dimensions.map((dimension) => (
                      <span key={dimension}>{dimension}</span>
                    ))}
                  </div>
                  <div className="qa-rule-row">
                    {businessPlan.qa_rules.map((rule) => (
                      <span key={rule.id} className={`qa-rule ${rule.severity}`}>
                        {rule.name}
                      </span>
                    ))}
                  </div>
                </section>
              ) : null}

              {readinessScore ? <ReadinessScorePanel readinessScore={readinessScore} /> : null}

              {competitorScores ? <CompetitorScorePanel report={competitorScores} /> : null}

              {evidenceGaps ? <EvidenceGapPanel report={evidenceGaps} /> : null}

              {redTeam ? <RedTeamPanel report={redTeam} /> : null}

              {qaEvaluation ? <QAEvaluationPanel evaluation={qaEvaluation} /> : null}

              <section className="panel competitor-strip-panel">
                <div className="panel-heading-row">
                  <h2>Competitor library</h2>
                  <Layers size={17} aria-hidden />
                </div>
                <div className="competitor-strip">
                  {competitors.map((competitor) => (
                    <span key={competitor.id} title={competitor.id}>
                      {competitor.name}
                      <em>{competitor.layer}</em>
                    </span>
                  ))}
                </div>
              </section>

              <section className="panel enterprise-data-panel">
                <div className="enterprise-tabs">
                  <button
                    className={activeTab === "competitors" ? "active" : ""}
                    type="button"
                    onClick={() => setActiveTab("competitors")}
                  >
                    Competitors
                  </button>
                  <button
                    className={activeTab === "evidence" ? "active" : ""}
                    type="button"
                    onClick={() => setActiveTab("evidence")}
                  >
                    Evidence
                  </button>
                  <button
                    className={activeTab === "claims" ? "active" : ""}
                    type="button"
                    onClick={() => setActiveTab("claims")}
                  >
                    Claims
                  </button>
                  <button
                    className={activeTab === "reports" ? "active" : ""}
                    type="button"
                    onClick={() => setActiveTab("reports")}
                  >
                    Reports
                  </button>
                </div>

                {isLoadingProject ? <p className="muted-line">Loading project data...</p> : null}
                {activeTab === "competitors" ? (
                  <CompetitorLibrary competitors={competitors} scores={competitorScores} />
                ) : null}
                {activeTab === "evidence" ? (
                  <EvidenceTable
                    competitorById={competitorById}
                    evidence={filteredEvidence}
                    onQualityChange={handleQualityChange}
                    query={query}
                    setQuery={setQuery}
                  />
                ) : null}
                {activeTab === "claims" ? (
                  <ClaimList
                    claims={claims}
                    competitorById={competitorById}
                    evidenceById={evidenceById}
                  />
                ) : null}
                {activeTab === "reports" ? (
                  <ReportHistory
                    diff={diff}
                    releaseGate={releaseGate}
                    selectedVersion={selectedVersion}
                    selectedVersionId={selectedVersionId}
                    setSelectedVersionId={setSelectedVersionId}
                    versions={versions}
                  />
                ) : null}
              </section>
            </>
          ) : (
            <div className="empty-state">
              <Briefcase size={18} aria-hidden />
              <span>Select a project after an analysis run has completed.</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function CompetitorLibrary({
  competitors,
  scores,
}: {
  competitors: CompetitorRecord[];
  scores: CompetitorScoreReport | null;
}) {
  const scoreByCompetitor = new Map(
    (scores?.scores ?? []).map((score) => [score.competitor_id, score]),
  );
  if (competitors.length === 0) {
    return (
      <div className="empty-state">
        <Layers size={18} aria-hidden />
        <span>No competitors are linked to this project.</span>
      </div>
    );
  }
  return (
    <div className="competitor-library-grid">
      {competitors.map((competitor) => {
        const score = scoreByCompetitor.get(competitor.id);
        return (
          <article className="competitor-library-card" key={competitor.id}>
            <div>
              <strong>{competitor.name}</strong>
              <span>{competitor.layer}</span>
            </div>
            <p>{competitor.homepage_url ?? "No homepage recorded"}</p>
            <div className="project-meta-row">
              <span>Aliases {competitor.aliases.length}</span>
              <span>Score {score ? score.total_score : "-"}</span>
              <span>Rank {score ? `#${score.rank}` : "-"}</span>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function ReadinessScorePanel({
  readinessScore,
}: {
  readinessScore: ProjectReadinessScore;
}) {
  return (
    <section className={`panel readiness-panel ${readinessScore.risk_level}`}>
      <div className="panel-heading-row">
        <h2>Readiness score</h2>
        <Gauge size={17} aria-hidden />
      </div>
      <div className="readiness-score-row">
        <strong>{readinessScore.score}</strong>
        <div>
          <span>{readinessScore.risk_level.replace("_", " ")}</span>
          <p>{readinessScore.summary}</p>
        </div>
      </div>
      <div className="readiness-breakdown">
        <ScoreBar label="Evidence" value={readinessScore.evidence_score} />
        <ScoreBar label="Claims" value={readinessScore.claim_score} />
        <ScoreBar label="Coverage" value={readinessScore.coverage_score} />
        <ScoreBar label="QA" value={readinessScore.qa_score} />
      </div>
      <div className="recommendation-list">
        {readinessScore.recommendations.slice(0, 4).map((item) => (
          <article className={`recommendation-card ${item.priority}`} key={item.id}>
            <strong>{item.title}</strong>
            <span>{item.priority} / {item.action_type.replace("_", " ")}</span>
            <p>{item.detail}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function CompetitorScorePanel({ report }: { report: CompetitorScoreReport }) {
  if (report.scores.length === 0) {
    return null;
  }
  return (
    <section className="panel competitor-score-panel">
      <div className="panel-heading-row">
        <h2>Competitor scores</h2>
        <ListChecks size={17} aria-hidden />
      </div>
      <div className="scorecard-grid">
        {report.scores.slice(0, 4).map((score) => (
          <article className="competitor-score-card" key={score.competitor_id}>
            <div>
              <span>#{score.rank}</span>
              <strong>{score.competitor_name}</strong>
              <em>{score.total_score}</em>
            </div>
            <ScoreBar label="Evidence" value={score.evidence_score} />
            <ScoreBar label="Claims" value={score.claim_score} />
            <ScoreBar label="Coverage" value={score.coverage_score} />
            <p>{score.recommendation}</p>
            <div className="dimension-score-row">
              {score.dimension_scores.slice(0, 4).map((dimension) => (
                <span key={dimension.dimension} title={dimension.rationale}>
                  {dimension.dimension}
                  <em>{dimension.score}</em>
                </span>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="score-bar">
      <span>
        {label}
        <em>{value}%</em>
      </span>
      <div>
        <i style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

function WorkspaceUsagePanel({ usage }: { usage: WorkspaceUsageSummary }) {
  const rows = [
    {
      label: "Runs",
      value: `${usage.run_count}/${usage.monthly_run_quota}`,
      ratio: usage.run_usage_ratio,
    },
    {
      label: "Tokens",
      value: `${usage.total_tokens_estimate}/${usage.monthly_token_quota}`,
      ratio: usage.token_usage_ratio,
    },
    {
      label: "Cost",
      value: `$${usage.cost_estimate_usd.toFixed(4)}/$${usage.monthly_cost_quota_usd.toFixed(2)}`,
      ratio: usage.cost_usage_ratio,
    },
  ];
  return (
    <div className={`workspace-usage-panel ${usage.status}`}>
      <div>
        <Gauge size={14} aria-hidden />
        <strong>Workspace usage</strong>
        <span>{usage.status}</span>
      </div>
      {rows.map((row) => (
        <label key={row.label}>
          <span>
            {row.label}
            <em>{row.value}</em>
          </span>
          <meter max={1} min={0} value={Math.min(row.ratio, 1)} />
        </label>
      ))}
    </div>
  );
}

function EvidenceGapPanel({ report }: { report: EvidenceGapReport }) {
  const status = report.critical_count > 0 ? "critical" : report.high_count > 0 ? "high" : "clear";
  return (
    <section className={`panel evidence-gap-panel ${status}`}>
      <div className="panel-heading-row">
        <h2>Evidence gaps</h2>
        {status === "clear" ? <CheckCircle2 size={17} aria-hidden /> : <Search size={17} aria-hidden />}
      </div>
      <div className="evidence-gap-summary">
        <span>
          <strong>{report.gap_count}</strong>
          <em>Total gaps</em>
        </span>
        <span>
          <strong>{report.critical_count}</strong>
          <em>Critical</em>
        </span>
        <span>
          <strong>{report.high_count}</strong>
          <em>High</em>
        </span>
        <span>
          <strong>{report.medium_count}</strong>
          <em>Medium</em>
        </span>
      </div>
      {report.gaps.length > 0 ? (
        <div className="evidence-gap-list">
          {report.gaps.slice(0, 5).map((gap) => (
            <EvidenceGapCard gap={gap} key={gap.id} />
          ))}
        </div>
      ) : (
        <p className="muted-line">No structured evidence gaps for the active scenario.</p>
      )}
    </section>
  );
}

function EvidenceGapCard({ gap }: { gap: EvidenceGapItem }) {
  return (
    <article className={`evidence-gap-card ${gap.severity}`}>
      <div>
        <strong>{gap.gap_type.replace(/_/g, " ")}</strong>
        <span>
          {gap.severity}
          {gap.competitor_name ? ` / ${gap.competitor_name}` : ""}
          {gap.dimension ? ` / ${gap.dimension}` : ""}
        </span>
      </div>
      <p>{gap.message}</p>
      {gap.recommended_query ? <em>{gap.recommended_query}</em> : null}
    </article>
  );
}

function RedTeamPanel({ report }: { report: RedTeamReport }) {
  const status = report.high_severity_count >= 2 ? "high" : report.finding_count > 0 ? "medium" : "clear";
  return (
    <section className={`panel red-team-panel ${status}`}>
      <div className="panel-heading-row">
        <h2>Red team</h2>
        {status === "clear" ? <CheckCircle2 size={17} aria-hidden /> : <AlertTriangle size={17} aria-hidden />}
      </div>
      <div className="red-team-summary">
        <span>
          <strong>{report.finding_count}</strong>
          <em>Findings</em>
        </span>
        <span>
          <strong>{report.high_severity_count}</strong>
          <em>High severity</em>
        </span>
        <span>
          <strong>{report.pydantic_ai_available ? "on" : "off"}</strong>
          <em>Pydantic-AI</em>
        </span>
      </div>
      {report.findings.length > 0 ? (
        <div className="red-team-list">
          {report.findings.slice(0, 5).map((finding) => (
            <RedTeamFindingCard finding={finding} key={finding.id} />
          ))}
        </div>
      ) : (
        <p className="muted-line">No red-team findings for the active project.</p>
      )}
    </section>
  );
}

function RedTeamFindingCard({ finding }: { finding: RedTeamFinding }) {
  return (
    <article className={`red-team-card ${finding.severity}`}>
      <div>
        <strong>{finding.finding_type.replace(/_/g, " ")}</strong>
        <span>
          {finding.severity}
          {finding.competitor_name ? ` / ${finding.competitor_name}` : ""}
          {finding.dimension ? ` / ${finding.dimension}` : ""}
        </span>
      </div>
      <p>{finding.message}</p>
      <em>{finding.recommendation}</em>
    </article>
  );
}

function QAEvaluationPanel({ evaluation }: { evaluation: BusinessQAEvaluation }) {
  const status = evaluation.blocker_count > 0 ? "blocker" : evaluation.warn_count > 0 ? "warn" : "pass";
  return (
    <section className={`panel business-qa-panel ${status}`}>
      <div className="panel-heading-row">
        <h2>Business QA</h2>
        {status === "pass" ? <CheckCircle2 size={17} aria-hidden /> : <AlertTriangle size={17} aria-hidden />}
      </div>
      <div className="business-qa-metrics">
        <span>
          <strong>{evaluation.passed_rules}/{evaluation.total_rules}</strong>
          <em>Rules passed</em>
        </span>
        <span>
          <strong>{evaluation.blocker_count}</strong>
          <em>Blockers</em>
        </span>
        <span>
          <strong>{evaluation.warn_count}</strong>
          <em>Warnings</em>
        </span>
        <span>
          <strong>{evaluation.info_count}</strong>
          <em>Info</em>
        </span>
      </div>
      {evaluation.findings.length > 0 ? (
        <div className="business-qa-findings">
          {evaluation.findings.slice(0, 5).map((finding) => (
            <QAFindingItem finding={finding} key={finding.id} />
          ))}
        </div>
      ) : (
        <p className="muted-line">All active business QA rules passed.</p>
      )}
    </section>
  );
}

function QAFindingItem({ finding }: { finding: BusinessQAFinding }) {
  return (
    <article className={`business-qa-finding ${finding.severity}`}>
      <div>
        <strong>{finding.rule_name}</strong>
        <span>
          {finding.severity}
          {finding.competitor_name ? ` / ${finding.competitor_name}` : ""}
          {finding.dimension ? ` / ${finding.dimension}` : ""}
        </span>
      </div>
      <p>{finding.message}</p>
      {finding.recommendation ? <em>{finding.recommendation}</em> : null}
    </article>
  );
}

function Metric({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: number | string;
}) {
  return (
    <span>
      {icon}
      <strong>{value}</strong>
      <em>{label}</em>
    </span>
  );
}

function EvidenceTable({
  competitorById,
  evidence,
  onQualityChange,
  query,
  setQuery,
}: {
  competitorById: Map<string, CompetitorRecord>;
  evidence: EvidenceRecord[];
  onQualityChange: (evidenceId: string, qualityLabel: EvidenceQualityLabel) => void;
  query: string;
  setQuery: (value: string) => void;
}) {
  return (
    <div className="evidence-section">
      <label className="search-box">
        <Search size={16} aria-hidden />
        <input
          aria-label="Search evidence"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search evidence"
        />
      </label>
      <div className="enterprise-table-wrap">
        <table className="enterprise-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Competitor</th>
              <th>Dimension</th>
              <th>Quality</th>
              <th>Reliability</th>
            </tr>
          </thead>
          <tbody>
            {evidence.map((item) => {
              const competitor = competitorById.get(item.competitor_id)?.name ?? item.competitor_id;
              return (
                <tr id={`evidence-${item.id}`} key={item.id}>
                  <td>
                    <strong>{item.title}</strong>
                    <span>{item.snippet}</span>
                    {item.url ? (
                      <a href={item.url} rel="noreferrer" target="_blank">
                        <ExternalLink size={13} aria-hidden />
                        {item.url}
                      </a>
                    ) : null}
                  </td>
                  <td>{competitor}</td>
                  <td>{item.dimension}</td>
                  <td>
                    <select
                      aria-label={`Quality for ${item.title}`}
                      className="quality-select"
                      value={item.quality_label}
                      onChange={(event) =>
                        onQualityChange(item.id, event.target.value as EvidenceQualityLabel)
                      }
                    >
                      <option value="unreviewed">unreviewed</option>
                      <option value="accepted">accepted</option>
                      <option value="rejected">rejected</option>
                      <option value="stale">stale</option>
                    </select>
                  </td>
                  <td>{formatPercent(item.reliability_score)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {evidence.length === 0 ? <p className="muted-line">No matching evidence.</p> : null}
    </div>
  );
}

function ClaimList({
  claims,
  competitorById,
  evidenceById,
}: {
  claims: ClaimRecord[];
  competitorById: Map<string, CompetitorRecord>;
  evidenceById: Map<string, EvidenceRecord>;
}) {
  if (claims.length === 0) {
    return <p className="muted-line">No claims have been projected yet.</p>;
  }
  return (
    <div className="claim-list">
      {claims.map((claim) => {
        const competitor = competitorById.get(claim.competitor_id)?.name ?? claim.competitor_id;
        return (
          <article key={claim.id}>
            <div>
              <strong>{claim.claim_text}</strong>
              <span>
                {competitor} / {claim.claim_type} / {formatPercent(claim.confidence)}
              </span>
            </div>
            <div className="source-id-links">
              {claim.evidence_ids.map((evidenceId) => (
                <a href={`#evidence-${evidenceId}`} key={evidenceId} title={evidenceById.get(evidenceId)?.title}>
                  {evidenceById.get(evidenceId)?.dimension ?? evidenceId.slice(0, 10)}
                </a>
              ))}
            </div>
          </article>
        );
      })}
    </div>
  );
}

function ReportHistory({
  diff,
  releaseGate,
  selectedVersion,
  selectedVersionId,
  setSelectedVersionId,
  versions,
}: {
  diff: ReportVersionDiff | null;
  releaseGate: ReportReleaseGate | null;
  selectedVersion: ReportVersionRecord | null;
  selectedVersionId: string | null;
  setSelectedVersionId: (value: string) => void;
  versions: ReportVersionRecord[];
}) {
  if (versions.length === 0) {
    return <p className="muted-line">No report versions have been created yet.</p>;
  }
  return (
    <div className="report-history-grid">
      <aside className="version-list" aria-label="Report versions">
        {versions.map((version) => (
          <button
            className={version.id === selectedVersionId ? "active" : ""}
            key={version.id}
            type="button"
            onClick={() => setSelectedVersionId(version.id)}
          >
            <strong>v{version.version_number}</strong>
            <span>{version.status}</span>
            <em>{formatDate(version.created_at)}</em>
          </button>
        ))}
      </aside>
      <div className="report-reader">
        <div className="panel-heading-row">
          <h2>{selectedVersion ? `Report v${selectedVersion.version_number}` : "Report"}</h2>
          <GitCompare size={17} aria-hidden />
        </div>
        {releaseGate ? <ReleaseGatePanel gate={releaseGate} /> : null}
        {selectedVersion ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{selectedVersion.report_md || "No report body."}</ReactMarkdown>
        ) : null}
        {diff ? (
          <div className="report-diff">
            <div className="diff-summary">
              <span>Base {diff.base_version ? `v${diff.base_version.version_number}` : "none"}</span>
              <span>+{diff.added_lines}</span>
              <span>-{diff.removed_lines}</span>
            </div>
            <pre>
              {diff.lines.map((line, index) => {
                const prefix = line.kind === "added" ? "+" : line.kind === "removed" ? "-" : " ";
                return `${prefix} ${line.text}${index === diff.lines.length - 1 ? "" : "\n"}`;
              })}
            </pre>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ReleaseGatePanel({ gate }: { gate: ReportReleaseGate }) {
  return (
    <section className={`release-gate-panel ${gate.status}`}>
      <div>
        <strong>{gate.allowed ? "Release gate passed" : "Release gate blocked"}</strong>
        <span>
          {gate.readiness.score} readiness / {gate.qa_evaluation.finding_count} QA finding(s)
        </span>
      </div>
      {gate.issues.length ? (
        <ul>
          {gate.issues.slice(0, 3).map((issue) => (
            <li key={issue.id}>{issue.message}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
