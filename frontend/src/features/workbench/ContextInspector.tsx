import type { ClaimRecord, EvidenceRecord, ReportVersionRecord } from "../../api/types";
import { EmptyState, StatusPill } from "../../components/ui";
import { formatPercent, reportStatusTone } from "./format";

export type InspectorTab = "source" | "claim" | "report";

export function ContextInspector({
  claim,
  evidence,
  report,
  selectedTab,
  setSelectedTab,
}: {
  claim: ClaimRecord | null;
  evidence: EvidenceRecord | null;
  report: ReportVersionRecord | null;
  selectedTab: InspectorTab;
  setSelectedTab: (tab: InspectorTab) => void;
}) {
  return (
    <aside className="concept-inspector">
      <div className="inspector-tabs">
        {(["source", "claim", "report"] as const).map((tab) => (
          <button
            className={selectedTab === tab ? "active" : ""}
            key={tab}
            type="button"
            onClick={() => setSelectedTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>
      {selectedTab === "source" ? <SourceInspector evidence={evidence} /> : null}
      {selectedTab === "claim" ? <ClaimInspector claim={claim} /> : null}
      {selectedTab === "report" ? <ReportInspector report={report} /> : null}
    </aside>
  );
}

function SourceInspector({ evidence }: { evidence: EvidenceRecord | null }) {
  if (!evidence) return <EmptyState title="No source selected" />;
  return (
    <div className="inspector-body">
      <StatusPill tone={evidence.quality_label === "accepted" ? "good" : "warn"}>{evidence.quality_label}</StatusPill>
      <h3>{evidence.title}</h3>
      {evidence.url ? (
        <a href={evidence.url} target="_blank" rel="noreferrer">
          {evidence.url}
        </a>
      ) : null}
      <code>{evidence.raw_source_id}</code>
      <div className="inspector-meta-grid">
        <span>
          Type <strong>{evidence.source_type}</strong>
        </span>
        <span>
          Dimension <strong>{evidence.dimension}</strong>
        </span>
        <span>
          Reliability <strong>{formatPercent(evidence.reliability_score)}</strong>
        </span>
        <span>
          Freshness <strong>{formatPercent(evidence.freshness_score)}</strong>
        </span>
      </div>
      <section className="snapshot-box">
        <strong>Snapshot</strong>
        <p>{evidence.snippet}</p>
      </section>
    </div>
  );
}

function ClaimInspector({ claim }: { claim: ClaimRecord | null }) {
  if (!claim) return <EmptyState title="No claim selected" />;
  return (
    <div className="inspector-body">
      <StatusPill tone={claim.status === "accepted" ? "good" : claim.status === "rejected" ? "bad" : "neutral"}>
        {claim.status}
      </StatusPill>
      <h3>{claim.claim_type}</h3>
      <p>{claim.claim_text}</p>
      <div className="inspector-meta-grid">
        <span>
          Confidence <strong>{formatPercent(claim.confidence)}</strong>
        </span>
        <span>
          Evidence <strong>{claim.evidence_ids.length}</strong>
        </span>
        <span>
          Agent <strong>{claim.created_by_agent ?? "unknown"}</strong>
        </span>
      </div>
      <div className="linked-chip-list">
        {claim.evidence_ids.slice(0, 6).map((id) => (
          <span key={id}>{id}</span>
        ))}
      </div>
    </div>
  );
}

function ReportInspector({ report }: { report: ReportVersionRecord | null }) {
  if (!report) return <EmptyState title="No report selected" />;
  return (
    <div className="inspector-body">
      <StatusPill tone={reportStatusTone(report.status)}>{report.status}</StatusPill>
      <h3>Report v{report.version_number}</h3>
      <div className="inspector-meta-grid">
        <span>
          Claims <strong>{report.claim_ids.length}</strong>
        </span>
        <span>
          Evidence <strong>{report.evidence_ids.length}</strong>
        </span>
        <span>
          Size <strong>{report.report_md.length.toLocaleString()}</strong>
        </span>
      </div>
      <section className="snapshot-box">
        <strong>Preview</strong>
        <p>{report.report_md.slice(0, 420)}</p>
      </section>
    </div>
  );
}
