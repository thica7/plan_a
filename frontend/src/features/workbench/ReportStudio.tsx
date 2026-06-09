import { useEffect, useMemo, useState } from "react";
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
import { EmptyState } from "../../components/ui";
import { ReportView } from "../report/ReportView";
import type { ReportSourceBundle } from "../report/sourceBundle";
import { ReportReleasePanel } from "./ReportReleasePanel";
import { ReportReviewDesk } from "./ReportReviewDesk";
import { ReportVersionPanel } from "./ReportVersionPanel";
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
    <div className="report-studio-workbench">
      <div className="report-command-row">
        <ReportVersionPanel
          onSelectReport={onSelectReport}
          selectedVersionId={selectedVersionId}
          setSelectedVersionId={setSelectedVersionId}
          versions={versions}
        />
        <ReportReleasePanel
          isPending={isPending}
          lastExport={lastExport}
          onExport={onExport}
          onReportAction={onReportAction}
          releaseGate={releaseGate}
          selectedVersion={selectedVersion}
        />
      </div>

      <div className="report-reading-grid">
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

        <ReportReviewDesk
          diff={diff}
          evidenceById={evidenceById}
          isDiffLoading={isDiffLoading}
          onEvidenceQuality={onEvidenceQuality}
          onSelectClaim={onSelectClaim}
          onSelectEvidence={onSelectEvidence}
          previousVersion={previousVersion}
          releaseGate={releaseGate}
          scopedClaims={scopedClaims}
          selectedVersion={selectedVersion}
        />
      </div>
    </div>
  );
}
