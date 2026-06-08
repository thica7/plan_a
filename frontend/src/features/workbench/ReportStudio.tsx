import { CheckCircle2, Database, Download, FileText, ShieldCheck, XCircle } from "lucide-react";
import type {
  ArtifactRecord,
  EvidenceRecord,
  ReportReleaseGate,
  ReportVersionRecord,
} from "../../api/types";
import { EmptyState, LoadingState, Panel, StatusPill } from "../../components/ui";
import { ReportView } from "../report/ReportView";
import type { ReportSourceBundle } from "../report/sourceBundle";
import { formatDate } from "./format";
import type { ReportAction, ReportExportFormat } from "./reportOperations";

interface ReportStudioProps {
  evidenceById: Map<string, EvidenceRecord>;
  isPending: boolean;
  lastExport: ArtifactRecord | null;
  onExport: (format: ReportExportFormat) => void;
  onReportAction: (action: ReportAction) => void;
  releaseGate: ReportReleaseGate | null;
  reportSources: ReportSourceBundle;
  selectedVersion: ReportVersionRecord | null;
  selectedVersionId: string | null;
  setSelectedVersionId: (versionId: string) => void;
  versions: ReportVersionRecord[];
}

export function ReportStudio({
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
}: ReportStudioProps) {
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
