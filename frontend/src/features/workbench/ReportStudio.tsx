import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Database, Download, FileText, GitCompareArrows, ShieldCheck, XCircle } from "lucide-react";
import { getReportVersionDiff } from "../../api/client";
import type {
  ArtifactRecord,
  ClaimRecord,
  EvidenceQualityLabel,
  EvidenceRecord,
  ReportReleaseGate,
  ReportVersionDiff,
  ReportVersionRecord,
} from "../../api/types";
import { EmptyState, LoadingState, Panel, StatusPill } from "../../components/ui";
import { ReportView } from "../report/ReportView";
import type { ReportSourceBundle } from "../report/sourceBundle";
import { formatDate } from "./format";
import type { ReportAction, ReportExportFormat } from "./reportOperations";

interface ReportStudioProps {
  claims: ClaimRecord[];
  evidenceById: Map<string, EvidenceRecord>;
  isPending: boolean;
  lastExport: ArtifactRecord | null;
  onExport: (format: ReportExportFormat) => void;
  onEvidenceQuality: (evidenceId: string, qualityLabel: EvidenceQualityLabel) => void;
  onSelectClaim: (claim: ClaimRecord) => void;
  onSelectEvidence: (evidence: EvidenceRecord) => void;
  onSelectReport: (report: ReportVersionRecord) => void;
  onReportAction: (action: ReportAction) => void;
  releaseGate: ReportReleaseGate | null;
  reportSources: ReportSourceBundle;
  selectedVersion: ReportVersionRecord | null;
  selectedVersionId: string | null;
  setSelectedVersionId: (versionId: string) => void;
  versions: ReportVersionRecord[];
}

