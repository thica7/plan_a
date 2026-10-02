import { FileText, GitBranch, ListChecks, ShieldCheck } from "lucide-react";

import type { AgentMessage, RunDetail as RunDetailRecord, TraceSpan } from "../../api/types";
import { Panel, StatusPill } from "../../components/ui";
import { useTranslation } from "../../stores/i18n";
import { displayLabel } from "../../i18n/display";

interface AgentHandoffSummaryProps {
  detail: RunDetailRecord;
  messages: AgentMessage[];
  mode?: "compact" | "full";
}

const EXPECTED_HANDOFFS = [
  ["planner", "collector_dispatch", "plan"],
  ["collector", "collect_join", "sources"],
  ["collect_join", "qa", "collection QA"],
  ["analyst", "analyst_join", "knowledge"],
  ["comparator", "reflector", "matrix"],
  ["reflector", "writer", "constraints"],
  ["writer", "qa", "report"],
] as const;

export function AgentHandoffSummary({ detail, messages, mode = "full" }: AgentHandoffSummaryProps) {
  const { locale, t } = useTranslation();
  const latestReflection = detail.reflections[detail.reflections.length - 1];
  const writerReport = latestMessage(messages, (message) => (
    message.payload_schema === "MarkdownReport" || (message.from_agent === "writer" && message.to_agent === "qa")
  ));
  const writerSpan = latestSpan(detail.trace_spans, (span) => span.agent === "writer");
  const hasReport = detail.report_md.trim().length > 0;
  const writerRepairMode = payloadString(writerReport?.payload, "writer_repair_mode")
    ?? metadataString(writerSpan, "writer_repair_mode")
    ?? (hasReport ? "none" : "pending");
  const writerMode = payloadString(writerReport?.payload, "writer_mode") ?? (hasReport ? "report ready" : "pending");
  const writerSections = payloadStringList(writerReport?.payload, "writer_repair_sections");
  const handoffs = buildHandoffRows(detail, messages);
  const stageCounts = countPlanStages(detail);
  const taskReasons = detail.plan.task_decomposition
    .map((task) => task.reason)
    .filter(Boolean)
    .slice(0, 3);
  const compact = mode === "compact";
  const history = detail.plan.report_reuse_context;
  const historyReasons = [...new Set(history?.skipped.map((item) => item.reason) ?? [])];

  return (
    <Panel
      className={`agent-handoff-summary ${compact ? "compact" : ""}`}
      title={t('handoff.title')}
      icon={<GitBranch size={16} aria-hidden />}
    >
      <div className="handoff-signal-grid">
        <SignalBlock
          label={t('handoff.layerScenario')}
          tone="neutral"
          value={`${displayLabel(detail.plan.competitor_layer, locale)} / ${displayLabel(detail.plan.scenario_id ?? "auto", locale)}`}
          detail={`${detail.plan.qa_rule_ids.length} ${t('runHeader.qaRules')} / ${detail.plan.task_decomposition.length} ${t('tasks.count')}`}
        />
        <SignalBlock
          label={t('handoff.reflectorGate')}
          tone={gateTone(latestReflection?.gate_status)}
          value={displayLabel(latestReflection?.gate_status ?? "pending", locale)}
          detail={`${latestReflection?.writer_constraints.length ?? 0} ${t('handoff.writerConstraints')}`}
        />
        <SignalBlock
          label={t('handoff.writerMode')}
          tone={writerRepairMode === "none" ? "good" : "warn"}
          value={displayLabel(writerRepairMode, locale)}
          detail={displayLabel(writerMode, locale)}
        />
      </div>

      {history && (history.selected.length > 0 || history.skipped.length > 0) ? (
        <div className="handoff-constraint-list">
          <strong>{t('handoff.historyTitle')}</strong>
          <span>{history.refresh_required.length} {t('handoff.historyLinks')} / {history.selected.length} {t('handoff.historyReports')}</span>
          <span>{t('handoff.historyRefresh')}</span>
          {historyReasons.map((reason) => <span key={reason}>{t('handoff.historySkipped')}: {historyReasonLabel(reason, locale)}</span>)}
          {history.refresh_required.length > 0 ? (
            <details>
              <summary>{t('handoff.historyDetails')}</summary>
              {history.refresh_required.map((link) => (
                <p key={`${link.report_id}-${link.evidence_id}`}>
                  <a href={link.url} target="_blank" rel="noreferrer">{link.title || link.url}</a>
                  {" / "}{link.competitor}{" / "}{displayLabel(link.dimension, locale)}
                  <br />{t('handoff.historyCaptured')}: {link.captured_at}
                  {link.source_published_at ? <> / {t('handoff.historyPublished')}: {link.source_published_at}</> : null}
                  {link.source_updated_at ? <> / {t('handoff.historyUpdated')}: {link.source_updated_at}</> : null}
                  {" / "}{historyReasonLabel(link.reason, locale)}
                </p>
              ))}
            </details>
          ) : null}
        </div>
      ) : null}

      <div className="agent-workload-grid">
        <article>
          <ListChecks size={15} aria-hidden />
          <strong>{t('handoff.taskSplit')}</strong>
          <span>
            {t('tasks.collector')} {stageCounts.collector} / {t('tasks.analyst')} {stageCounts.analyst} / {t('tasks.research')} {stageCounts.survey_interview}
          </span>
        </article>
        <article>
          <ShieldCheck size={15} aria-hidden />
          <strong>{t('handoff.reflectorInput')}</strong>
          <span>
            {detail.comparison_matrix ? `${detail.comparison_matrix.cells.length} ${t('handoff.matrixCells')}` : t('handoff.matrixPending')} /{" "}
            {detail.reflections.length} {t('handoff.reviews')}
          </span>
        </article>
        <article>
          <FileText size={15} aria-hidden />
          <strong>{t('handoff.writerSurface')}</strong>
          <span>{detail.report_md.length.toLocaleString()} {t('summary.characters')} / {writerSections.length || 0} {t('handoff.repairSections')}</span>
        </article>
      </div>

      {latestReflection?.writer_constraints.length ? (
        <div className="handoff-constraint-list">
          {latestReflection.writer_constraints.slice(0, compact ? 2 : 5).map((constraint) => (
            <span key={constraint}>{constraint}</span>
          ))}
        </div>
      ) : null}

      {!compact && latestReflection?.blocking_gaps.length ? (
        <div className="handoff-gap-list">
          {latestReflection.blocking_gaps.slice(0, 4).map((gap) => (
            <span key={gap}>{gap}</span>
          ))}
        </div>
      ) : null}

      {!compact && taskReasons.length ? (
        <div className="handoff-rationale-list">
          {taskReasons.map((reason) => (
            <span key={reason}>{reason}</span>
          ))}
        </div>
      ) : null}

      <div className="handoff-route-list">
        {handoffs.map((handoff) => (
          <article key={`${handoff.from}-${handoff.to}`}>
            <strong>{displayLabel(handoff.from, locale)} -&gt; {displayLabel(handoff.to, locale)}</strong>
            <StatusPill tone={handoff.linked ? "good" : "neutral"}>{displayLabel(handoff.linked ? "linked" : "pending", locale)}</StatusPill>
            <span>
              {displayLabel(handoff.label, locale)}
              {handoff.count > 1 ? ` / ${handoff.count} ${t('handoff.messages')}` : handoff.inferred ? ` / ${t('handoff.inferred')}` : ""}
            </span>
          </article>
        ))}
      </div>
    </Panel>
  );
}

