import type {
  ArtifactRecord,
  DecisionReplayReport,
  RunComplianceReport,
  RunDetail as RunDetailRecord,
  RunQualityComparison,
  RunSummary,
} from "../../api/types";
import { CompetitorDiscoveryView } from "../discovery/CompetitorDiscoveryView";
import { CostPanel } from "../cost/CostPanel";
import { StaticGraphView } from "../graph/StaticGraphView";
import { KbMatrixView } from "../kb/KbMatrixView";
import { AgentMessagesView } from "../messages/AgentMessagesView";
import { ReportView } from "../report/ReportView";
import type { ReportSourceBundle } from "../report/sourceBundle";
import { RevisionDiff } from "../revisions/RevisionDiff";
import { SwimlaneView } from "../swimlane/SwimlaneView";
import { TraceList } from "../trace/TraceList";
import { TracePlayback } from "../trace/TracePlayback";
import type { RunEvent } from "../../api/sse_types";
import { CompliancePanel } from "./CompliancePanel";
import { RunQaPanel } from "./RunQaPanel";
import { RunQualityPanel } from "./RunQualityPanel";
import { TaskDecompositionPanel } from "./TaskDecompositionPanel";
import type { ReflectionItem, RunDetailView } from "./types";

interface RunDetailContentProps {
  activeView: RunDetailView;
  complianceExport: ArtifactRecord | null;
  complianceReport: RunComplianceReport | null;
  decisionReplay: DecisionReplayReport | null;
  detail: RunDetailRecord;
  events: RunEvent[];
  isExportingCompliance: boolean;
  isRedoing: boolean;
  onBaselineRunChange: (runId: string) => void;
  onExportCompliance: () => void;
  onRedo: () => void;
  qualityBaselineRunId: string;
  qualityComparison: RunQualityComparison | null;
  redoLimitReached: boolean;
  reflectionItems: ReflectionItem[];
  reportSources: ReportSourceBundle;
  runHistory: RunSummary[];
}

export function RunDetailContent({
  activeView,
  complianceExport,
  complianceReport,
  decisionReplay,
  detail,
  events,
  isExportingCompliance,
  isRedoing,
  onBaselineRunChange,
  onExportCompliance,
  onRedo,
  qualityBaselineRunId,
  qualityComparison,
  redoLimitReached,
  reflectionItems,
  reportSources,
  runHistory,
}: RunDetailContentProps) {
  if (activeView === "report") {
    return (
      <div className="detail-grid report-detail-grid">
        <ReportView
          markdown={detail.report_md}
          sourceAliases={reportSources.aliases}
          sources={reportSources.sources}
        />
        <RevisionDiff revisions={detail.revisions} />
      </div>
    );
  }

  if (activeView === "agents") {
    return (
      <div className="detail-grid agents-detail-grid">
        <TracePlayback spans={detail.trace_spans} />
        <AgentMessagesView messages={detail.agent_messages} toolCalls={detail.tool_call_messages} />
        <TraceList
          events={events}
          metrics={detail.metrics}
          replay={decisionReplay}
          spans={detail.trace_spans}
        />
      </div>
    );
  }

  if (activeView === "quality") {
    return (
      <div className="detail-grid">
        <RunQaPanel
          detail={detail}
          isRedoing={isRedoing}
          onRedo={onRedo}
          redoLimitReached={redoLimitReached}
          reflectionItems={reflectionItems}
        />
        <RunQualityPanel
          baselineRunId={qualityBaselineRunId}
          comparison={qualityComparison}
          onBaselineRunChange={onBaselineRunChange}
          runHistory={runHistory}
        />
        <CompliancePanel
          exportArtifact={complianceExport}
          isExporting={isExportingCompliance}
          onExport={onExportCompliance}
          report={complianceReport}
        />
        <CostPanel metrics={detail.metrics} spans={detail.trace_spans} />
      </div>
    );
  }

  return (
    <div className="detail-grid">
      <SwimlaneView
        currentNode={detail.current_node}
        events={events}
        spans={detail.trace_spans}
        status={detail.status}
      />
      <StaticGraphView
        activeNode={detail.current_node}
        competitors={detail.plan.competitors}
        dimensions={detail.plan.dimensions}
        events={events}
        revisionCount={detail.revisions.length}
        status={detail.status}
      />
      <CompetitorDiscoveryView discovery={detail.competitor_discovery} />
      <TaskDecompositionPanel tasks={detail.plan.task_decomposition} />
      <KbMatrixView
        kbs={detail.competitor_kbs}
        knowledge={detail.competitor_knowledge}
        matrix={detail.comparison_matrix}
        sources={detail.raw_sources}
      />
    </div>
  );
}
