import { AlertTriangle, ArrowRight, Database, FileText, GitBranch, RefreshCw, ShieldCheck } from "lucide-react";
import { useContext } from "react";
import { Link, UNSAFE_LocationContext, UNSAFE_NavigationContext } from "react-router-dom";

import type { DecisionReplayReport, RunDetail as RunDetailRecord, RunQualityComparison } from "../../api/types";
import type { RunEvent } from "../../api/sse_types";
import { MetricCard, Panel, StatusPill } from "../../components/ui";
import type { ReportSourceBundle } from "../report/sourceBundle";
import { SwimlaneView } from "../swimlane/SwimlaneView";
import { AgentHandoffSummary } from "./AgentHandoffSummary";
import type { ReflectionItem, RunDetailView } from "./types";
import { useTranslation, type Locale } from "../../stores/i18n";
import { displayLabel, displayScope, runtimeDiagnostic } from "../../i18n/display";
import { SystemMessage } from "../../i18n/SystemMessage";
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
  const { locale, t } = useTranslation();
  const routing = useContext(UNSAFE_NavigationContext);
  const location = useContext(UNSAFE_LocationContext)?.location;
  const reportQuery = new URLSearchParams(location?.search);
  reportQuery.set('view', 'report');
  const verifiedRate = Math.round(detail.metrics.verified_source_rate * 100);
  const sourceCoverage = Math.round(detail.metrics.source_coverage_rate * 100);
  const citedClaimRate = Math.round(detail.metrics.claim_citation_rate * 100);
  const qualityScore = qualityComparison?.target_score ?? deriveRunScore(detail);
  const timelineRows = buildTimelineRows(detail, decisionReplay, events, locale);

  return (
    <div className="run-review-overview">
      <main className="run-review-main">
        <div className="run-review-score-grid">
          <Panel className="run-review-card" title={t('runQuality.title')} icon={<ShieldCheck size={16} aria-hidden />}>
            <strong className="run-review-score">{qualityScore}</strong>
            <StatusPill tone={qualityTone(qualityComparison?.verdict, qualityScore)}>
              {displayLabel(qualityComparison?.verdict ?? detail.status, locale)}
            </StatusPill>
            <div className="compact-stat-list">
              <span>
                {t('reviewOverview.schemaPass')} <strong>{Math.round(detail.metrics.schema_pass_rate * 100)}%</strong>
              </span>
              <span>
                {t('reviewOverview.citation')} <strong>{citedClaimRate}%</strong>
              </span>
              <span>
                {t('reviewOverview.qaIssues')} <strong>{detail.qa_findings.length}</strong>
              </span>
            </div>
          </Panel>

          <Panel className="run-review-card" title={t('report.evidence')} icon={<Database size={16} aria-hidden />}>
            <strong className="large-metric">
              {reportSources.sources.length}
              <span>/{detail.raw_sources.length}</span>
            </strong>
            <p className="muted-line">{verifiedRate}% {t('summary.verified')} / {sourceCoverage}% {t('summary.coverage')}</p>
            <div className="metric-grid compact">
              <MetricCard label={t('reportStatus.sources')} value={detail.raw_sources.length} />
              <MetricCard label={t('summary.verified')} value={`${verifiedRate}%`} tone={verifiedRate >= 70 ? "good" : "warn"} />
            </div>
          </Panel>

          <Panel className="run-review-card" title={t('runTabs.report')} icon={<FileText size={16} aria-hidden />}>
            <strong className="large-metric">
              {detail.report_md.length.toLocaleString()}
              <span> {t('summary.characters')}</span>
            </strong>
            <p className="muted-line">{detail.enterprise_projection ? displayLabel(detail.enterprise_projection.report_version.status, locale) : t('reviewOverview.runReport')} / {detail.enterprise_projection?.report_version.claim_ids.length ?? 0} {t('reportStatus.claims')}</p>
            <button className="icon-text-button" type="button" onClick={() => onViewChange("report")}>
              {t('reviewOverview.openReport')}
              <ArrowRight size={15} aria-hidden />
            </button>
          </Panel>
        </div>

        <AgentHandoffSummary detail={detail} messages={detail.agent_messages} mode="compact" />

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
            title={t('reviewOverview.qaFocus')}
            icon={<AlertTriangle size={16} aria-hidden />}
            actions={
              <button className="icon-text-button" disabled={isRedoing || redoLimitReached} type="button" onClick={onRedo}>
                <RefreshCw size={15} aria-hidden />
                {isRedoing ? t('reviewOverview.redoing') : t('runQa.redo')}
              </button>
            }
          >
            <div className="recommendation-list compact">
              {detail.qa_findings.slice(0, 4).map((issue) => (
                <article className={`recommendation-card ${issue.severity}`} key={issue.id}>
                  <strong>{displayLabel(issue.detected_by, locale)} / {issue.field_path}</strong>
                  <p><SystemMessage message={issue.problem} /></p>
                </article>
              ))}
              {detail.qa_findings.length === 0 ? <p className="muted-line">{t('reviewOverview.noActiveQa')}</p> : null}
            </div>
            {reflectionItems.length > 0 ? (
              <div className="auto-redo-strip">
                <span>{t('reviewOverview.reflection')}</span>
                <strong>{reflectionItems.length}</strong>
                <span>{reflectionItems[0]?.text}</span>
              </div>
            ) : null}
          </Panel>

          <Panel className="run-review-card" title={t('reviewOverview.decisionTimeline')} icon={<GitBranch size={16} aria-hidden />}>
            <div className="activity-timeline compact">
              {timelineRows.map((row) => (
                <article key={row.id}>
                  <i aria-hidden />
                  <div>
                    <strong>{row.title}</strong>
                    <span>{row.meta}</span>
                  </div>
                  <time dateTime={row.time}>{formatTime(row.time, locale)}</time>
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
        <Panel title={t('reviewOverview.reviewShortcuts')}>
          <div className="action-grid">
            <button className="icon-text-button" type="button" onClick={() => onViewChange("report")}>
              <FileText size={15} aria-hidden />
              {t('runTabs.report')}
            </button>
            <button className="icon-text-button" type="button" onClick={() => onViewChange("agents")}>
              <GitBranch size={15} aria-hidden />
              {t('trace.title')}
            </button>
            <button className="icon-text-button" type="button" onClick={() => onViewChange("quality")}>
              <ShieldCheck size={15} aria-hidden />
              {t('runTabs.quality')}
            </button>
          </div>
        </Panel>

        <Panel title={t('reviewOverview.citedSources')} icon={<Database size={16} aria-hidden />}>
          <div className="run-source-list">
            {reportSources.sources.slice(0, 8).map((source) => {
              const href = `/runs/${encodeURIComponent(detail.id)}?${reportQuery.toString()}#source-${encodeURIComponent(source.id)}`;
              const content = <><strong>{source.title}</strong><span>{displayLabel(source.dimension, locale)} / {Math.round(source.confidence * 100)}%</span></>;
              return routing ? <Link to={href} key={source.id}>{content}</Link> : <a href={href} key={source.id}>{content}</a>;
            })}
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

function buildTimelineRows(detail: RunDetailRecord, replay: DecisionReplayReport | null, events: RunEvent[], locale: Locale) {
  if (replay?.events.length) {
    return replay.events.slice(-6).reverse().map((event) => ({
      id: event.id,
      title: displayLabel(event.event_type, locale),
      meta: `${displayLabel(event.agent ?? "system", locale)}${event.subagent ? `/${displayScope(event.subagent, locale)}` : ""} / ${runtimeDiagnostic(event.message, locale)}`,
      time: event.created_at,
    }));
  }

  if (detail.trace_spans.length) {
    return detail.trace_spans.slice(-6).reverse().map((span) => ({
      id: span.id,
      title: `${displayLabel(span.kind, locale)} / ${displayLabel(span.name, locale)}`,
      meta: `${displayLabel(span.agent, locale)}${span.subagent ? `/${displayScope(span.subagent, locale)}` : ""} / ${displayLabel(span.status, locale)} / ${span.duration_ms}${locale === 'zh-CN' ? '毫秒' : 'ms'}`,
      time: span.created_at,
    }));
  }

  return events.slice(-6).reverse().map((event) => ({
    id: String(event.id),
    title: displayLabel(event.type, locale),
    meta: runtimeDiagnostic(event.message, locale),
    time: event.created_at,
  }));
}

function formatTime(value: string, locale: Locale) {
  const date = parseUTC(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale, { hour12: false });
}