function historyReasonLabel(reason: string, locale: string) {
  const labels: Record<string, [string, string]> = {
    expired: ["事实已过期", "Historical fact expired"],
    stale: ["来源已标记过期", "Source marked stale"],
    unreviewed: ["历史来源尚未审查", "Historical source unreviewed"],
    current_fetch_required: ["原始链接待重新核验", "Original URL needs verification"],
    future_capture: ["采集时间异常", "Capture time invalid"],
    market_conflict: ["市场不一致", "Market conflict"],
    version_conflict: ["产品版本不一致", "Product version conflict"],
    category_conflict: ["产品品类不一致", "Product category conflict"],
    category_unconfirmed: ["产品品类关系未确认", "Category relation unconfirmed"],
    product_identity_missing: ["缺少匹配的产品身份", "Matching product identity missing"],
    dimension_mismatch: ["研究维度不匹配", "Research dimensions differ"],
    not_explicit_real: ["未明确来自真实研究", "Real research provenance unconfirmed"],
    simulated_source: ["来源为模拟资料", "Simulated source"],
    non_fetched_source: ["来源没有真实采集证明", "Source has no real capture proof"],
    provenance_unknown: ["历史采集来源未确认", "Historical capture provenance unconfirmed"],
    scope_mismatch: ["工作区或项目范围不一致", "Workspace or project scope mismatch"],
    rejected: ["历史资料已被拒绝", "Historical material rejected"],
    missing_url: ["缺少原始链接", "Original URL missing"],
    unsafe_url: ["原始链接不可采集", "Original URL cannot be collected"],
    duplicate_url: ["原始链接重复", "Duplicate original URL"],
    superseded_report: ["已有更新的报告版本", "Newer report version exists"],
    report_limit: ["已达历史报告数量上限", "Historical report limit reached"],
    context_limit: ["已达历史线索容量上限", "Historical context limit reached"],
  };
  return labels[reason]?.[locale === "zh-CN" ? 0 : 1] ?? (locale === "zh-CN" ? "历史线索不可复用" : "Historical context unavailable");
}

