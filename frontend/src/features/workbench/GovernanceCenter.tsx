import { CalendarClock } from "lucide-react";
import type {
  AuditLogRecord,
  DataRetentionReport,
  ModelPolicyReport,
  ModelRouteDecision,
  QualityAgentMatrix,
  SourceRegistryRecord,
  WorkspaceQuotaDecision,
  WorkspaceUsageSummary,
} from "../../api/types";
import { Panel } from "../../components/ui";
import { AuditTrail } from "./AuditTrail";
import { RuntimePolicyPanel } from "./RuntimePolicyPanel";
import { SourceRegistryPanel } from "./SourceRegistryPanel";
import { WorkspaceUsagePanel } from "./WorkspaceUsagePanel";

interface GovernanceCenterProps {
  auditLogs: AuditLogRecord[];
  matrix: QualityAgentMatrix | null;
  modelPolicy: ModelPolicyReport | null;
  modelRoute: ModelRouteDecision | null;
  quota: WorkspaceQuotaDecision | null;
  registry: SourceRegistryRecord[];
  retention: DataRetentionReport | null;
  usage: WorkspaceUsageSummary | null;
}

export function GovernanceCenter({
  auditLogs,
  matrix,
  modelPolicy,
  modelRoute,
  quota,
  registry,
  retention,
  usage,
}: GovernanceCenterProps) {
  return (
    <div className="governance-workbench">
      <div className="governance-summary-row">
        <RuntimePolicyPanel matrix={matrix} modelPolicy={modelPolicy} modelRoute={modelRoute} quota={quota} />
        <WorkspaceUsagePanel quota={quota} retention={retention} usage={usage} />
      </div>

      <div className="governance-detail-grid">
        <SourceRegistryPanel registry={registry} />
        <Panel className="governance-audit-panel" title="Audit trail" icon={<CalendarClock size={16} aria-hidden />}>
          <AuditTrail logs={auditLogs} />
        </Panel>
      </div>
    </div>
  );
}