export function ReportStudio({
  claims,
  evidenceById,
  isPending,
  lastExport,
  onExport,
  onEvidenceQuality,
  onSelectClaim,
  onSelectEvidence,
  onSelectReport,
  onReportAction,
  releaseGate,
  reportSources,
  selectedVersion,
  selectedVersionId,
  setSelectedVersionId,
  versions,
}: ReportStudioProps) {
  const [diff, setDiff] = useState<ReportVersionDiff | null>(null);
  const [isDiffLoading, setDiffLoading] = useState(false);
  const selectedClaimIds = useMemo(() => new Set(selectedVersion?.claim_ids ?? []), [selectedVersion?.claim_ids]);
  const scopedClaims = useMemo(
    () => claims.filter((claim) => selectedClaimIds.has(claim.id)).slice(0, 8),
    [claims, selectedClaimIds],
  );
  const previousVersion = useMemo(() => {
    if (!selectedVersion) return null;
    const sorted = versions.slice().sort((a, b) => b.version_number - a.version_number);
    return sorted.find((version) => version.version_number < selectedVersion.version_number) ?? null;
  }, [selectedVersion, versions]);

  useEffect(() => {
    if (!selectedVersion) {
      setDiff(null);
      return;
    }
    let active = true;
    setDiffLoading(true);
    getReportVersionDiff(selectedVersion.id, previousVersion?.id)
      .then((value) => {
        if (active) setDiff(value);
      })
      .catch(() => {
        if (active) setDiff(null);
      })
      .finally(() => {
        if (active) setDiffLoading(false);
      });
    return () => {
      active = false;
    };
  }, [previousVersion?.id, selectedVersion?.id]);

  return (
    <div className="report-studio-layout">
      <div className="review-left-rail">
        <Panel className="version-rail" title="Versions">
          {versions.map((version) => (
            <button
              className={version.id === selectedVersionId ? "version-item active" : "version-item"}
              key={version.id}
              type="button"
              onClick={() => {
                setSelectedVersionId(version.id);
                onSelectReport(version);
              }}
            >
              <strong>v{version.version_number}</strong>
              <span>{version.status}</span>
              <em>{formatDate(version.created_at)}</em>
            </button>
          ))}
          {versions.length === 0 ? <EmptyState title="No report versions" /> : null}
        </Panel>

        <DiffPanel diff={diff} isLoading={isDiffLoading} previousVersion={previousVersion} />
      </div>

      <div className="report-reader-panel" aria-label="Report reader">
        {selectedVersion ? (
          <ReportView
            markdown={selectedVersion.report_md}
            sourceAliases={reportSources.aliases}
            sources={reportSources.sources}
          />
        ) : (
          <EmptyState title="Select a version" />
        )}
      </div>

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

        <Panel title="Claim review" icon={<GitCompareArrows size={16} aria-hidden />}>
          <div className="review-claim-list">
            {scopedClaims.map((claim) => (
              <button className="review-claim-item" key={claim.id} type="button" onClick={() => onSelectClaim(claim)}>
                <StatusPill tone={claim.status === "accepted" ? "good" : claim.status === "rejected" ? "bad" : "warn"}>
                  {claim.status}
                </StatusPill>
                <strong>{claim.claim_type}</strong>
                <span>{claim.claim_text}</span>
                <em>{Math.round(claim.confidence * 100)}% confidence / {claim.evidence_ids.length} evidence</em>
              </button>
            ))}
            {scopedClaims.length === 0 ? <EmptyState title="No scoped claims" /> : null}
          </div>
        </Panel>

        <Panel title="Evidence scope" icon={<Database size={16} aria-hidden />}>
          {selectedVersion ? (
            <div className="source-scope-list">
              {selectedVersion.evidence_ids.slice(0, 8).map((id) => {
                const evidence = evidenceById.get(id);
                return (
                  <article className="source-scope-item" key={id}>
                    <strong>{evidence?.title ?? id}</strong>
                    <span>{evidence?.dimension ?? "unknown"}</span>
                    {evidence ? (
                      <div className="scope-review-actions">
                        <button className="table-action-button" type="button" onClick={() => onSelectEvidence(evidence)}>
                          Inspect
                        </button>
                        <select
                          aria-label={`Quality for ${evidence.title}`}
                          value={evidence.quality_label}
                          onChange={(event) => onEvidenceQuality(evidence.id, event.target.value as EvidenceQualityLabel)}
                        >
                          <option value="unreviewed">unreviewed</option>
                          <option value="accepted">accepted</option>
                          <option value="rejected">rejected</option>
                          <option value="stale">stale</option>
                        </select>
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          ) : null}
        </Panel>
      </aside>
    </div>
  );
}

function DiffPanel({
  diff,
  isLoading,
  previousVersion,
}: {
  diff: ReportVersionDiff | null;
  isLoading: boolean;
  previousVersion: ReportVersionRecord | null;
}) {
  return (
    <Panel title="Version diff" icon={<GitCompareArrows size={16} aria-hidden />}>
      {isLoading ? <LoadingState label="Loading diff" /> : null}
      {!isLoading && diff ? (
        <div className="report-diff-panel">
          <div className="metric-grid compact">
            <span className="metric-card good">
              <i aria-hidden />
              <strong>{diff.added_lines}</strong>
              <em>added</em>
            </span>
            <span className="metric-card warn">
              <i aria-hidden />
              <strong>{diff.removed_lines}</strong>
              <em>removed</em>
            </span>
            <span className="metric-card">
              <i aria-hidden />
              <strong>{diff.unchanged_lines}</strong>
              <em>same</em>
            </span>
          </div>
          <p className="muted-line">
            {previousVersion ? `Compared with v${previousVersion.version_number}` : "No previous version available."}
          </p>
          <div className="report-diff-lines">
            {diff.lines
              .filter((line) => line.kind !== "unchanged")
              .slice(0, 12)
              .map((line, index) => (
                <code className={line.kind} key={`${line.kind}-${index}`}>
                  {line.kind === "added" ? "+ " : "- "}
                  {line.text}
                </code>
              ))}
          </div>
        </div>
      ) : null}
      {!isLoading && !diff ? <EmptyState title="No diff available" /> : null}
    </Panel>
  );
}