function SignalBlock({
  detail,
  label,
  tone,
  value,
}: {
  detail: string;
  label: string;
  tone: "good" | "neutral" | "warn" | "bad";
  value: string;
}) {
  return (
    <article className="handoff-signal-block">
      <span>{label}</span>
      <StatusPill tone={tone}>{value}</StatusPill>
      <em>{detail}</em>
    </article>
  );
}

function buildHandoffRows(detail: RunDetailRecord, messages: AgentMessage[]) {
  return EXPECTED_HANDOFFS.map(([from, to, label]) => {
    const count = messages.filter((message) => message.from_agent === from && message.to_agent === to).length;
    const inferred = inferHandoffFromRunState(detail, from, to);
    return {
      count,
      from,
      inferred,
      label,
      linked: count > 0 || inferred,
      to,
    };
  });
}

function inferHandoffFromRunState(detail: RunDetailRecord, from: string, to: string) {
  if (from === "comparator" && to === "reflector") {
    return Boolean(detail.comparison_matrix && detail.reflections.length);
  }
  if (from === "reflector" && to === "writer") {
    return detail.reflections.length > 0 && detail.report_md.trim().length > 0;
  }
  if (from === "writer" && to === "qa") {
    return detail.report_md.trim().length > 0 && ["completed", "completed_with_blockers"].includes(detail.status);
  }
  return false;
}

function countPlanStages(detail: RunDetailRecord) {
  return detail.plan.task_decomposition.reduce(
    (counts, task) => {
      counts[task.stage] += 1;
      return counts;
    },
    { analyst: 0, collector: 0, survey_interview: 0 },
  );
}

function latestMessage(messages: AgentMessage[], predicate: (message: AgentMessage) => boolean) {
  return [...messages].reverse().find(predicate);
}

function latestSpan(spans: TraceSpan[], predicate: (span: TraceSpan) => boolean) {
  return [...spans].reverse().find(predicate);
}

function payloadString(payload: Record<string, unknown> | undefined, key: string) {
  const value = payload?.[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function payloadStringList(payload: Record<string, unknown> | undefined, key: string) {
  const value = payload?.[key];
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function metadataString(span: TraceSpan | undefined, key: string) {
  const value = span?.metadata[key];
  return typeof value === "string" && value.trim() ? value : null;
}

function gateTone(gate: string | undefined) {
  if (gate === "block") return "bad";
  if (gate === "warn") return "warn";
  if (gate === "pass") return "good";
  return "neutral";
}
