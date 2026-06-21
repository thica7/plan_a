import type { BusinessQAFinding, ReportReleaseGate } from "../../api/types";
import type { KnowledgeRollbackRequest } from "../../stores/knowledgeStore";

export interface ReleaseIssueAuditRow {
  href?: string;
  label: string;
  value: string;
}

export interface ReleaseIssueRollbackTarget {
  issueId: string;
  request: KnowledgeRollbackRequest;
  selectorSummary: string;
}

export interface ReleaseIssueRedoTarget {
  issueId: string;
  issueIds: string[];
}

export interface ReleaseGateReviewTask {
  id: string;
  issue: BusinessQAFinding;
  auditRows: ReleaseIssueAuditRow[];
  claimCount: number;
  evidenceCount: number;
  phase: "kb_cleanup" | "evidence_review" | "claim_review" | "release_review";
  rollbackTarget: ReleaseIssueRollbackTarget | null;
}

export function buildReleaseGateReviewTasks(gate: ReportReleaseGate | null): ReleaseGateReviewTask[] {
  if (!gate) return [];
  return gate.issues
    .map((issue) => {
      const rollbackTarget = buildReleaseIssueRollbackTarget(issue);
      return {
        id: issue.id,
        issue,
        auditRows: buildReleaseIssueAuditRows(issue),
        claimCount: issue.claim_ids.length,
        evidenceCount: issue.evidence_ids.length,
        phase: releaseReviewPhase(issue, rollbackTarget),
        rollbackTarget,
      };
    })
    .sort((left, right) => severityRank(right.issue.severity) - severityRank(left.issue.severity));
}

export function buildReleaseIssueAuditRows(issue: BusinessQAFinding): ReleaseIssueAuditRow[] {
  const metadata = issue.metadata ?? {};
  const rows: ReleaseIssueAuditRow[] = [];
  const issueTypes = metadataStringList(metadata["claim_validation_issue_types"]);
  const conflictIds = metadataStringList(metadata["conflicting_evidence_ids"]);
  if (issueTypes.length > 0) {
    rows.push({ label: "Claim issue", value: issueTypes.join(", ") });
  }
  if (conflictIds.length > 0) {
    rows.push({ label: "Conflict evidence", value: conflictIds.join(", ") });
  }
  const claimArea = metadataText(metadata, "claim_area");
  if (claimArea) {
    rows.push({ label: "Conflict fact", value: claimArea });
  }
  const freshnessRow = buildFreshnessGateRow(metadata);
  if (freshnessRow) {
    rows.push(freshnessRow);
  }
  for (const pair of metadataObjectList(metadata["source_evidence_pairs"]).slice(0, 2)) {
    const pairRow = buildEvidencePairRow(pair);
    if (pairRow) rows.push(pairRow);
  }

  const trail = metadataObjectList(metadata["evidence_audit_trail"]);
  for (const item of trail.slice(0, 2)) {
    const evidenceId = metadataText(item, "evidence_id");
    const rawSourceId = metadataText(item, "raw_source_id");
    const kbDocumentId = metadataText(item, "kb_document_id");
    const kbVersion = metadataText(item, "kb_document_version");
    const kbStatus = metadataText(item, "kb_document_status");
    const kbRawSourceId = metadataText(item, "kb_raw_source_id");
    const collectorRunId = metadataText(item, "kb_collector_run_id");
    const freshnessScore = metadataNumber(item, "kb_freshness_score");

    if (evidenceId || rawSourceId) {
      rows.push({ label: "Evidence", value: [evidenceId, rawSourceId].filter(Boolean).join(" / ") });
    }
    if (kbDocumentId) {
      rows.push({
        label: "KB document",
        value: [kbDocumentId, kbVersion ? `v${kbVersion}` : "", kbStatus].filter(Boolean).join(" / "),
        href: knowledgeLocatorHref({
          chunkId: metadataText(item, "kb_chunk_id"),
          documentId: kbDocumentId,
          rawSourceId: kbRawSourceId || rawSourceId,
        }),
      });
    }
    if (kbRawSourceId) {
      rows.push({
        label: "KB raw source",
        value: kbRawSourceId,
        href: knowledgeLocatorHref({ rawSourceId: kbRawSourceId }),
      });
    }
    if (collectorRunId) {
      rows.push({ label: "Collector run", value: collectorRunId });
    }
    if (freshnessScore !== null) {
      rows.push({ label: "Freshness", value: `${Math.round(freshnessScore * 100)}%` });
    }
  }

  return rows.slice(0, 10);
}

function buildFreshnessGateRow(metadata: Record<string, unknown>): ReleaseIssueAuditRow | null {
  const ageDays = metadataNumber(metadata, "source_age_days");
  const policyDays = metadataNumber(metadata, "freshness_policy_days");
  const basis = metadataText(metadata, "freshness_basis");
  if (ageDays === null && policyDays === null && !basis) return null;
  const parts = [
    ageDays !== null ? `${ageDays}d old` : "",
    policyDays !== null ? `${policyDays}d policy` : "",
    basis ?? "",
  ].filter(Boolean);
  return { label: "Freshness gate", value: parts.join(" / ") };
}

