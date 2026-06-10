import { AlertTriangle, ArrowRight, Database, FileText, GitBranch, RefreshCw, ShieldCheck } from "lucide-react";

import type { DecisionReplayReport, RunDetail as RunDetailRecord, RunQualityComparison } from "../../api/types";
import type { RunEvent } from "../../api/sse_types";
import { MetricCard, Panel, StatusPill } from "../../components/ui";
import type { ReportSourceBundle } from "../report/sourceBundle";
import { SwimlaneView } from "../swimlane/SwimlaneView";
import type { ReflectionItem, RunDetailView } from "./types";
import { useTranslation } from "../../stores/i18n";
import { parseUTC } from "../workbench/format";

interface RunReviewOverviewProps {
  decisionReplay: DecisionReplayReport | null;
  detail: RunDetailRecord;
  events: RunEvent[];
  isRedoing: boolean;
  onRedo: () => void;
  onViewChange: (view: RunDetailView) => void;
  qualityComparison: RunQualityComparison | null;
  redoLimitReached: boolean;
  reflectionItems: ReflectionItem[];
  reportSources: ReportSourceBundle;
}

export function RunReviewOverview({
  decisionReplay,
  detail,
  events,
  isRedoing,
  onRedo,
  onViewChange,
  qualityComparison,
  redoLimitReached,
  reflectionItems,
  reportSources,
}: RunReviewOverviewProps) {
  const { t } = useTranslation();
  const verifiedRate = Math.round(detail.metrics.verified_source_rate * 100);
  const sourceCoverage = Math.round(detail.metrics.source_coverage_rate * 100);
  const citedClaimRate = Math.round(detail.metrics.claim_citation_rate * 100);
  const qualityScore = qualityComparison?.target_score ?? deriveRunScore(detail);
  const timelineRows = buildTimelineRows(detail, decisionReplay, events);

  return (
    <div className="run-review-overview">
      <main className="run-review-main">
        <div className="run-review-score-grid">
          <Panel className="run-review-card" title={t('runQuality.title')} icon={<ShieldCheck size={16} aria-hidden />}>
            <strong className="run-review-score">{qualityScore}</strong>
            <StatusPill tone={qualityTone(qualityComparison?.verdict, qualityScore)}>
              {qualityComparison?.verdict ?? detail.status}
            </StatusPill>
            <div className="compact-stat-list">
              <span>
                Schema pass <strong>{Math.round(detail.metrics.schema_pass_rate * 100)}%</strong>
              </span>
              <span>
                Citation <strong>{citedClaimRate}%</strong>
              </span>
              <span>
                QA issues <strong>{detail.qa_findings.length}</strong>
              </span>
            </div>
          </Panel>

          <Panel className="run-review-card" title={t('report.evidence')} icon={<Database size={16} aria-hidden />}>
            <strong className="large-metric">
              {reportSources.sources.length}
              <span>/{detail.raw_sources.length}</span>
            </strong>
            <p className="muted-line">{verifiedRate}% verified / {sourceCoverage}% coverage</p>
            <div className="metric-grid compact">
              <MetricCard label="sources" value={detail.raw_sources.length} />
              <MetricCard label="verified" value={`${verifiedRate}%`} tone={verifiedRate >= 70 ? "good" : "warn"} />
            </div>
          </Panel>

          <Panel className="run-review-card" title={t('runTabs.report')} icon={<FileText size={16} aria-hidden />}>
            <strong className="large-metric">
              {detail.report_md.length.toLocaleString()}
              <span> chars</span>
            </strong>
            <p className="muted-line">{detail.enterprise_projection?.report_version.status ?? "run report"} / {detail.enterprise_projection?.report_version.claim_ids.length ?? 0} claims</p>
            <button className="icon-text-button" type="button" onClick={() => onViewChange("report")}>
              {t('reviewOverview.openReport')}
              <ArrowRight size={15} aria-hidden />
            </button>
          </Panel>
        </div>

        <Panel className="run-flow-panel" title={t('reviewOverview.agentGraph')} icon={<GitBranch size={16} aria-hidden />}>
          <SwimlaneView
            currentNode={detail.current_node}
            events={events}
            spans={detail.trace_spans}
            status={detail.status}
          />
        </Panel>

        <div className="run-review-lower-grid">
          <Panel
            className="run-review-card"
            title="QA focus"
            icon={<AlertTriangle size={16} aria-hidden />}
            actions={
              <button className="icon-text-button" disabled={isRedoing || redoLimitReached} type="button" onClick={onRedo}>
                <RefreshCw size={15} aria-hidden />
                {isRedoing ? "Redoing" : "Redo"}
              </button>
            }
          >
            <div className="recommendation-list compact">
              {detail.qa_findings.slice(0, 4).map((issue) => (
                <article className={`recommendation-card ${issue.severity}`} key={issue.id}>
                  <strong>{issue.detected_by} / {issue.field_path}</strong>
                  <p>{issue.problem}</p>
                </article>
              ))}
              {detail.qa_findings.length === 0 ? <p className="muted-line">No active QA findings.</p> : null}
            </div>
            {reflectionItems.length > 0 ? (
              <div className="auto-redo-strip">
                <span>{t('reviewOverview.reflection')}</span>
                <strong>{reflectionItems.length}</strong>
                <span>{reflectionItems[0]?.text}</span>
              </div>
            ) : null}
          </Panel>

          <Panel className="run-review-card" title="Decision timeline" icon={<GitBranch size={16} aria-hidden />}>
            <div className="activity-timeline compact">
              {timelineRows.map((row) => (
                <article key={row.id}>
                  <i aria-hidden />
                  <div>
                    <strong>{row.title}</strong>
                    <span>{row.meta}</span>
                  </div>
                  <time dateTime={row.time}>{formatTime(row.time)}</time>
                </article>
              ))}
            </div>
            <button className="icon-text-button full-width" type="button" onClick={() => onViewChange("agents")}>
              {t('reviewOverview.openTrace')}
              <ArrowRight size={15} aria-hidden />
            </button>
          </Panel>
        </div>
      </main>

      <aside className="run-review-side-rail">
        <Panel title="Review shortcuts">
          <div className="action-grid">
            <button className="icon-text-button" type="button" onClick={() => onViewChange("report")}>
              <FileText size={15} aria-hidden />
              {t('runTabs.report')}
            </button>
            <button className="icon-text-button" type="button" onClick={() => onViewChange("agents")}>
              <GitBranch size={15} aria-hidden />
              Trace
            </button>
            <button className="icon-text-button" type="button" onClick={() => onViewChange("quality")}>
              <ShieldCheck size={15} aria-hidden />
              Quality
            </button>
          </div>
        </Panel>

        <Panel title="Cited sources" icon={<Database size={16} aria-hidden />}>
          <div className="run-source-list">
            {reportSources.sources.slice(0, 8).map((source) => (
              <a href={`#source-${source.id}`} key={source.id}>
                <strong>{source.title}</strong>
                <span>{source.dimension} / {Math.round(source.confidence * 100)}%</span>
              </a>
            ))}
          </div>
        </Panel>
      </aside>
    </div>
  );
}

