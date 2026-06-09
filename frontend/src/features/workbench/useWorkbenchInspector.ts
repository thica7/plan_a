import { useEffect, useMemo, useState } from "react";

import type { ClaimRecord, EvidenceRecord, ReportVersionRecord } from "../../api/types";
import type { InspectorTab } from "./ContextInspector";
import type { ProjectData } from "./types";

export function useWorkbenchInspector({
  data,
  selectedVersion,
}: {
  data: ProjectData;
  selectedVersion: ReportVersionRecord | null;
}) {
  const [selectedTab, setSelectedTab] = useState<InspectorTab>("source");
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);

  const evidenceById = useMemo(() => new Map(data.evidence.map((item) => [item.id, item])), [data.evidence]);
  const claimById = useMemo(() => new Map(data.claims.map((item) => [item.id, item])), [data.claims]);

  const selectedEvidence = useMemo(
    () => pickEvidence(data.evidence, evidenceById, selectedEvidenceId, selectedVersion),
    [data.evidence, evidenceById, selectedEvidenceId, selectedVersion],
  );

  const selectedClaim = useMemo(
    () => pickClaim(data.claims, claimById, selectedClaimId, selectedEvidence, selectedVersion),
    [claimById, data.claims, selectedClaimId, selectedEvidence, selectedVersion],
  );

  useEffect(() => {
    if (selectedEvidenceId && !evidenceById.has(selectedEvidenceId)) setSelectedEvidenceId(null);
  }, [evidenceById, selectedEvidenceId]);

  useEffect(() => {
    if (selectedClaimId && !claimById.has(selectedClaimId)) setSelectedClaimId(null);
  }, [claimById, selectedClaimId]);

  function inspectEvidence(evidence: EvidenceRecord) {
    setSelectedEvidenceId(evidence.id);
    const relatedClaim = data.claims.find((claim) => claim.evidence_ids.includes(evidence.id));
    if (relatedClaim) setSelectedClaimId(relatedClaim.id);
    setSelectedTab("source");
  }

  function inspectClaim(claim: ClaimRecord) {
    setSelectedClaimId(claim.id);
    const linkedEvidenceId = claim.evidence_ids.find((id) => evidenceById.has(id));
    if (linkedEvidenceId) setSelectedEvidenceId(linkedEvidenceId);
    setSelectedTab("claim");
  }

  function inspectReport(report: ReportVersionRecord | null) {
    if (!report) return;
    const linkedEvidenceId = report.evidence_ids.find((id) => evidenceById.has(id));
    const linkedClaimId = report.claim_ids.find((id) => claimById.has(id));
    if (linkedEvidenceId) setSelectedEvidenceId(linkedEvidenceId);
    if (linkedClaimId) setSelectedClaimId(linkedClaimId);
    setSelectedTab("report");
  }

  return {
    inspectClaim,
    inspectEvidence,
    inspectReport,
    selectedClaim,
    selectedEvidence,
    selectedTab,
    setSelectedTab,
  };
}

function pickEvidence(
  evidence: EvidenceRecord[],
  evidenceById: Map<string, EvidenceRecord>,
  selectedEvidenceId: string | null,
  selectedVersion: ReportVersionRecord | null,
) {
  if (selectedEvidenceId && evidenceById.has(selectedEvidenceId)) return evidenceById.get(selectedEvidenceId) ?? null;
  const scopedEvidence = selectedVersion?.evidence_ids.map((id) => evidenceById.get(id)).find(Boolean);
  return scopedEvidence ?? evidence.find((item) => item.quality_label === "accepted") ?? evidence.find((item) => item.url) ?? evidence[0] ?? null;
}

function pickClaim(
  claims: ClaimRecord[],
  claimById: Map<string, ClaimRecord>,
  selectedClaimId: string | null,
  selectedEvidence: EvidenceRecord | null,
  selectedVersion: ReportVersionRecord | null,
) {
  if (selectedClaimId && claimById.has(selectedClaimId)) return claimById.get(selectedClaimId) ?? null;
  const evidenceClaim = claims.find((claim) => selectedEvidence && claim.evidence_ids.includes(selectedEvidence.id));
  if (evidenceClaim) return evidenceClaim;
  const scopedClaim = selectedVersion?.claim_ids.map((id) => claimById.get(id)).find(Boolean);
  return scopedClaim ?? claims[0] ?? null;
}
