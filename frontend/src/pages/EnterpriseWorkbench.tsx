import { useEffect, useMemo, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Briefcase,
  CheckCircle2,
  Database,
  ExternalLink,
  FileText,
  GitCompare,
  Layers,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import {
  getProjectBusinessPlan,
  getReportVersionDiff,
  listEnterpriseCompetitors,
  listEnterpriseProjects,
  listProjectClaims,
  listProjectEvidence,
  listProjectReportVersions,
  updateEvidenceQuality,
} from "../api/client";
import type {
  BusinessIntelPlan,
  ClaimRecord,
  CompetitorRecord,
  EvidenceQualityLabel,
  EvidenceRecord,
  ProjectRecord,
  ReportVersionDiff,
  ReportVersionRecord,
} from "../api/types";

type EnterpriseTab = "evidence" | "claims" | "reports";

export function EnterpriseWorkbench() {
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorRecord[]>([]);
  const [evidence, setEvidence] = useState<EvidenceRecord[]>([]);
  const [claims, setClaims] = useState<ClaimRecord[]>([]);
  const [versions, setVersions] = useState<ReportVersionRecord[]>([]);
  const [businessPlan, setBusinessPlan] = useState<BusinessIntelPlan | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [diff, setDiff] = useState<ReportVersionDiff | null>(null);
  const [activeTab, setActiveTab] = useState<EnterpriseTab>("evidence");
  const [query, setQuery] = useState("");
  const [isLoadingProjects, setLoadingProjects] = useState(true);
  const [isLoadingProject, setLoadingProject] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function refreshProjects() {
    setLoadingProjects(true);
    setError(null);
    listEnterpriseProjects()
      .then((items) => {
        setProjects(items);
        setSelectedProjectId((current) => current ?? items[0]?.id ?? null);
      })
      .catch((err: Error) => {
        setError(err.message);
        setProjects([]);
      })
      .finally(() => setLoadingProjects(false));
  }

  useEffect(() => {
    refreshProjects();
  }, []);

  useEffect(() => {
    if (!selectedProjectId) {
      setCompetitors([]);
      setEvidence([]);
      setClaims([]);
      setVersions([]);
      setBusinessPlan(null);
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
    ])
      .then(([competitorItems, evidenceItems, claimItems, versionItems, businessPlanValue]) => {
        if (!active) return;
        setCompetitors(competitorItems);
        setEvidence(evidenceItems);
        setClaims(claimItems);
        setVersions(versionItems);
        setBusinessPlan(businessPlanValue);
        setSelectedVersionId(versionItems[0]?.id ?? null);
      })
      .catch((err: Error) => {
        if (!active) return;
        setError(err.message);
        setCompetitors([]);
        setEvidence([]);
        setClaims([]);
        setVersions([]);
        setBusinessPlan(null);
        setSelectedVersionId(null);
      })
      .finally(() => {
        if (active) setLoadingProject(false);
      });

    return () => {
      active = false;
    };
  }, [selectedProjectId]);

  useEffect(() => {
    if (!selectedVersionId) {
      setDiff(null);
      return;
    }

    let active = true;
    getReportVersionDiff(selectedVersionId)
      .then((value) => {
        if (active) setDiff(value);
      })
      .catch(() => {
        if (active) setDiff(null);
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
  function handleQualityChange(evidenceId: string, qualityLabel: EvidenceQualityLabel) {
    setEvidence((items) =>
      items.map((item) =>
        item.id === evidenceId ? { ...item, quality_label: qualityLabel } : item,
      ),
    );
    updateEvidenceQuality(evidenceId, { quality_label: qualityLabel }).catch((err: Error) => {
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
  selectedVersion,
  selectedVersionId,
  setSelectedVersionId,
  versions,
}: {
  diff: ReportVersionDiff | null;
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

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