function deriveRunScore(detail: RunDetailRecord) {
  const source = detail.metrics.source_coverage_rate;
  const verified = detail.metrics.verified_source_rate;
  const citation = detail.metrics.claim_citation_rate;
  const schema = detail.metrics.schema_pass_rate;
  return Math.round(((source + verified + citation + schema) / 4) * 100);
}

function qualityTone(verdict: RunQualityComparison["verdict"] | undefined, score: number) {
  if (verdict === "fail" || score < 60) return "bad";
  if (verdict === "warn" || score < 80) return "warn";
  return "good";
}

function buildTimelineRows(detail: RunDetailRecord, replay: DecisionReplayReport | null, events: RunEvent[]) {
  if (replay?.events.length) {
    return replay.events.slice(-6).reverse().map((event) => ({
      id: event.id,
      title: event.event_type,
      meta: `${event.agent ?? "system"}${event.subagent ? `/${event.subagent}` : ""} / ${event.message}`,
      time: event.created_at,
    }));
  }

  if (detail.trace_spans.length) {
    return detail.trace_spans.slice(-6).reverse().map((span) => ({
      id: span.id,
      title: `${span.kind} / ${span.name}`,
      meta: `${span.agent}${span.subagent ? `/${span.subagent}` : ""} / ${span.status} / ${span.duration_ms}ms`,
      time: span.created_at,
    }));
  }

  return events.slice(-6).reverse().map((event) => ({
    id: String(event.id),
    title: event.type,
    meta: event.message,
    time: event.created_at,
  }));
}

function formatTime(value: string) {
  const date = parseUTC(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}
