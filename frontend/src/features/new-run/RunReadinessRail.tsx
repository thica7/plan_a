import {
  AlertTriangle,
  CheckCircle2,
  Database,
  FileCheck2,
  KeyRound,
  Play,
  RefreshCw,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import type { ReactNode } from "react";
import type {
  RuntimeConfig,
  ScenarioPack,
  WorkspaceQuotaDecision,
} from "../../api/types";
import { ActionButton } from "../../components/interaction/ActionButton";
import { useTranslation } from "../../stores/i18n";
import { RuntimeLine } from "./RuntimeLine";
import type { CompetitorMode, ExecutionMode, LayerSelection } from "./types";

interface RunReadinessRailProps {
  autoRedoWarn: boolean;
  competitorList: string[];
  competitorMode: CompetitorMode;
  dynamicScenarioSelected: boolean;
  error: string | null;
  executionMode: ExecutionMode;
  hitlEnabled: boolean;
  isSubmitting: boolean;
  quotaDecision: WorkspaceQuotaDecision | null;
  runBlockedByQuota: boolean;
  runtime: RuntimeConfig | null;
  selected: string[];
  selectedLayer: LayerSelection;
  selectedScenario: ScenarioPack | null;
  setAutoRedoWarn: (enabled: boolean) => void;
  toggleHitl: (enabled: boolean) => void;
}

export function RunReadinessRail({
  autoRedoWarn,
  competitorList,
  competitorMode,
  dynamicScenarioSelected,
  error,
  executionMode,
  hitlEnabled,
  isSubmitting,
  quotaDecision,
  runBlockedByQuota,
  runtime,
  selected,
  selectedLayer,
  selectedScenario,
  setAutoRedoWarn,
  toggleHitl,
}: RunReadinessRailProps) {
  const { t } = useTranslation();

  const llmReady = Boolean(
    (runtime?.has_ark_api_key && runtime.has_ark_model) ||
      (runtime?.has_backup_llm_api_key && runtime.has_backup_llm_model),
  );
  const searchReady = Boolean(runtime?.has_web_search_key);
  const temporalReady = Boolean(runtime?.temporal_cutover_ready);
  const pydanticReady = Boolean(runtime?.pydantic_ai_model_backed_ready);
  const complianceReady = Boolean(runtime?.compliance_redaction_enabled);
  const readyCount = [
    llmReady,
    searchReady,
    temporalReady,
    complianceReady,
    quotaDecision?.allowed !== false,
    selected.length > 0,
  ].filter(Boolean).length;
  const readinessStatus = runBlockedByQuota
    ? t('run.readiness.blocked')
    : readyCount >= 5
      ? t('run.readiness.ready')
      : t('run.readiness.review');
  const competitorSummary =
    competitorMode === "auto"
      ? t('newRun.autoDiscover')
      : competitorList.length > 0
        ? `${competitorList.length} ${t('run.selected')}`
        : t('newRun.manual');

  return (
    <aside className="run-builder-rail">
      <section className="panel run-readiness-panel">
        <div className="run-readiness-header">
          <div>
            <h2>{t('run.readiness.title')}</h2>
            <p>{t('run.readiness.description')}</p>
          </div>
          <span className={runBlockedByQuota ? "flow-status failed" : "flow-status pass"}>
            <CheckCircle2 size={14} aria-hidden />
            {readinessStatus}
          </span>
        </div>

        <div className="readiness-checklist" aria-label={t('run.readiness.checklist')}>
          <ReadinessItem icon={<ShieldCheck size={15} />} ok={Boolean(quotaDecision?.allowed ?? true)} title={t('run.workspace')}>
            {quotaDecision?.allowed === false ? quotaDecision.reason : t('run.acmeCorp')}
          </ReadinessItem>
          <ReadinessItem icon={<FileCheck2 size={15} />} ok={selected.length > 0} title={t('newRun.dimensions')}>
            {selected.length} {t('run.selected')}
          </ReadinessItem>
          <ReadinessItem icon={<Database size={15} />} ok={searchReady} title={t('run.dataSources')}>
            {runtime?.has_web_search_key ? `${runtime.web_search_provider}, ${t('run.web')}, ${t('run.registry')}` : t('run.searchKeyMissing')}
          </ReadinessItem>
          <ReadinessItem icon={<KeyRound size={15} />} ok={llmReady} title={t('run.modelRoute')}>
            {runtime?.has_ark_api_key && runtime.has_ark_model
              ? runtime.ark_model
              : runtime?.has_backup_llm_api_key && runtime.has_backup_llm_model
                ? runtime.backup_llm_model
                : t('run.credentialsMissing')}
          </ReadinessItem>
          <ReadinessItem icon={<UserCheck size={15} />} ok={hitlEnabled || autoRedoWarn} title={t('run.qualityControls')}>
            {hitlEnabled ? t('run.humanReviewEnabled') : autoRedoWarn ? t('run.autoRedoEnabled') : t('run.manualLaunch')}
          </ReadinessItem>
        </div>

        <div className="readiness-section">
          <header>
            <h3>{t('run.costEstimate')}</h3>
            <ActionButton
              className="ghost-button"
              authenticity={{
                actionId: 'new-run.cost-details.disabled',
                kind: 'disabled',
                description: 'detailed cost breakdown not available in demo'
              }}
              disabled
              disabledReason={t('run.details.disabled')}
            >
              {t('run.details')}
            </ActionButton>
          </header>
          <strong className="cost-estimate">~$48.60</strong>
          <dl className="readiness-cost-list">
            <div>
              <dt>{t('run.llmCalls')}</dt>
              <dd>~$28.20</dd>
            </div>
            <div>
              <dt>{t('run.webSearch')}</dt>
              <dd>~$12.40</dd>
            </div>
            <div>
              <dt>{t('run.embeddingVector')}</dt>
              <dd>~$5.80</dd>
            </div>
            <div>
              <dt>{t('run.storageTrace')}</dt>
              <dd>~$2.20</dd>
            </div>
          </dl>
        </div>

        <div className="readiness-section">
          <header>
            <h3>{t('run.sourcePolicy')}</h3>
            <span>{t('run.strict')}</span>
          </header>
          <dl className="readiness-cost-list">
            <div>
              <dt>{t('run.verifiedSourcesOnly')}</dt>
              <dd>{t('run.required')}</dd>
            </div>
            <div>
              <dt>{t('run.minDomainAuthority')}</dt>
              <dd>40</dd>
            </div>
            <div>
              <dt>{t('run.maxSourcesPerClaim')}</dt>
              <dd>5</dd>
            </div>
            <div>
              <dt>{t('run.citationRequired')}</dt>
              <dd>{t('common.yes')}</dd>
            </div>
          </dl>
        </div>

        <div className="readiness-section">
          <header>
            <h3>{t('run.runtimeSignals')}</h3>
            <span>{executionMode}</span>
          </header>
          <div className="runtime-lines compact">
            <RuntimeLine ok={searchReady}>
              {searchReady ? `${runtime?.web_search_provider} ${t('run.searchEnabled')}` : t('run.searchCredentialsMissing')}
            </RuntimeLine>
            <RuntimeLine ok={temporalReady}>
              {temporalReady ? `Temporal ${runtime?.temporal_task_queue}` : runtime?.temporal_cutover_reason ?? t('run.temporalUnavailable')}
            </RuntimeLine>
            <RuntimeLine ok={pydanticReady}>
              {pydanticReady
                ? `Pydantic-AI ${runtime?.pydantic_ai_model_name}`
                : runtime?.pydantic_ai_model_backed_reason ?? t('run.pydanticDisabled')}
            </RuntimeLine>
            <RuntimeLine ok={complianceReady}>
              {complianceReady ? t('run.complianceRedactionEnabled') : t('run.complianceRedactionDisabled')}
            </RuntimeLine>
          </div>
        </div>

        <div className="readiness-section">
          <header>
            <h3>{t('run.hitlCheckpoints')}</h3>
            <span>{hitlEnabled ? t('common.enabled') : t('common.optional')}</span>
          </header>
          <label className="toggle-row compact">
            <input
              checked={autoRedoWarn}
              disabled={runtime?.auto_redo_enabled === false || hitlEnabled}
              onChange={(event) => setAutoRedoWarn(event.target.checked)}
              type="checkbox"
            />
            <span>
              <strong>{t('run.autoRedoWarnings')}</strong>
              <em>{t('run.autoRedoWarningsDesc')}</em>
            </span>
          </label>
          <label className="toggle-row compact">
            <input
              checked={hitlEnabled}
              onChange={(event) => toggleHitl(event.target.checked)}
              type="checkbox"
            />
            <span>
              <strong>{t('run.humanReviewPauses')}</strong>
              <em>{t('run.humanReviewPausesDesc')}</em>
            </span>
          </label>
        </div>

        {error ? <p className="error-line">{error}</p> : null}

        <ActionButton
          className="primary-button full-width"
          type="submit"
          authenticity={{
            actionId: 'new-run.submit',
            kind: 'submit',
            description: 'submits the new run builder form'
          }}
          disabled={selected.length === 0 || runBlockedByQuota}
          disabledReason={
            runBlockedByQuota
              ? quotaDecision?.reason || t('run.disabled.quota')
              : selected.length === 0
                ? t('run.disabled.dimensions')
                : undefined
          }
          isLoading={isSubmitting}
          loadingLabel={t('run.submitting')}
        >
          {isSubmitting ? <RefreshCw size={18} aria-hidden /> : <Play size={18} aria-hidden />}
          {t('run.submit')}
        </ActionButton>
      </section>

      <section className="panel run-contract-panel">
        <h2>{t('run.runContract')}</h2>
        <dl className="contract-list">
          <div>
            <dt>{t('runHeader.layer')}</dt>
            <dd>{selectedLayer}</dd>
          </div>
          <div>
            <dt>{t('runHeader.scenario')}</dt>
            <dd>{selectedScenario?.name ?? (dynamicScenarioSelected ? t('run.dynamic') : t('newRun.auto'))}</dd>
          </div>
          <div>
            <dt>{t('newRun.competitors')}</dt>
            <dd>{competitorSummary}</dd>
          </div>
        </dl>
        <div className="contract-chips">
          {selected.map((dimension) => (
            <span key={dimension}>{dimension}</span>
          ))}
        </div>
      </section>
    </aside>
  );
}

function ReadinessItem({
  children,
  icon,
  ok,
  title,
}: {
  children: ReactNode;
  icon: ReactNode;
  ok: boolean;
  title: string;
}) {
  return (
    <div className={ok ? "readiness-item ok" : "readiness-item warn"}>
      <span>{icon}</span>
      <div>
        <strong>{title}</strong>
        <em>{children}</em>
      </div>
      {ok ? <CheckCircle2 size={14} aria-hidden /> : <AlertTriangle size={14} aria-hidden />}
    </div>
  );
}
