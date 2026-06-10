import type {
  ArtifactRecord,
  AgentMessage,
  DecisionReplayReport,
  RunComplianceReport,
  RunDetail as RunDetailRecord,
  RunQualityComparison,
  RunSummary,
  ToolCallMessage,
  TraceSpan,
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
import { useTranslation } from "../../stores/i18n";

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
  traceSpans: TraceSpan[] | null;
  agentMessages: AgentMessage[] | null;
  toolCallMessages: ToolCallMessage[] | null;
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
  traceSpans,
  agentMessages,
  toolCallMessages,
}: RunDetailContentProps) {
  const { t } = useTranslation();
  const renderedTraceSpans = traceSpans ?? detail.trace_spans;
  const renderedAgentMessages = agentMessages ?? detail.agent_messages;
  const renderedToolCallMessages = toolCallMessages ?? detail.tool_call_messages;
  if (activeView === "report") {
    return <RunReportReviewStudio detail={detail} reportSources={reportSources} />;
  }

  if (activeView === "agents") {
    return (
      <div className="detail-grid agents-detail-grid">
        <TracePlayback spans={renderedTraceSpans} />
        <AgentMessagesView messages={renderedAgentMessages} toolCalls={renderedToolCallMessages} />
        <TraceList
          events={events}
          metrics={detail.metrics}
          replay={decisionReplay}
          spans={renderedTraceSpans}
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
