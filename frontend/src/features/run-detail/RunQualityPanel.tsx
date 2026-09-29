import { AlertTriangle, CheckCircle2, Loader2 } from "lucide-react";
import type { RunQualityComparison, RunSummary } from "../../api/types";
import { useTranslation } from "../../stores/i18n";
import { displayLabel, runtimeDiagnostic } from "../../i18n/display";
import { SystemMessage } from "../../i18n/SystemMessage";
import { MetricValue } from "./MetricValue";
import { formatQualityValue, metricWeightedLoss } from "./utils";

interface RunQualityPanelProps {
  baselineRunId: string;
  comparison: RunQualityComparison | null;
  onBaselineRunChange: (runId: string) => void;
  runHistory: RunSummary[];
}

export function RunQualityPanel({
  baselineRunId,
  comparison,
  onBaselineRunChange,
  runHistory,
}: RunQualityPanelProps) {
  const { locale, t } = useTranslation();
  if (!comparison) {
    return (
      <aside className="qa-panel run-quality-panel">
        <div className="panel-heading-row">
          <h2>{t("runQuality.title")}</h2>
          <Loader2 className="spin" size={16} aria-hidden />
        </div>
        <p className="muted-text">{t('runQuality.loading')}</p>
      </aside>
    );
  }

  const signalRows = [
    ["Real collection", comparison.real_collection_signal],
    ["Real LLM", comparison.real_llm_signal],
    ["Report quality", comparison.report_quality_signal],
  ] as const;
  const signalChecks =
    comparison.signal_checks.length > 0
      ? comparison.signal_checks
      : signalRows.map(([label, enabled]) => ({
          signal: label.toLowerCase().replace(/\s+/g, "_"),
          label,
          passed: enabled,
          reason: enabled ? "Signal passed." : "Signal did not pass.",
          blocking_metric_names: [],
        }));
  const failedSignalChecks = signalChecks.filter((check) => !check.passed);
  const highlightedMetrics = comparison.metrics
    .filter((metric) => metric.status === "regressed" || metric.target_normalized_score < 0.999)
    .sort((left, right) => metricWeightedLoss(right) - metricWeightedLoss(left))
    .slice(0, 5);

  return (
    <aside className={`qa-panel run-quality-panel ${comparison.verdict}`}>
      <div className="panel-heading-row">
        <h2>{t("runQuality.title")}</h2>
        <div className="panel-heading-actions">
          <label className="compact-select">
            <span>{t("runQuality.baseline")}</span>
            <select
              aria-label={t('runQuality.baselineLabel')}
              onChange={(event) => onBaselineRunChange(event.target.value)}
              value={baselineRunId}
            >
              <option value="">{t('common.none')}</option>
              {runHistory.slice(0, 30).map((run) => (
                <option key={run.id} value={run.id}>
                  {run.topic} / {run.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </label>
          {comparison.verdict === "pass" ? (
            <CheckCircle2 size={16} aria-hidden />
          ) : (
            <AlertTriangle size={16} aria-hidden />
          )}
        </div>
      </div>
      <div className="metric-grid compact">
        <MetricValue label={t("runQuality.score")} value={`${comparison.target_score}/100`} />
        <MetricValue label={t("runQuality.verdict")} value={displayLabel(comparison.verdict, locale)} />
        <MetricValue label={t("runQuality.gate")} value={displayLabel(comparison.regression_gate_status, locale)} />
        <MetricValue
          label={t("runQuality.baseline")}
          value={comparison.baseline_score === null || comparison.baseline_score === undefined ? t('common.none') : `${comparison.baseline_score}/100`}
        />
        <MetricValue
          label={t("runQuality.delta")}
          value={comparison.delta_score === null || comparison.delta_score === undefined ? t('common.unavailable') : String(comparison.delta_score)}
        />
      </div>
      <div className="run-quality-signals">
        {signalChecks.map((check) => (
          <span className={check.passed ? "on" : "off"} key={check.signal} title={runtimeDiagnostic(check.reason, locale)}>
            {check.passed ? <CheckCircle2 size={13} aria-hidden /> : <AlertTriangle size={13} aria-hidden />}
            {displayLabel(check.label, locale)}
          </span>
        ))}
      </div>
      <div className="reflection-review">
        <h3>{t('runQuality.regressionGate')}</h3>
        {comparison.regression_gate_reasons.map((reason) => (
          <article className="issue-row reflection-row" key={reason}>
            <strong>{displayLabel(comparison.regression_gate_passed ? "pass" : comparison.regression_gate_status, locale)}</strong>
            <SystemMessage message={reason} />
          </article>
        ))}
      </div>
      {failedSignalChecks.length > 0 ? (
        <div className="reflection-review">
          <h3>{t('runQuality.signalBlockers')}</h3>
          {failedSignalChecks.map((check) => (
            <article className="issue-row reflection-row" key={check.signal}>
              <strong>{displayLabel(check.label, locale)}</strong>
              <span>
                <SystemMessage message={check.reason} />
                {check.blocking_metric_names.length > 0
                  ? ` ${t('runQuality.blockedBy')} ${check.blocking_metric_names.map((name) => displayLabel(name, locale)).join(", ")}.`
                  : ""}
              </span>
            </article>
          ))}
        </div>
      ) : null}
      {highlightedMetrics.length > 0 ? (
        <div className="reflection-review">
          <h3>{t('runQuality.scoreDrivers')}</h3>
          {highlightedMetrics.map((metric) => (
            <article className="issue-row reflection-row" key={metric.name}>
              <strong>
                {Math.round(metric.target_normalized_score * 100)}/100
              </strong>
              <span>
                {displayLabel(metric.name, locale)}: {t('common.rawValue')} {formatQualityValue(metric.target_value)}
                {metricWeightedLoss(metric) > 0
                  ? ` / ${t('runQuality.weightedLoss')} ${metricWeightedLoss(metric).toFixed(1)} ${t('common.points')}`
                  : ""}
                {metric.baseline_value !== null && metric.baseline_value !== undefined
                  ? ` / ${t('runQuality.baseline')} ${formatQualityValue(metric.baseline_value)}`
                  : ""}
              </span>
            </article>
          ))}
        </div>
      ) : null}
      {comparison.recommendations.length > 0 ? (
        <div className="reflection-review">
          <h3>{t("runQuality.recommendations")}</h3>
          {comparison.recommendations.slice(0, 3).map((item) => (
            <article className="issue-row reflection-row" key={item}>
              <strong>{t('workbench.next')}</strong>
              <SystemMessage message={item} />
            </article>
          ))}
        </div>
      ) : null}
    </aside>
  );
}
