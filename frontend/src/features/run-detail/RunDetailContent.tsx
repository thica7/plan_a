import type {
  ArtifactRecord,
  DecisionReplayReport,
  RunComplianceReport,
  RunDetail as RunDetailRecord,
  RunQualityComparison,
  RunSummary,
} from "../../api/types";
import { CostPanel } from "../cost/CostPanel";
import { AgentMessagesView } from "../messages/AgentMessagesView";
import type { ReportSourceBundle } from "../report/sourceBundle";
import { TraceList } from "../trace/TraceList";
import { TracePlayback } from "../trace/TracePlayback";
import type { RunEvent } from "../../api/sse_types";
import { CompliancePanel } from "./CompliancePanel";
import { RunQaPanel } from "./RunQaPanel";
import { RunQualityPanel } from "./RunQualityPanel";
import { RunReportReviewStudio } from "./RunReportReviewStudio";
import { RunReviewOverview } from "./RunReviewOverview";
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
  onViewChange: (view: RunDetailView) => void;
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
  onViewChange,
  qualityBaselineRunId,
  qualityComparison,
  redoLimitReached,
  reflectionItems,
  reportSources,
  runHistory,
}: RunDetailContentProps) {
  if (activeView === "report") {
    return <RunReportReviewStudio detail={detail} reportSources={reportSources} />;
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
    <RunReviewOverview
      decisionReplay={decisionReplay}
      detail={detail}
      events={events}
      isRedoing={isRedoing}
      onRedo={onRedo}
      onViewChange={onViewChange}
      qualityComparison={qualityComparison}
      redoLimitReached={redoLimitReached}
      reflectionItems={reflectionItems}
      reportSources={reportSources}
    />
  );
}
