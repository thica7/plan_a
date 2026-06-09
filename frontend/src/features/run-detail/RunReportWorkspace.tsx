import type { RunDetail as RunDetailRecord } from "../../api/types";
import { MetricCard } from "../../components/ui";
import { ReportView } from "../report/ReportView";
import type { ReportSourceBundle } from "../report/sourceBundle";
import { RevisionDiff } from "../revisions/RevisionDiff";

interface RunReportWorkspaceProps {
  detail: RunDetailRecord;
  reportSources: ReportSourceBundle;
}

export function RunReportWorkspace({ detail, reportSources }: RunReportWorkspaceProps) {
  const markdown = detail.report_md ?? "";
  const wordCount = markdown.trim() ? markdown.trim().split(/\s+/).length : 0;
  const citedSourceCount = reportSources.sources.length;
  const revisionCount = detail.revisions.length;
  const blockerCount = detail.qa_findings.filter((finding) => finding.severity === "blocker").length;

  return (
    <div className="run-report-workspace">
      <div className="run-report-summary-row">
        <MetricCard label="Report words" value={wordCount.toLocaleString()} />
        <MetricCard label="Traceable sources" value={citedSourceCount} tone={citedSourceCount ? "good" : "warn"} />
        <MetricCard label="Revision loops" value={revisionCount} />
        <MetricCard label="QA blockers" value={blockerCount} tone={blockerCount ? "warn" : "good"} />
      </div>

      <ReportView
        layout="reader"
        markdown={markdown}
        sourceAliases={reportSources.aliases}
        sources={reportSources.sources}
      />

      <RevisionDiff compact revisions={detail.revisions} />
    </div>
  );
}