function buildEvidencePairRow(pair: Record<string, unknown>): ReleaseIssueAuditRow | null {
  const kbSourceId = metadataText(pair, "kb_source_id");
  const kbPosition = metadataText(pair, "kb_position");
  const kbDocumentId = metadataText(pair, "kb_document_id");
  const kbChunkId = metadataText(pair, "kb_chunk_id");
  const liveSourceId = metadataText(pair, "live_source_id");
  const livePosition = metadataText(pair, "live_position");
  if (!kbSourceId && !liveSourceId) return null;
  const kb = [kbSourceId, kbPosition ? `(${kbPosition})` : "", kbDocumentId ? `[${kbDocumentId}]` : ""]
    .filter(Boolean)
    .join(" ");
  const live = [liveSourceId, livePosition ? `(${livePosition})` : ""].filter(Boolean).join(" ");
  return {
    href: knowledgeLocatorHref({ chunkId: kbChunkId, documentId: kbDocumentId, rawSourceId: kbSourceId }),
    label: "Evidence pair",
    value: `${kb || "KB source"} vs ${live || "live source"}`,
  };
}

function knowledgeLocatorHref({
  chunkId,
  documentId,
  rawSourceId,
}: {
  chunkId?: string | null;
  documentId?: string | null;
  rawSourceId?: string | null;
}): string | undefined {
  const params = new URLSearchParams();
  if (documentId) params.set("document_id", documentId);
  if (chunkId) params.set("chunk_id", chunkId);
  if (rawSourceId) params.set("raw_source_id", rawSourceId);
  const query = params.toString();
  return query ? `/knowledge?${query}` : undefined;
}

export function buildReleaseIssueRollbackTarget(issue: BusinessQAFinding): ReleaseIssueRollbackTarget | null {
  const metadata = issue.metadata ?? {};
  const trail = metadataObjectList(metadata["evidence_audit_trail"]);
  const documentIds = uniqueStrings(
    trail.map((item) => metadataText(item, "kb_document_id")).filter((item): item is string => Boolean(item)),
  );
  if (documentIds.length > 0) {
    return {
      issueId: issue.id,
      request: { document_ids: documentIds, restore_previous: true },
      selectorSummary: documentIds.length === 1 ? documentIds[0] : `${documentIds.length} KB documents`,
    };
  }

  const rawSourceId = firstMetadataText(trail, "kb_raw_source_id");
  if (rawSourceId) {
    return {
      issueId: issue.id,
      request: { raw_source_id: rawSourceId, restore_previous: true },
      selectorSummary: `raw source ${rawSourceId}`,
    };
  }

  const collectorRunId = firstMetadataText(trail, "kb_collector_run_id");
  if (collectorRunId) {
    return {
      issueId: issue.id,
      request: { run_id: collectorRunId, restore_previous: true },
      selectorSummary: `collector run ${collectorRunId}`,
    };
  }

  return null;
}

export function buildReleaseIssueRedoTarget(issue: BusinessQAFinding): ReleaseIssueRedoTarget {
  const metadata = issue.metadata ?? {};
  const issueIds = uniqueStrings([issue.id, metadataText(metadata, "run_qa_finding_id") ?? ""]);
  return {
    issueId: issue.id,
    issueIds,
  };
}

export function releaseReviewPhaseLabel(phase: ReleaseGateReviewTask["phase"]): string {
  return {
    claim_review: "Claim review",
    evidence_review: "Evidence review",
    kb_cleanup: "KB cleanup",
    release_review: "Release review",
  }[phase];
}

function releaseReviewPhase(
  issue: BusinessQAFinding,
  rollbackTarget: ReleaseIssueRollbackTarget | null,
): ReleaseGateReviewTask["phase"] {
  if (rollbackTarget) return "kb_cleanup";
  const issueKey = `${issue.rule_id} ${issue.message}`.toLowerCase();
  if (issueKey.includes("claim") || issue.claim_ids.length > 0) return "claim_review";
  if (issueKey.includes("evidence") || issue.evidence_ids.length > 0) return "evidence_review";
  return "release_review";
}

function severityRank(severity: BusinessQAFinding["severity"]): number {
  return {
    blocker: 3,
    warn: 2,
    info: 1,
  }[severity];
}

function firstMetadataText(items: Record<string, unknown>[], key: string): string | null {
  for (const item of items) {
    const value = metadataText(item, key);
    if (value) return value;
  }
  return null;
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))];
}

function metadataObjectList(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item),
  );
}

function metadataStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || "").trim()).filter(Boolean);
}

function metadataText(metadata: Record<string, unknown>, key: string): string | null {
  const value = metadata[key];
  if (value === null || value === undefined || value === "") return null;
  return String(value);
}

function metadataNumber(metadata: Record<string, unknown>, key: string): number | null {
  const value = metadata[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
